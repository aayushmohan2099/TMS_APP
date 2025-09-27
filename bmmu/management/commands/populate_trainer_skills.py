# bmmu/management/commands/populate_trainer_skills.py
import random
from django.core.management.base import BaseCommand
from django.db import transaction

SKILLS_POOL = [
    "Soil Health", "Organic Farming", "Post-harvest Management", "Seed Selection",
    "Crop Rotation", "Pest Management", "Integrated Pest Management", "Nutrition",
    "Maternal Care", "Child Health", "COVID Safety", "WASH", "Sanitation",
    "SHG Formation", "Book Keeping", "Microenterprise", "Livelihood Skills",
    "Vocational Training", "Gender Sensitization", "Leadership", "Financial Literacy",
    "Digital Literacy", "Entrepreneurship", "Communication Skills", "Public Speaking",
    "Climate Resilience", "Irrigation Management", "Organic Certification",
    "Value Chain Development", "Market Linkages", "Business Planning"
]

class Command(BaseCommand):
    help = "Populate MasterTrainer.skills with randomly chosen skills (comma-separated)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--min", type=int, default=3,
            help="Minimum number of skills to assign per trainer (default: 3)"
        )
        parser.add_argument(
            "--max", type=int, default=7,
            help="Maximum number of skills to assign per trainer (default: 7)"
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Overwrite existing skills even if present"
        )
        parser.add_argument(
            "--seed", type=int, default=None,
            help="Optional random seed for reproducible assignments"
        )
        parser.add_argument(
            "--commit", action="store_true",
            help="If provided, save changes to DB. Otherwise runs as dry-run and only prints what would change."
        )

    def handle(self, *args, **options):
        from bmmu.models import MasterTrainer  # local import to avoid startup issues
        min_sk = max(1, options["min"])
        max_sk = max(min_sk, options["max"])
        force = options["force"]
        seed = options["seed"]
        commit = options["commit"]

        if seed is not None:
            random.seed(seed)

        trainers = list(MasterTrainer.objects.all())
        total = len(trainers)
        if total == 0:
            self.stdout.write(self.style.WARNING("No MasterTrainer records found. Nothing to do."))
            return

        self.stdout.write(f"Found {total} MasterTrainer records. Preparing assignments (min={min_sk}, max={max_sk}).")
        changed = 0
        skipped = 0
        preview = []

        for t in trainers:
            current = (t.skills or "").strip()
            if current and not force:
                skipped += 1
                preview.append((t.id, t.full_name, "SKIP (exists)"))
                continue

            # choose random number of skills
            n = random.randint(min_sk, max_sk)
            # pick n unique skills
            n = min(n, len(SKILLS_POOL))
            chosen = random.sample(SKILLS_POOL, n)
            skill_str = ", ".join(chosen)

            preview.append((t.id, t.full_name, skill_str))

            if commit:
                try:
                    with transaction.atomic():
                        t.skills = skill_str
                        t.save(update_fields=["skills"])
                except Exception as e:
                    self.stderr.write(f"Failed to save trainer id={t.id} name={t.full_name}: {e}")
                    continue
                changed += 1

        # Print summary
        self.stdout.write("")
        self.stdout.write("Preview of changes (first 50 shown):")
        for row in preview[:50]:
            tid, name, skills = row
            self.stdout.write(f" - id={tid} | {name} -> {skills}")

        self.stdout.write("")
        if commit:
            self.stdout.write(self.style.SUCCESS(f"Committed changes. {changed} trainers updated. {skipped} skipped."))
        else:
            self.stdout.write(self.style.WARNING(f"DRY RUN (no DB writes). {len(preview)-skipped} would be updated. {skipped} skipped."))
            self.stdout.write(self.style.NOTICE("Rerun with --commit to persist changes. Use --force to overwrite existing skills."))

