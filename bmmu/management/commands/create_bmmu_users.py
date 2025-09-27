# create_bmmu_users.py
from pathlib import Path
import re
import csv
import sys
import pandas as pd
from collections import OrderedDict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model

User = get_user_model()

# Split IDs on comma / semicolon / newline
ID_SPLIT_RE = re.compile(r'[,\n;]+')

def is_blank_val(val):
    """
    Return True if value should be considered blank/missing.
    Handles pandas NaN, Python None, empty string, and 'nan' string.
    """
    if pd.isna(val):
        return True
    s = str(val).strip()
    if s == "":
        return True
    if s.lower() == "nan":
        return True
    return False

def normalize(s):
    """Return cleaned string or empty string for blanks."""
    if is_blank_val(s):
        return ""
    return str(s).strip()

def make_username(id_token, district_name):
    """
    Compose username as "<ID>_<District>".
    District spaces -> underscores, strip surrounding whitespace.
    """
    id_val = normalize(id_token)
    district = normalize(district_name).replace(" ", "_")
    return f"{id_val}_{district}" if district else id_val

class Command(BaseCommand):
    help = "Create BMMU users from Excel file. Headers expected: 'District Name', 'Block Name' and 'IDs'. Username pattern: <ID>_<District>"

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to Excel file (.xls/.xlsx)")
        parser.add_argument("--dry-run", action="store_true", help="Don't write to DB (default)")
        parser.add_argument("--commit", action="store_true", help="Actually create/update users")
        parser.add_argument("--force", action="store_true", help="If user exists, reset password to the generated password (only with --commit)")
        parser.add_argument("--make-staff", action="store_true", help="Set is_staff=True on created users")
        parser.add_argument("--make-superuser", action="store_true", help="Set is_superuser=True on created users (implies --make-staff)")
        parser.add_argument("--report", help="Path to CSV report file (default: ./bmmu_users_report.csv)", default="bmmu_users_report.csv")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {path}"))
            sys.exit(1)

        try:
            # read file; dtype=str sometimes yields 'nan' strings for empty cells,
            # but our is_blank_val handles both pandas NaN and 'nan' string.
            df = pd.read_excel(path, engine="openpyxl", dtype=object)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed reading Excel: {e}"))
            return

        if df.empty:
            self.stdout.write(self.style.WARNING("Excel is empty"))
            return

        # identify columns heuristically (case-insensitive)
        district_col = None
        block_col = None
        ids_col = None
        for c in df.columns:
            lc = str(c).strip().lower()
            if "district" in lc and district_col is None:
                district_col = c
            if "block" in lc and block_col is None:
                block_col = c
            if ("id" in lc or "ids" in lc) and ids_col is None:
                ids_col = c

        if not ids_col or not block_col:
            self.stderr.write(self.style.ERROR("Could not find required columns. Ensure file contains 'IDs' and 'Block Name' (and optionally 'District Name')."))
            self.stderr.write(self.style.ERROR(f"Found columns: {list(df.columns)}"))
            return

        # Parse rows. Carry-forward district when blank (but only when truly blank).
        mapping = OrderedDict()  # username -> (block_name, original_row)
        blank_rows = []
        total_rows = 0
        raw_entries = []  # (row_num, district, block, id_token, username)

        last_district = None
        for idx, r in df.iterrows():
            total_rows += 1
            row_num = idx + 2  # excel-like row num (header + 1)

            raw_district = r.get(district_col) if district_col else None
            district_val = normalize(raw_district)

            # Only update last_district if district_val is non-blank
            if district_val:
                last_district = district_val

            # block and ids normalized
            block_val = normalize(r.get(block_col))
            ids_val = r.get(ids_col)

            if is_blank_val(ids_val):
                blank_rows.append((row_num, last_district or "", block_val))
                continue

            # split IDs tokens
            ids = [s.strip() for s in ID_SPLIT_RE.split(str(ids_val)) if s and s.strip()]
            # defensive additional split when only one token contains spaces
            if len(ids) == 1 and " " in ids[0]:
                ids = [s.strip() for s in ids[0].split() if s.strip()]

            for uid in ids:
                username = make_username(uid, last_district or "")
                if not username.strip():
                    blank_rows.append((row_num, last_district or "", block_val))
                    continue
                raw_entries.append((row_num, last_district or "", block_val, uid, username))
                if username not in mapping:
                    mapping[username] = (block_val, row_num)

        if not mapping:
            self.stdout.write(self.style.WARNING("No valid user IDs found in file."))
            if blank_rows:
                self.stdout.write(self.style.WARNING(f"{len(blank_rows)} rows had blank IDs or produced blank usernames. Sample: {blank_rows[:5]}"))
            return

        unique_usernames = list(mapping.keys())
        self.stdout.write(f"Parsed {total_rows} rows -> {len(raw_entries)} ID tokens -> {len(unique_usernames)} unique usernames (username pattern: <ID>_<District>).")
        if blank_rows:
            self.stdout.write(self.style.WARNING(f"{len(blank_rows)} rows had blank/missing IDs or could not build username; they were ignored."))

        if options["dry_run"] and not options["commit"]:
            self.stdout.write(self.style.NOTICE("DRY RUN — no DB changes. Use --commit to apply."))
            sample = unique_usernames[:40]
            for uname in sample:
                block_name, rownum = mapping.get(uname, ("", None))
                pwd = f"{block_name}@admin25"
                self.stdout.write(f"Would create user: username='{uname}', password='{pwd}', role='bmmu' (from row {rownum})")
            if len(unique_usernames) > len(sample):
                self.stdout.write(f"... and {len(unique_usernames)-len(sample)} more.")
            return

        # apply changes
        if options["make_superuser"]:
            options["make_staff"] = True

        report_rows = []
        created = 0
        updated = 0
        skipped = 0
        errors = 0

        with transaction.atomic():
            for uname in unique_usernames:
                block_name, rownum = mapping.get(uname, ("", None))
                password = f"{block_name}@admin25"
                try:
                    user = User.objects.filter(username=uname).first()
                    if user:
                        if options["force"]:
                            user.set_password(password)
                            user.role = 'bmmu'
                            if options["make_staff"]:
                                user.is_staff = True
                            if options["make_superuser"]:
                                user.is_superuser = True
                            user.save()
                            updated += 1
                            report_rows.append({"username": uname, "block": block_name, "status": "updated", "reason": "password reset (force)", "row": rownum})
                        else:
                            skipped += 1
                            report_rows.append({"username": uname, "block": block_name, "status": "skipped", "reason": "user exists", "row": rownum})
                        continue

                    # create new user
                    user = User.objects.create_user(username=uname, password=password)
                    user.role = 'bmmu'
                    if options["make_staff"]:
                        user.is_staff = True
                    if options["make_superuser"]:
                        user.is_superuser = True
                    user.save()
                    created += 1
                    report_rows.append({"username": uname, "block": block_name, "status": "created", "reason": "", "row": rownum})
                except Exception as e:
                    errors += 1
                    report_rows.append({"username": uname, "block": block_name, "status": "error", "reason": str(e), "row": rownum})
                    self.stderr.write(self.style.ERROR(f"Failed for username '{uname}': {e}"))

        # write CSV report
        report_path = Path(options["report"])
        try:
            with open(report_path, "w", newline="", encoding="utf-8") as fh:
                fieldnames = ["username", "block", "status", "reason", "row"]
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                for r in report_rows:
                    writer.writerow(r)
            self.stdout.write(self.style.SUCCESS(f"Wrote CSV report to: {report_path.resolve()}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed writing report CSV: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Done. Created: {created}, Updated(password reset): {updated}, Skipped(existing): {skipped}, Errors: {errors}"))
