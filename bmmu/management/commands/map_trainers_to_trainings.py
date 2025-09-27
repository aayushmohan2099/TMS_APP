import re
import random
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.apps import apps

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize_text(s):
    """Return a set of lowercase alphanumeric tokens (length>1) from input."""
    if not s:
        return set()
    return set(t.lower() for t in TOKEN_RE.findall(str(s)) if len(t) > 1)


def split_skills_field(skills_raw):
    """Split a comma/semicolon separated skills string into normalized phrases."""
    if not skills_raw:
        return []
    parts = re.split(r'[;,]+', skills_raw)
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out


class Command(BaseCommand):
    help = "Map MasterTrainer -> TrainingPlan by matching trainer.skills against training_name/theme and populate MasterTrainerExpertise."

    def add_arguments(self, parser):
        parser.add_argument('--min-score', type=int, default=1, help='Minimum token-overlap score to consider (default 1).')
        parser.add_argument('--top-n', type=int, default=3, help='Create up to top-n matches per trainer (default 3). Use 0 for all matches >= min-score.')
        parser.add_argument('--commit', action='store_true', help='Persist changes to DB. Without this flag the command will perform a dry-run.')
        parser.add_argument('--seed', type=int, default=None, help='Optional random seed for reproducible proficiency values / sampling.')
        parser.add_argument('--xlsx', type=str, default=None, help='Optional path to an XLSX/CSV file listing trainings (columns: training_name, theme). Requires pandas.')
        parser.add_argument('--limit-trainings', type=int, default=0, help='If >0, sample at most this many training plans from DB for matching.')
        parser.add_argument('--proficiency-range', type=str, default='5,9', help='Comma pair min,max for random proficiency (inclusive). Default "5,9".')

    def handle(self, *args, **options):
        MasterTrainer = apps.get_model('bmmu', 'MasterTrainer')
        TrainingPlan = apps.get_model('bmmu', 'TrainingPlan')
        MasterTrainerExpertise = apps.get_model('bmmu', 'MasterTrainerExpertise')

        if options['seed'] is not None:
            random.seed(options['seed'])

        min_score = max(0, int(options.get('min_score', 1)))
        top_n = int(options.get('top_n', 3))
        commit = bool(options.get('commit', False))
        xlsx_path = options.get('xlsx')
        limit_trainings = int(options.get('limit_trainings', 0))
        prof_range = options.get('proficiency_range', '5,9')
        try:
            prof_min, prof_max = [int(x) for x in prof_range.split(',')]
        except Exception:
            prof_min, prof_max = 5, 9

        self.stdout.write(f"Mapping trainers -> trainings (min_score={min_score}, top_n={top_n}, commit={commit})")

        # Load trainings: prefer xlsx if given
        trainings = []
        if xlsx_path:
            try:
                import pandas as pd
                df = pd.read_excel(xlsx_path) if xlsx_path.lower().endswith('.xlsx') else pd.read_csv(xlsx_path)
                for _, row in df.iterrows():
                    name = row.get('training_name') or row.get('training') or row.get('module') or None
                    theme = row.get('theme') or ''
                    if name and str(name).strip():
                        trainings.append({'training_name': str(name).strip(), 'theme': str(theme).strip()})
                self.stdout.write(self.style.SUCCESS(f"Loaded {len(trainings)} trainings from {xlsx_path}"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Failed to read {xlsx_path}: {e}. Falling back to DB trainings."))

        if not trainings:
            qs = TrainingPlan.objects.all().only('id', 'training_name', 'theme')
            if limit_trainings and 0 < limit_trainings < qs.count():
                qs = qs.order_by('?')[:limit_trainings]
            for tp in qs:
                trainings.append({'id': tp.id, 'training_name': tp.training_name, 'theme': getattr(tp, 'theme', '')})
            self.stdout.write(self.style.SUCCESS(f"Loaded {len(trainings)} trainings from DB"))

        if not trainings:
            self.stdout.write(self.style.ERROR("No trainings available to map. Exiting."))
            return

        # Precompute tokens for trainings
        training_data = []
        for t in trainings:
            text = f"{t.get('training_name') or ''} {t.get('theme') or ''}"
            tokens = tokenize_text(text)
            training_data.append({'obj': t, 'tokens': tokens})

        trainers = list(MasterTrainer.objects.all())
        if not trainers:
            self.stdout.write(self.style.ERROR("No MasterTrainer records found. Exiting."))
            return

        created = 0
        skipped_existing = 0
        skipped_score = 0
        preview_rows = []

        for trainer in trainers:
            skills_raw = getattr(trainer, 'skills', '') or ''
            skill_phrases = split_skills_field(skills_raw)
            skill_tokens = set()
            for p in skill_phrases:
                skill_tokens |= tokenize_text(p)
            # fallback to full name tokens if skills empty
            if not skill_tokens:
                skill_tokens |= tokenize_text(trainer.full_name)

            # compute match score against each training
            matches = []
            for t in training_data:
                if not t['tokens']:
                    continue
                common = skill_tokens & t['tokens']
                score = len(common)
                if score >= min_score:
                    matches.append((score, t['obj'], common))

            # sort by score desc, then name
            matches.sort(key=lambda x: (-x[0], str(x[1].get('training_name'))))

            if top_n > 0:
                matches = matches[:top_n]

            if not matches:
                preview_rows.append((trainer.id, trainer.full_name, None, 0, 'NO_MATCH'))
                continue

            for score, training_obj, common in matches:
                # resolve TrainingPlan instance
                tp_instance = None
                tp_id = training_obj.get('id')
                if tp_id:
                    try:
                        tp_instance = TrainingPlan.objects.get(id=tp_id)
                    except TrainingPlan.DoesNotExist:
                        tp_instance = TrainingPlan.objects.filter(training_name=training_obj.get('training_name')).first()
                else:
                    tp_instance = TrainingPlan.objects.filter(training_name=training_obj.get('training_name')).first()

                if tp_instance is None:
                    preview_rows.append((trainer.id, trainer.full_name, training_obj.get('training_name'), score, 'NO_TP_INSTANCE'))
                    continue

                # skip existing mappings
                exists = MasterTrainerExpertise.objects.filter(trainer=trainer, training_plan=tp_instance).exists()
                if exists:
                    skipped_existing += 1
                    preview_rows.append((trainer.id, trainer.full_name, tp_instance.training_name, score, 'EXISTS'))
                    continue

                # choose a proficiency randomly within provided range
                prof = random.randint(prof_min, prof_max)

                preview_rows.append((trainer.id, trainer.full_name, tp_instance.training_name, score, f'CREATE prof={prof}'))

                if commit:
                    try:
                        with transaction.atomic():
                            MasterTrainerExpertise.objects.create(
                                trainer=trainer,
                                training_plan=tp_instance,
                                proficiency=prof,
                                recommended=True,
                                notes=f"Auto-mapped (score={score})"
                            )
                            created += 1
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Failed to create mapping for trainer {trainer.id} -> training {tp_instance.id}: {e}"))
                else:
                    skipped_score += 0  # placeholder for dry-run counting if desired

        # Print preview (first 200)
        self.stdout.write("\nPreview (first 200 rows):")
        for row in preview_rows[:200]:
            tid, tname, ttraining, score, action = row
            self.stdout.write(f" - Trainer(id={tid}) {tname} -> {ttraining} score={score} action={action}")

        self.stdout.write("\nSummary:")
        self.stdout.write(f" Trainers scanned: {len(trainers)}")
        self.stdout.write(f" Trainings considered: {len(training_data)}")
        if commit:
            self.stdout.write(self.style.SUCCESS(f" Created {created} MasterTrainerExpertise rows."))
        else:
            self.stdout.write(self.style.WARNING(" Dry-run: no DB writes were performed. Use --commit to persist."))
        self.stdout.write(f" Skipped (existing): {skipped_existing}")
        self.stdout.write("Done.")
