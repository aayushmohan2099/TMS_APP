# main/management/commands/link_existing_experts.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from bmmu.models import TrainingPlan
from django.db import transaction

User = get_user_model()

# ---------- MAPPING: theme -> username (existing user) ----------
# Use canonical usernames exactly as in your admin list.
# Do NOT include lovelesh@SMMU as you asked.
MAPPING = {
    "Farm LH": "SMM_FARMLH",
    "FNHW": "SMM_FNHW",
    "M&E": "SMM_ME",
    "MCLF": "SMM_MCLF",
    "MF&FI": "SMM_MF",
    "Non Farm": "SMM_NONFARM",
    "NONFARM LH": "SMM_NONFARMLH",
    "SISD": "SMM_SISD",
    "SMCB": "SMM_SMCB",
    "TNCB": "SMM_TNCB",
    "Fishery": "SMM_FISHERY",
}

# A little helper to normalize theme strings from DB and mapping keys consistently
def normalize_theme(s):
    if s is None:
        return ""
    return s.strip()

class Command(BaseCommand):
    help = "Link existing thematic expert users to existing TrainingPlan.theme_expert based on theme -> username mapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed, but do not save to DB."
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show verbose per-row output."
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']

        # Normalize mapping keys
        norm_map = { normalize_theme(k): v for k, v in MAPPING.items() }

        self.stdout.write(self.style.MIGRATE_HEADING("Link existing thematic experts to training plans"))
        self.stdout.write(f"Dry run: {dry_run}\n")

        # Build reverse mapping for quick lookup: username -> list of themes
        user_to_themes = {}
        for theme, username in norm_map.items():
            user_to_themes.setdefault(username, []).append(theme)

        # Stats
        assigned_count = 0
        skipped_no_user = []
        skipped_no_plan = []
        changed_rows = []

        # We'll run all updates inside a transaction; for dry-run we'll rollback at the end.
        with transaction.atomic():
            for theme_key, username in norm_map.items():
                # find user
                try:
                    user = User.objects.get(username=username)
                except User.DoesNotExist:
                    skipped_no_user.append((theme_key, username))
                    self.stdout.write(self.style.WARNING(f"User NOT FOUND for mapping: theme='{theme_key}' -> username='{username}'"))
                    continue

                # find matching TrainingPlan rows (case-insensitive exact match of theme)
                plans_qs = TrainingPlan.objects.filter(theme__iexact=theme_key)
                if not plans_qs.exists():
                    skipped_no_plan.append((theme_key, username))
                    self.stdout.write(self.style.WARNING(f"No TrainingPlan rows found with theme='{theme_key}' (mapped to {username})"))
                    continue

                # assign each plan
                for plan in plans_qs:
                    prev = plan.theme_expert
                    prev_username = prev.username if prev else None
                    if prev_username == username:
                        if verbose:
                            self.stdout.write(f"SKIP (already assigned) plan id={plan.id} theme='{plan.theme}' -> {username}")
                        continue

                    if dry_run:
                        self.stdout.write(self.style.NOTICE(f"[dry] would assign plan id={plan.id} theme='{plan.theme}' from '{prev_username}' -> '{username}'"))
                        changed_rows.append((plan.id, plan.theme, prev_username, username))
                    else:
                        plan.theme_expert = user
                        plan.save(update_fields=['theme_expert'])
                        assigned_count += 1
                        self.stdout.write(self.style.SUCCESS(f"Assigned plan id={plan.id} theme='{plan.theme}' to user '{username}' (was '{prev_username}')"))
                        changed_rows.append((plan.id, plan.theme, prev_username, username))

            # Finish loop

            if dry_run:
                # rollback the transaction by raising an exception intentionally (but we'll not raise — instead we rollback by exiting and not committing).
                # But because we're in atomic block, we can just let it exit: changes won't be committed because we didn't call commit explicitly.
                # Django will commit at the end of the outermost atomic unless an exception occurs — to be safe we will explicitly roll back:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("\nDry-run: no DB changes were saved (transaction rolled back)."))
            else:
                self.stdout.write(self.style.SUCCESS(f"\nDone. Assigned {assigned_count} TrainingPlan rows."))

        # Summary
        self.stdout.write("\nSummary:")
        if skipped_no_user:
            self.stdout.write(self.style.WARNING(f"Mapping entries skipped because user not found: {len(skipped_no_user)}"))
            for theme_key, username in skipped_no_user:
                self.stdout.write(f" - theme='{theme_key}' -> missing user '{username}'")
        if skipped_no_plan:
            self.stdout.write(self.style.WARNING(f"Mapping entries skipped because no TrainingPlan rows found: {len(skipped_no_plan)}"))
            for theme_key, username in skipped_no_plan:
                self.stdout.write(f" - theme='{theme_key}' (mapped to '{username}') has no TrainingPlan rows")
        self.stdout.write(self.style.NOTICE(f"Planned/affected rows: {len(changed_rows)}"))
        if changed_rows and verbose:
            self.stdout.write("Details of changed rows:")
            for pid, theme, prev, new in changed_rows:
                self.stdout.write(f" - plan id={pid} theme='{theme}' : {prev} -> {new}")

        self.stdout.write("\nTip: verify changes in admin / by running shell queries.")
