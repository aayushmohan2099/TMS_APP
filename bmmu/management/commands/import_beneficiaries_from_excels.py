import os
import re
import math
from pathlib import Path
from typing import Optional, Tuple

from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError
from django.utils.dateparse import parse_date
from django.conf import settings

# pandas is used to read Excel files reliably.
# If you don't have pandas/openpyxl installed: `pip install pandas openpyxl`
try:
    import pandas as pd
except Exception as e:
    raise ImportError("This command requires pandas and openpyxl. Install them: pip install pandas openpyxl") from e

from bmmu.models import Beneficiary, District, Block

# Mapping from Excel header -> Beneficiary model field
HEADER_MAP = {
    "State": "state",
    "District": "district",  # handled specially (FK)
    "Block": "block",        # handled specially (FK)
    "Gram Panchayat": "gram_panchayat",
    "Village": "village",
    "SHG Code": "shg_code",
    "SHG Name": "shg_name",
    "Date of Formation": "date_of_formation",
    "Member Code": "member_code",
    "Member Name": "member_name",
    "Date of Birth": "date_of_birth",
    "Date of Joining in SHG": "date_of_joining_shg",
    "Designation in SHG": "designation_in_shg_vo_clf",
    "Social Category": "social_category",
    "PVTG Category": "pvtg_category",
    "Religion": "religion",
    "Gender": "gender",
    "Education": "education",
    "Marital Status": "marital_status",
    "Insurance": "insurance_status",
    "Disability": "disability",
    "Disability Type": "disability_type",
    "Is head of Family": "is_head_of_family",
    "Father/Mother/Spouse Name": "parent_or_spouse_name",
    "Relation": "relation",
    "Account Number (Default)": "account_number",
    "IFSC": "ifsc",
    "Branch Name": "branch_name",
    "Bank Name": "bank_name",
    "Account Opening Date": "account_opening_date",
    "Account Type": "account_type",
    "Mobile No.": "mobile_no",
    "Aadhaar Number": "aadhaar_no",
    "Aadhaar KYC": "aadhar_kyc",
    "eKYC": "ekyc_status",
    "Cadres Role": "cadres_role",
    "Primary Livelihoods": "primary_livelihood",
    "Secondary Livelihoods": "secondary_livelihood",
    "Tertiary Livelihoods": "tertiary_livelihood",
    "NREGA Job Card Number": "nrega_no",
    "PMAY-G ID": "pmay_id",
    "SECC TIN": "secc_tin",
    "NRLM MIS ID": "nrlm_id",
    "State MIS ID": "state_id",
    "eBK ID": "ebk_id",
    "eBK Name": "ebk_name",
    "eBK Mobile No.": "ebk_mobile_no",
    "Approval Status": "approval_status",
    "First Time Approval Date": "date_of_approval",
    "Status (Active/Inactive)": "benef_status",
    "Inactive/Reject Date": "inactive_date",
    "Inactive/Reject Reason": "inactive_reason",
    "Migrated/LokOS": "member_type",
}

# helper to normalize district/block names for tolerant matching
def _normalize_name(s: Optional[str]) -> str:
    if s is None:
        return ""
    s = str(s).strip().upper()
    # remove punctuation and multiple spaces
    s = re.sub(r'\s+', ' ', s)
    # remove non-alphanumeric for robust comparison
    return re.sub(r'[^0-9A-Z]', '', s)

def _find_district_by_name(name: str) -> Optional[District]:
    if not name or not name.strip():
        return None
    # try exact case-insensitive first
    q = District.objects.filter(district_name_en__iexact=name.strip())
    if q.exists():
        return q.first()
    # fallback normalized lookup
    norm = _normalize_name(name)
    # build a normalized map lookup (cache could be added; but dataset small)
    for d in District.objects.all():
        if _normalize_name(d.district_name_en) == norm:
            return d
    # substring fallback
    for d in District.objects.all():
        if norm in _normalize_name(d.district_name_en) or _normalize_name(d.district_name_en) in norm:
            return d
    return None

def _find_block_by_name_and_district(name: str, district: Optional[District]) -> Optional[Block]:
    if not name or not name.strip():
        return None
    if district:
        q = Block.objects.filter(block_name_en__iexact=name.strip(), district=district)
        if q.exists():
            return q.first()
        # fallback normalized
        norm = _normalize_name(name)
        for b in Block.objects.filter(district=district):
            if _normalize_name(b.block_name_en) == norm:
                return b
        for b in Block.objects.filter(district=district):
            if norm in _normalize_name(b.block_name_en) or _normalize_name(b.block_name_en) in norm:
                return b
    else:
        # no district given: match globally
        q = Block.objects.filter(block_name_en__iexact=name.strip())
        if q.exists():
            return q.first()
        norm = _normalize_name(name)
        for b in Block.objects.all():
            if _normalize_name(b.block_name_en) == norm:
                return b
        for b in Block.objects.all():
            if norm in _normalize_name(b.block_name_en) or _normalize_name(b.block_name_en) in norm:
                return b
    return None

def _to_date_safe(value):
    """
    Accept strings, datetimes, pandas Timestamp, numeric excel dates etc.
    Returns python date or None.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    # If pandas.Timestamp or datetime-like
    try:
        # parse_date handles YYYY-MM-DD etc; fallback to pandas
        if hasattr(value, "date"):
            return value.date()
        s = str(value).strip()
        if not s:
            return None
        # Try django parse_date first
        parsed = parse_date(s)
        if parsed:
            return parsed
        # fallback: pandas
        try:
            ts = pd.to_datetime(s, errors='coerce')
            if pd.isna(ts):
                return None
            return ts.date()
        except Exception:
            return None
    except Exception:
        return None

class Command(BaseCommand):
    help = "Import Beneficiary rows from multiple Excel files (headers must match the expected template)."

    def add_arguments(self, parser):
        parser.add_argument(
            "directory",
            help="Directory path containing Excel files (.xlsx/.xls) to import."
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write changes to DB. Without this flag runs as dry-run and only reports."
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="If True, update existing Beneficiary rows when member_code or aadhaar matches. Otherwise skip duplicates."
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional: limit number of rows processed per file (0 = no limit). Useful for testing."
        )
        parser.add_argument(
            "--skip-header-check",
            action="store_true",
            help="Skip strict check that Excel headers exactly match expected headers (useful for slightly different files)."
        )
        parser.add_argument(
            "--create-missing-loc",
            action="store_true",
            help="Attempt to create missing District/Block records when not found (may fail if your models require PK values). Use with caution."
        )

    def handle(self, *args, **options):
        directory = options["directory"]
        apply_changes = options["apply"]
        update_existing = options["update_existing"]
        limit = int(options["limit"]) or None
        skip_header_check = options["skip_header_check"]
        create_missing_loc = options["create_missing_loc"]

        p = Path(directory)
        if not p.exists() or not p.is_dir():
            self.stdout.write(self.style.ERROR(f"Directory not found: {directory}"))
            return

        excel_files = sorted([f for f in p.iterdir() if f.suffix.lower() in (".xlsx", ".xls")])
        if not excel_files:
            self.stdout.write(self.style.ERROR("No .xlsx/.xls files found in the directory."))
            return

        total_created = 0
        total_updated = 0
        total_skipped = 0
        total_errors = 0
        row_number = 0

        self.stdout.write(self.style.SUCCESS(f"Found {len(excel_files)} excel files. (Dry-run={not apply_changes})"))
        for file_path in excel_files:
            self.stdout.write(self.style.NOTICE(f"Processing file: {file_path.name}"))
            try:
                # read into pandas dataframe; preserve raw values
                df = pd.read_excel(file_path, dtype=object)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to read {file_path.name}: {e}"))
                total_errors += 1
                continue

            # Normalize column names: strip spaces
            df.columns = [str(c).strip() for c in df.columns]

            # Validate headers (optional)
            missing_headers = [h for h in HEADER_MAP.keys() if h not in df.columns]
            if missing_headers and not skip_header_check:
                self.stdout.write(self.style.ERROR(f"Missing expected headers in {file_path.name}: {missing_headers}"))
                total_errors += 1
                continue

            # Iterate rows
            processed = 0
            for idx, raw_row in df.iterrows():
                row_number += 1
                if limit and processed >= limit:
                    break
                processed += 1

                # build field dict
                beneficiary_data = {}
                district_name = None
                block_name = None

                for col_header, model_field in HEADER_MAP.items():
                    if col_header not in df.columns:
                        continue
                    raw_val = raw_row.get(col_header, None)
                    # strip strings
                    if isinstance(raw_val, str):
                        val = raw_val.strip()
                    else:
                        val = raw_val

                    if model_field == "district":
                        district_name = val
                    elif model_field == "block":
                        block_name = val
                    elif model_field in ("date_of_birth", "date_of_joining_shg", "date_of_formation", "account_opening_date", "date_of_approval", "inactive_date"):
                        beneficiary_data[model_field] = _to_date_safe(val)
                    else:
                        beneficiary_data[model_field] = (str(val).strip() if (val is not None and not (isinstance(val, float) and math.isnan(val))) else None)

                # Resolve district & block FKs
                district_obj = None
                block_obj = None
                if district_name:
                    district_obj = _find_district_by_name(district_name)
                    if not district_obj and create_missing_loc:
                        # Attempt to create (only if model allows). WARNING: District model in your code has district_id PK (BigInteger) so creating without PK may fail.
                        try:
                            district_obj, _ = District.objects.get_or_create(district_name_en=district_name.strip())
                            self.stdout.write(self.style.WARNING(f"Created District record for '{district_name}' (id={district_obj.pk})."))
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f"Could not create District '{district_name}': {e}"))
                            district_obj = None

                if block_name:
                    block_obj = _find_block_by_name_and_district(block_name, district_obj)
                    if not block_obj and create_missing_loc:
                        try:
                            # If district_obj exists, link to it
                            kwargs = {"block_name_en": block_name.strip()}
                            if district_obj:
                                kwargs["district"] = district_obj
                            block_obj, _ = Block.objects.get_or_create(**kwargs)
                            self.stdout.write(self.style.WARNING(f"Created Block record for '{block_name}' (id={block_obj.pk})."))
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f"Could not create Block '{block_name}': {e}"))
                            block_obj = None

                # attach to data dict
                if district_obj:
                    beneficiary_data["district"] = district_obj
                else:
                    beneficiary_data["district"] = None

                if block_obj:
                    beneficiary_data["block"] = block_obj
                else:
                    beneficiary_data["block"] = None

                # Duplicate checks: prefer member_code then aadhaar
                member_code = beneficiary_data.get("member_code") or None
                aadhaar = beneficiary_data.get("aadhaar_no") or None
                existing = None
                if member_code:
                    existing = Beneficiary.objects.filter(member_code=member_code).first()
                if not existing and aadhaar:
                    existing = Beneficiary.objects.filter(aadhaar_no=aadhaar).first()

                try:
                    if existing:
                        if update_existing:
                            # update allowed: only update fields that are provided (not None)
                            for k, v in beneficiary_data.items():
                                # skip PK
                                if k == "id":
                                    continue
                                # set if v is not None
                                if v is not None:
                                    setattr(existing, k, v)
                            if apply_changes:
                                existing.save()
                            total_updated += 1
                            self.stdout.write(f"Updated existing Beneficiary (member_code={existing.member_code or 'N/A'}, aadhaar={existing.aadhaar_no or 'N/A'})")
                        else:
                            total_skipped += 1
                            self.stdout.write(self.style.NOTICE(f"Skipped existing Beneficiary (member_code={existing.member_code or 'N/A'}). Use --update-existing to update."))
                        continue
                    else:
                        # Create new Beneficiary instance but do not save if dry-run
                        b = Beneficiary(**{k: v for k, v in beneficiary_data.items() if k not in ("district", "block")})
                        # assign FK objects explicitly
                        if beneficiary_data.get("district"):
                            b.district = beneficiary_data["district"]
                        if beneficiary_data.get("block"):
                            b.block = beneficiary_data["block"]

                        if apply_changes:
                            try:
                                with transaction.atomic():
                                    b.save()
                                total_created += 1
                                self.stdout.write(self.style.SUCCESS(f"Created Beneficiary: member_code={b.member_code or 'N/A'} aadhaar={b.aadhaar_no or 'N/A'}"))
                            except IntegrityError as ie:
                                total_errors += 1
                                self.stdout.write(self.style.ERROR(f"IntegrityError creating row (member_code={member_code}): {ie}"))
                            except Exception as e:
                                total_errors += 1
                                self.stdout.write(self.style.ERROR(f"Error creating Beneficiary (member_code={member_code}): {e}"))
                        else:
                            total_created += 1
                            self.stdout.write(f"[DRY RUN] Would create Beneficiary: member_code={member_code or 'N/A'} aadhaar={aadhaar or 'N/A'}")
                except Exception as e:
                    total_errors += 1
                    self.stdout.write(self.style.ERROR(f"Unhandled error for row {row_number}: {e}"))

            self.stdout.write(self.style.NOTICE(f"Finished file {file_path.name}: processed {processed} rows."))

        # Summary
        self.stdout.write(self.style.SUCCESS("Import summary:"))
        self.stdout.write(self.style.SUCCESS(f"  Created: {total_created}"))
        self.stdout.write(self.style.SUCCESS(f"  Updated: {total_updated}"))
        self.stdout.write(self.style.WARNING(f"  Skipped (existing, not updated): {total_skipped}"))
        if total_errors:
            self.stdout.write(self.style.ERROR(f"  Errors: {total_errors}"))
        else:
            self.stdout.write(self.style.SUCCESS("  Errors: 0"))

        if not apply_changes:
            self.stdout.write(self.style.WARNING("DRY RUN finished. Run with --apply to actually write records to the database."))

