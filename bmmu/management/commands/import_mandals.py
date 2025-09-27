# import_mandals.py
from pathlib import Path
from collections import OrderedDict

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction

from bmmu.models import Mandal, District  


def normalize(s):
    if s is None:
        return ""
    return str(s).strip()


class Command(BaseCommand):
    help = "Import Mandals and assign District.mandal from Excel. Expected headers: 'Mandal' and 'District Name'."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to Excel file (.xls/.xlsx)")
        parser.add_argument("--dry-run", action="store_true", help="Don't write to DB (default)")
        parser.add_argument("--commit", action="store_true", help="Actually write changes to DB")
        parser.add_argument("--chunk-size", type=int, default=1000, help="Chunk size for bulk DB operations")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {path}"))
            return

        # Read Excel as strings to avoid dtype surprises
        try:
            df = pd.read_excel(path, engine="openpyxl", dtype=str)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to read Excel file: {e}"))
            return

        if df.empty:
            self.stdout.write(self.style.WARNING("Excel appears empty. Nothing to import."))
            return

        # Find Mandal and District columns heuristically (case-insensitive substring match)
        mandal_col = None
        district_col = None
        for c in df.columns:
            lc = c.strip().lower()
            if "mandal" in lc and mandal_col is None:
                mandal_col = c
            if "district" in lc and district_col is None:
                district_col = c

        if not mandal_col or not district_col:
            self.stderr.write(self.style.ERROR(
                "Could not find required columns. Ensure Excel has columns containing 'Mandal' and 'District'. "
                f"Found columns: {list(df.columns)}"
            ))
            return

        # Build ordered pairs preserving input order; ignore empty rows
        pairs = []
        for _, row in df.iterrows():
            mandal_name = normalize(row.get(mandal_col))
            district_name = normalize(row.get(district_col))
            if mandal_name == "" or district_name == "":
                continue
            pairs.append((mandal_name, district_name))

        if not pairs:
            self.stdout.write(self.style.WARNING("No valid Mandal-District rows found in the file."))
            return

        # Unique mandal names preserving original order
        mandal_names = list(OrderedDict.fromkeys([m for m, _ in pairs]))

        self.stdout.write(f"Found {len(mandal_names)} unique mandal names and {len(pairs)} mapping rows.")

        # Load existing mandals (name -> Mandal) case-insensitive
        existing_mandals = {m.name.strip().lower(): m for m in Mandal.objects.all()}

        to_create = []
        for name in mandal_names:
            key = name.strip().lower()
            if key not in existing_mandals:
                to_create.append(Mandal(name=name))

        self.stdout.write(f"Mandals to create: {len(to_create)}")

        if options["dry_run"] and not options["commit"]:
            # Dry-run summary
            self.stdout.write(self.style.NOTICE("DRY-RUN mode (no DB changes). Use --commit to apply changes.\n"))
            if to_create:
                self.stdout.write("Sample Mandals to create (first 20):")
                for m in to_create[:20]:
                    self.stdout.write(f"  {m.name}")
            self.stdout.write("\nSample mapping pairs (first 20):")
            for mname, dname in pairs[:20]:
                self.stdout.write(f"  Mandal: '{mname}' -> District: '{dname}'")
            return

        # Create missing mandals and refresh existing_mandals map
        created_mandals_count = 0
        with transaction.atomic():
            if to_create:
                Mandal.objects.bulk_create(to_create, ignore_conflicts=True)
                created_mandals_count = len(to_create)
            # Refresh map
            existing_mandals = {m.name.strip().lower(): m for m in Mandal.objects.all()}

        self.stdout.write(self.style.SUCCESS(f"Created approx {created_mandals_count} Mandal(s)."))

        # Prepare a cache of districts: name_lower -> list(District)
        district_qs = District.objects.all()
        district_by_name = {}
        for d in district_qs:
            key = (d.district_name_en or "").strip().lower()
            if key:
                district_by_name.setdefault(key, []).append(d)

        # For each pair, find district and assign mandal
        district_updates = []
        not_found = []
        for mandal_name, district_name in pairs:
            mkey = mandal_name.strip().lower()
            dkey = district_name.strip().lower()
            mandal_obj = existing_mandals.get(mkey)
            if not mandal_obj:
                # this should not happen because we created missing mandals above, but guard anyway
                mandal_obj = Mandal.objects.filter(name__iexact=mandal_name).first()
                if not mandal_obj:
                    self.stderr.write(self.style.WARNING(f"Mandal not found after creation attempt: '{mandal_name}'"))
                    continue

            # Try exact match first
            candidates = district_by_name.get(dkey)
            district_obj = None
            if candidates:
                # If multiple candidates, pick the first; you can refine later if needed
                district_obj = candidates[0]
            else:
                # fallback to icontains
                district_obj = District.objects.filter(district_name_en__icontains=district_name).first()

            if not district_obj:
                not_found.append((mandal_name, district_name))
                continue

            # only update if different
            if district_obj.mandal_id != mandal_obj.id:
                district_obj.mandal = mandal_obj
                district_updates.append(district_obj)

        # Bulk update districts in chunks
        total_updates = 0
        chunk = max(1, options.get("chunk_size", 1000))
        if district_updates:
            with transaction.atomic():
                for i in range(0, len(district_updates), chunk):
                    slice_objs = district_updates[i:i + chunk]
                    District.objects.bulk_update(slice_objs, ['mandal'])
                    total_updates += len(slice_objs)

        self.stdout.write(self.style.SUCCESS(f"Assigned mandal to {total_updates} district(s)."))
        if not_found:
            self.stderr.write(self.style.WARNING(f"Could not find {len(not_found)} district(s) referenced in the file. Sample:"))
            for mname, dname in not_found[:20]:
                self.stderr.write(f"  Mandal '{mname}' -> District '{dname}' (district not found)")

        self.stdout.write(self.style.SUCCESS("import_mandals completed."))
