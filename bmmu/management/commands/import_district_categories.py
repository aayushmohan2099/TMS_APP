# import_district_categories.py
import sys
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from bmmu.models import District, DistrictCategory

def normalize(s):
    if s is None:
        return ""
    return str(s).strip()

class Command(BaseCommand):
    help = "Import district categories from Excel. Headers: 'District Name' and 'District Category' (comma-separated categories allowed)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to Excel file (.xls/.xlsx)")
        parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
        parser.add_argument("--commit", action="store_true", help="Write to DB (if not provided, dry-run)")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            self.stderr.write(f"File not found: {path}")
            sys.exit(1)

        df = pd.read_excel(path, engine="openpyxl", dtype=str)
        cols = [c.strip().lower() for c in df.columns]
        # find columns
        district_col = None
        cat_col = None
        for c in df.columns:
            lc = c.strip().lower()
            if "district" in lc and district_col is None:
                district_col = c
            elif "category" in lc and cat_col is None:
                cat_col = c
        if not district_col or not cat_col:
            self.stderr.write("Excel must have 'District Name' and 'District Category' columns.")
            sys.exit(1)

        created = 0
        skipped = 0
        pending_creates = []

        for idx, row in df.iterrows():
            dname = normalize(row.get(district_col))
            cats_raw = row.get(cat_col)
            if not dname or (pd.isna(dname) and (not cats_raw or pd.isna(cats_raw))):
                # skip empty
                continue
            # split categories by comma
            if pd.isna(cats_raw) or str(cats_raw).strip() == "":
                cats = []
            else:
                cats = [normalize(c) for c in str(cats_raw).split(",") if normalize(c) != ""]

            # find district by exact name (case-insensitive)
            try:
                district = District.objects.filter(district_name_en__iexact=dname).first()
            except Exception:
                district = None

            if not district:
                # try partial match (starts/contains)
                district = District.objects.filter(district_name_en__icontains=dname).first()

            if not district:
                self.stderr.write(f"[WARN] District not found for '{dname}' — skipping (you may run with cleaned names)")
                skipped += 1
                continue

            for cat in cats:
                # avoid duplicates
                existing = DistrictCategory.objects.filter(district=district, category_name__iexact=cat).exists()
                if existing:
                    continue
                pending_creates.append(DistrictCategory(district=district, category_name=cat))

        self.stdout.write(f"Prepared {len(pending_creates)} district category rows to create. Skipped {skipped} district rows due to missing district.")
        if options["dry_run"] and not options["commit"]:
            self.stdout.write("Dry-run mode. No changes made. Use --commit to write to DB.")
            return

        # bulk create in chunks
        chunk = 1000
        created = 0
        with transaction.atomic():
            for i in range(0, len(pending_creates), chunk):
                slice_objs = pending_creates[i:i+chunk]
                try:
                    DistrictCategory.objects.bulk_create(slice_objs, ignore_conflicts=True)
                    created += len(slice_objs)
                except IntegrityError as e:
                    # fallback to per-row create (safe)
                    for obj in slice_objs:
                        try:
                            obj.save()
                            created += 1
                        except IntegrityError:
                            continue

        self.stdout.write(self.style.SUCCESS(f"Inserted approx {created} DistrictCategory rows."))
