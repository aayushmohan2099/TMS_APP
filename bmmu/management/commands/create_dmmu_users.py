# create_dmmu_users.py
from pathlib import Path
import re
import sys
import pandas as pd

from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model

User = get_user_model()

ID_SPLIT_RE = re.compile(r'[,\n;]+')

def normalize(s):
    if s is None:
        return ""
    return str(s).strip()

class Command(BaseCommand):
    help = "Create DMMU/DC users from Excel. Headers expected: 'District Name' and 'IDs'."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to Excel file (.xls/.xlsx)")
        parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
        parser.add_argument("--commit", action="store_true", help="Actually create/update users")
        parser.add_argument("--force", action="store_true", help="If user exists, reset password to generated one (only with --commit)")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {path}"))
            sys.exit(1)

        try:
            df = pd.read_excel(path, engine="openpyxl", dtype=str)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed reading Excel: {e}"))
            return

        if df.empty:
            self.stdout.write(self.style.WARNING("Excel is empty"))
            return

        # find columns
        district_col = None
        ids_col = None
        for c in df.columns:
            lc = c.strip().lower()
            if "district" in lc and district_col is None:
                district_col = c
            if ("id" in lc or "ids" in lc) and ids_col is None:
                ids_col = c

        if not district_col or not ids_col:
            self.stderr.write(self.style.ERROR("Could not find required columns. Ensure file contains 'District' and 'IDs' columns."))
            self.stderr.write(self.style.ERROR(f"Found columns: {list(df.columns)}"))
            return

        rows = []
        for _, r in df.iterrows():
            district_name = normalize(r.get(district_col))
            ids_val = normalize(r.get(ids_col))
            if not district_name or not ids_val:
                continue
            ids = [s.strip() for s in ID_SPLIT_RE.split(ids_val) if s.strip()]
            if len(ids) == 1 and " " in ids[0]:
                ids = [s.strip() for s in ids[0].split() if s.strip()]
            for uid in ids:
                rows.append((district_name, uid))

        if not rows:
            self.stdout.write(self.style.WARNING("No valid rows to process."))
            return

        self.stdout.write(f"Found {len(rows)} user entries.")

        if options["dry_run"] and not options["commit"]:
            self.stdout.write(self.style.NOTICE("DRY RUN — no DB changes. Use --commit to apply."))
            for district_name, uid in rows[:30]:
                uname = uid
                if 'DMM' in uid.upper():
                    pwd = f"{district_name}@dmm25"
                elif 'DC' in uid.upper():
                    pwd = f"{district_name}@dc25"
                else:
                    # default fallback if token doesn't contain prefix
                    pwd = f"{district_name}@dmm25"
                self.stdout.write(f"Would create user: username='{uname}', password='{pwd}', role='dmmu'")
            if len(rows) > 30:
                self.stdout.write(f"... and {len(rows)-30} more.")
            return

        created = 0
        updated = 0
        skipped = 0
        with transaction.atomic():
            for district_name, uid in rows:
                username = uid.strip()
                if not username:
                    skipped += 1
                    continue
                uupper = username.upper()
                if 'DC' in uupper:
                    password = f"{district_name}@dc25"
                elif 'DMM' in uupper:
                    password = f"{district_name}@dmm25"
                else:
                    # fallback default: treat as DMM
                    password = f"{district_name}@dmm25"

                try:
                    user = User.objects.filter(username=username).first()
                    if user:
                        if options["force"]:
                            user.set_password(password)
                            user.role = 'dmmu'
                            user.save()
                            updated += 1
                        else:
                            skipped += 1
                        continue
                    # create new user
                    user = User.objects.create_user(username=username, password=password)
                    user.role = 'dmmu'
                    user.save()
                    created += 1
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Failed creating user '{username}': {e}"))

        self.stdout.write(self.style.SUCCESS(f"Done. Created: {created}, Updated(password reset): {updated}, Skipped(existing): {skipped}"))
