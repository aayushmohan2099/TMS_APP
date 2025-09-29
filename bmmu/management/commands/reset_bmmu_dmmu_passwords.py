import re
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from bmmu.models import BmmuBlockAssignment, DmmuDistrictAssignment

User = get_user_model()

def _normalize_for_password(name: str) -> str:
    """
    Build the normalized name fragment: remove spaces and non-alphanumeric,
    and convert to lowercase. Example: "Sant Kabeer nagar" -> "santkabeernagar"
    """
    if not name:
        return ""
    # remove non-alphanumeric characters, then lowercase
    cleaned = re.sub(r'[^0-9A-Za-z]', '', name)
    return cleaned.lower()

def _make_password_from_name(name_fragment: str) -> str:
    return f"{name_fragment}@admin25"

class Command(BaseCommand):
    help = "Reset passwords for BMMU (based on their Block assignment) and DMMU (based on their District assignment)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Actually write password changes to the database. Without this flag the command runs in dry-run mode.'
        )
        parser.add_argument(
            '--show-passwords',
            action='store_true',
            help='Print the new plaintext passwords to stdout (insecure — use only in safe environments).'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Optional: limit number of users to process (0 = no limit). Useful for testing.'
        )

    def handle(self, *args, **options):
        apply_changes = options.get('apply', False)
        show_passwords = options.get('show_passwords', False)
        limit = int(options.get('limit', 0)) or None

        self.stdout.write("Starting password reset process for BMMU and DMMU users.")
        if not apply_changes:
            self.stdout.write(self.style.WARNING("DRY RUN: No passwords will be changed. Use --apply to write changes."))

        # Collect BMMU users via assignments
        bmmu_qs = BmmuBlockAssignment.objects.select_related('user', 'block').all()
        dmmu_qs = DmmuDistrictAssignment.objects.select_related('user', 'district').all()

        # Optionally apply a limit across combined sets (if limit provided)
        # We'll enforce limit separately for each for simplicity
        if limit:
            bmmu_qs = bmmu_qs[:limit]
            dmmu_qs = dmmu_qs[:limit]

        bmmu_changes = []
        dmmu_changes = []
        errors = []

        # Process BMMU assignments
        for assign in bmmu_qs:
            try:
                user = assign.user
                # Only affect users actually marked as role 'bmmu' (safety)
                if getattr(user, 'role', None) != 'bmmu':
                    # Still allow if you want to override, but by default skip mismatches
                    self.stdout.write(self.style.NOTICE(f"Skipping {user.username}: user.role != 'bmmu' (role={getattr(user,'role',None)})"))
                    continue

                block = assign.block
                block_name = (block.block_name_en or "").strip()
                if not block_name:
                    self.stdout.write(self.style.WARNING(f"Skipped {user.username}: assigned block has no block_name_en"))
                    continue

                fragment = _normalize_for_password(block_name)
                if not fragment:
                    self.stdout.write(self.style.WARNING(f"Skipped {user.username}: block name normalized to empty string"))
                    continue

                new_password = _make_password_from_name(fragment)
                bmmu_changes.append((user, new_password, block_name))
            except Exception as e:
                errors.append((getattr(assign, 'user', '<unknown>'), str(e)))

        # Process DMMU assignments
        for assign in dmmu_qs:
            try:
                user = assign.user
                if getattr(user, 'role', None) != 'dmmu':
                    self.stdout.write(self.style.NOTICE(f"Skipping {user.username}: user.role != 'dmmu' (role={getattr(user,'role',None)})"))
                    continue

                district = assign.district
                district_name = (district.district_name_en or "").strip()
                if not district_name:
                    self.stdout.write(self.style.WARNING(f"Skipped {user.username}: assigned district has no district_name_en"))
                    continue

                fragment = _normalize_for_password(district_name)
                if not fragment:
                    self.stdout.write(self.style.WARNING(f"Skipped {user.username}: district name normalized to empty string"))
                    continue

                new_password = _make_password_from_name(fragment)
                dmmu_changes.append((user, new_password, district_name))
            except Exception as e:
                errors.append((getattr(assign, 'user', '<unknown>'), str(e)))

        # Summarize
        total_bmmu = len(bmmu_changes)
        total_dmmu = len(dmmu_changes)
        self.stdout.write(self.style.SUCCESS(f"Prepared {total_bmmu} BMMU password updates and {total_dmmu} DMMU password updates."))

        # Perform updates in a transaction if requested
        if apply_changes:
            try:
                with transaction.atomic():
                    # Update BMMU users
                    for user, pwd, block_name in bmmu_changes:
                        user.set_password(pwd)
                        user.save(update_fields=['password'])
                        self.stdout.write(self.style.SUCCESS(f"BMMU: {user.username} -> password set based on block '{block_name}'"))
                        if show_passwords:
                            self.stdout.write(f"  new_password: {pwd}")

                    # Update DMMU users
                    for user, pwd, district_name in dmmu_changes:
                        user.set_password(pwd)
                        user.save(update_fields=['password'])
                        self.stdout.write(self.style.SUCCESS(f"DMMU: {user.username} -> password set based on district '{district_name}'"))
                        if show_passwords:
                            self.stdout.write(f"  new_password: {pwd}")

                self.stdout.write(self.style.SUCCESS("All requested password changes have been applied."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error applying password changes: {e}"))
        else:
            # Dry-run: print sample of planned changes
            if total_bmmu:
                self.stdout.write(self.style.NOTICE("BMMU planned changes (dry-run):"))
                for user, pwd, block_name in bmmu_changes:
                    if show_passwords:
                        self.stdout.write(f"  {user.username} -> {pwd}  (block: {block_name})")
                    else:
                        self.stdout.write(f"  {user.username} -> [will set based on block: {block_name}]")

            if total_dmmu:
                self.stdout.write(self.style.NOTICE("DMMU planned changes (dry-run):"))
                for user, pwd, district_name in dmmu_changes:
                    if show_passwords:
                        self.stdout.write(f"  {user.username} -> {pwd}  (district: {district_name})")
                    else:
                        self.stdout.write(f"  {user.username} -> [will set based on district: {district_name}]")

            self.stdout.write(self.style.WARNING("DRY RUN complete. Use --apply to actually write the changes."))

        # Print any errors that happened while preparing changes
        if errors:
            self.stdout.write(self.style.ERROR("Some errors occurred while preparing updates:"))
            for who, err in errors:
                self.stdout.write(self.style.ERROR(f"  {who}: {err}"))

        self.stdout.write(self.style.SUCCESS("Finished."))
