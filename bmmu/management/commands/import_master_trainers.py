# your_app/management/commands/import_master_trainers.py
"""
Import Master Trainers from CSV/XLSX and create User accounts (theme only, no TrainingPlan).

District matching improvements:
 - Uses a combination of exact-normalized, substring and multi-scorer fuzzy matching (token_sort_ratio, ratio, partial_ratio).
 - Configurable threshold: --district-threshold (default 75).
 - Auto-assign mode: --auto-assign-districts (default True). If enabled, assigns the best match when score >= threshold.
 - Optional mapping file: --district-mapping-file to explicitly map raw district strings to district_name_en or district_name_local.
 - Preview CSV includes suggested district and score so you can audit results.
"""

from __future__ import annotations

import csv
import secrets
import unicodedata
import re
import tempfile
from pathlib import Path
from typing import Optional, Dict, Tuple, Any

import pandas as pd
from rapidfuzz import process, fuzz

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from django.contrib.auth import get_user_model

from bmmu.models import MasterTrainer, District  # adjust import path if different

User = get_user_model()

CANONICAL_THEMES = [
    "Farm LH", "FNHW", "M&E", "MCLF", "MF&FI",
    "Non Farm", "NONFARM LH", "SISD", "SMCB", "TNCB", "Fishery"
]

# ---- Helpers ----
def normalize_text(s: Optional[str]) -> str:
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    s = s.replace("\ufeff", "")
    s = unicodedata.normalize("NFKC", s)
    s = s.strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r"[^\w\u0900-\u097F\s&]", "", s)
    return s.lower().strip()

def build_canonical_map():
    return { normalize_text(t): t for t in CANONICAL_THEMES }

def load_user_mappings(path: Path) -> Dict[str, str]:
    """Load user mapping CSV (raw -> map_to canonical)."""
    if not path.exists():
        raise FileNotFoundError(path)
    df = None
    for enc in ("utf-8-sig","utf-8","utf-16","latin1","cp1252"):
        for sep in ("\t",","):
            try:
                df_try = pd.read_csv(path, dtype=str, encoding=enc, sep=sep, low_memory=False)
                cols = [c.lower().strip() for c in df_try.columns]
                if "raw_theme" in cols and "map_to" in cols:
                    df = df_try
                    break
            except Exception:
                continue
        if df is not None:
            break
    if df is None:
        # try utf-16 tab-split as fallback
        df = pd.read_csv(path, dtype=str, encoding="utf-16", sep="\t", low_memory=False)
    lower_cols = {c.lower().strip(): c for c in df.columns}
    raw_col = lower_cols.get("raw_theme") or lower_cols.get("raw") or next((c for k,c in lower_cols.items() if "raw" in k and "theme" in k), None)
    map_col = lower_cols.get("map_to") or lower_cols.get("mapped") or lower_cols.get("map") or next((c for k,c in lower_cols.items() if "map" in k), None)
    if not raw_col or not map_col:
        raise ValueError("Mapping file must contain 'raw_theme' and 'map_to' columns")
    user_map = {}
    canonical_set = set(CANONICAL_THEMES)
    for _, r in df.iterrows():
        raw = str(r.get(raw_col,"")).strip()
        mapped = str(r.get(map_col,"")).strip()
        if not raw or not mapped:
            continue
        if mapped not in canonical_set:
            mapped_norm = normalize_text(mapped)
            found = None
            for c in CANONICAL_THEMES:
                if normalize_text(c) == mapped_norm:
                    found = c; break
            if not found:
                continue
            mapped = found
        user_map[normalize_text(raw)] = mapped
    return user_map

def load_district_mappings(path: Path) -> Dict[str, str]:
    """Load an explicit district mapping file: raw_district -> target_district_name (exact name in DB)."""
    # tolerant: try common encodings/separators, look for 'raw_district' and 'map_to' or 'target'
    if not path.exists():
        raise FileNotFoundError(path)
    df = None
    for enc in ("utf-8-sig","utf-8","utf-16","latin1","cp1252"):
        for sep in ("\t",","):
            try:
                df_try = pd.read_csv(path, dtype=str, encoding=enc, sep=sep, low_memory=False)
                cols = [c.lower().strip() for c in df_try.columns]
                if "raw_district" in cols and ("map_to" in cols or "target" in cols or "district" in cols):
                    df = df_try
                    break
            except Exception:
                continue
        if df is not None:
            break
    if df is None:
        df = pd.read_csv(path, dtype=str, encoding="utf-16", sep="\t", low_memory=False)
    lower_cols = {c.lower().strip(): c for c in df.columns}
    raw_col = lower_cols.get("raw_district") or lower_cols.get("raw") or next((c for k,c in lower_cols.items() if "raw" in k and "district" in k), None)
    map_col = lower_cols.get("map_to") or lower_cols.get("target") or lower_cols.get("district") or next((c for k,c in lower_cols.items() if "map" in k or "target" in k), None)
    if not raw_col or not map_col:
        raise ValueError("District mapping file must contain 'raw_district' and 'map_to'/'target'/'district' columns")
    out = {}
    for _, r in df.iterrows():
        raw = str(r.get(raw_col,"")).strip()
        mapped = str(r.get(map_col,"")).strip()
        if not raw or not mapped:
            continue
        out[normalize_text(raw)] = mapped
    return out

# Build district candidate lists for matching
def build_district_candidates() -> Tuple[Dict[str, District], list]:
    """
    Returns:
      - dict_norm_to_district: normalized_name -> District (first occurrence if duplicates)
      - choices_list: list of normalized names (for rapidfuzz)
    We include both district_name_local and district_name_en if present.
    """
    dict_norm = {}
    choices = []
    for d in District.objects.all():
        for name in (getattr(d, "district_name_local", None), getattr(d, "district_name_en", None)):
            if not name:
                continue
            n = normalize_text(name)
            if not n:
                continue
            # If multiple districts share same normalized name pick the first; that's rare
            dict_norm.setdefault(n, d)
            choices.append(n)
    # remove duplicates while preserving order
    seen = set(); uniq_choices = []
    for c in choices:
        if c not in seen:
            seen.add(c); uniq_choices.append(c)
    return dict_norm, uniq_choices

def find_best_district(raw: str, dict_norm: Dict[str, District], choices: list, threshold: int = 75) -> Tuple[Optional[District], float, Optional[str]]:
    """
    Try several strategies to find a matching District:
      1) exact normalized match
      2) substring containment (raw in candidate or candidate in raw)
      3) rapidfuzz with several scorers, pick best
    Returns (District or None, score 0-100, reason)
    """
    if not raw or str(raw).strip() == "":
        return None, 0.0, "empty"
    norm = normalize_text(raw)
    # 1) exact
    if norm in dict_norm:
        return dict_norm[norm], 100.0, "exact_norm"
    # 2) substring checks
    for cand_norm, d in dict_norm.items():
        if norm in cand_norm or cand_norm in norm:
            # high-confidence substring hit
            return d, 95.0, "substring"
    # 3) fuzzy: evaluate multiple scorers
    if not choices:
        return None, 0.0, "no_candidates"
    # get best by token_sort_ratio
    best_token = process.extractOne(norm, choices, scorer=fuzz.token_sort_ratio)
    best_ratio = process.extractOne(norm, choices, scorer=fuzz.ratio)
    best_partial = process.extractOne(norm, choices, scorer=fuzz.partial_ratio)
    # choose the best among them
    candidates = [best_token, best_ratio, best_partial]
    # each is (match, score, idx) or None
    best = max((c for c in candidates if c), key=lambda t: t[1])
    match_norm, score, _ = best
    # also allow lower threshold if partial match is strong
    reason = "fuzzy"
    return dict_norm.get(match_norm), float(score), f"{reason}"

# Username / password generation
def district_to_token(district: Optional[District]) -> str:
    if not district:
        return "unknown"
    district_name = getattr(district, "district_name_local", None) or getattr(district, "district_name_en", None) or str(getattr(district, "pk", "unknown"))
    dslug = slugify(district_name) or "unknown"
    return dslug.replace('-', '')

def generate_username(prefix: str='mt', district: Optional[District]=None, counter: int=1) -> str:
    dtoken = district_to_token(district)
    return f"{prefix}-{dtoken}-{int(counter):02d}"

def generate_password_from_counter(counter: int) -> str:
    return f"mt{int(counter):02d}@25"

# theme mapping reused
def map_theme_name_with_user(raw: Optional[str], canonical_map: dict, user_map: Dict[str,str], threshold: int = 85):
    if not raw or str(raw).strip() == "":
        return None, "empty"
    norm = normalize_text(raw)
    if user_map and norm in user_map:
        return user_map[norm], "user_map"
    if norm in canonical_map:
        return canonical_map[norm], "exact_norm"
    choices = list(canonical_map.keys())
    best = process.extractOne(norm, choices, scorer=fuzz.ratio)
    if best and best[1] >= threshold:
        return canonical_map[best[0]], f"fuzzy:{best[1]}"
    return None, "no_match"

# ---- Command ----
class Command(BaseCommand):
    help = "Import Master Trainers from CSV/XLSX and create User accounts with stronger district matching."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Path to XLSX or CSV file")
        parser.add_argument("--mapping-file", type=str, default=None, help="Optional theme mapping CSV (raw_theme -> map_to)")
        parser.add_argument("--district-mapping-file", type=str, default=None, help="Optional district mapping file (raw_district -> target district name)")
        parser.add_argument("--sheet", type=str, default=None, help="Sheet name for xlsx")
        parser.add_argument("--fuzzy-threshold", type=int, default=85, help="Threshold for theme fuzzy matching")
        parser.add_argument("--district-threshold", type=int, default=75, help="Threshold for district fuzzy matching (0-100)")
        parser.add_argument("--username-prefix", type=str, default="mt")
        parser.add_argument("--auto-assign-districts", action="store_true", default=True, help="If set, auto-assign best district when score >= district-threshold (default ON)")
        parser.add_argument("--dry-run", action="store_true", help="Preview mappings, do not create DB objects")

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        mapping_file = Path(opts["mapping_file"]) if opts.get("mapping_file") else None
        district_mapping_file = Path(opts["district_mapping_file"]) if opts.get("district_mapping_file") else None
        sheet = opts["sheet"]
        fuzz_thresh = opts["fuzzy_threshold"]
        district_thresh = opts["district_threshold"]
        username_prefix = opts["username_prefix"]
        auto_assign = bool(opts.get("auto_assign_districts", True))
        dry_run = opts["dry_run"]

        if not path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {path}"))
            return

        # load theme mapping if provided
        user_theme_map = {}
        if mapping_file:
            try:
                user_theme_map = load_user_mappings(mapping_file)
                self.stdout.write(self.style.NOTICE(f"Loaded {len(user_theme_map)} theme mappings from {mapping_file}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to load theme mapping file {mapping_file}: {e}"))
                return

        # load district mapping if provided
        user_district_map = {}
        if district_mapping_file:
            try:
                user_district_map = load_district_mappings(district_mapping_file)
                self.stdout.write(self.style.NOTICE(f"Loaded {len(user_district_map)} district mappings from {district_mapping_file}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to load district mapping file {district_mapping_file}: {e}"))
                return

        # load source file
        try:
            if path.suffix.lower() in (".xls", ".xlsx"):
                df = pd.read_excel(path, sheet_name=sheet, dtype=str, engine="openpyxl")
            else:
                df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to read file: {e}"))
            return

        df.columns = [str(c).strip() for c in df.columns]

        # autodetect columns
        name_col = next((c for c in df.columns if c.strip().upper() in ("NAME OF DRP","NAME","FULL_NAME","FULL NAME")), None)
        parent_col = next((c for c in df.columns if "father" in c.lower() or "spouce" in c.lower() or "spouse" in c.lower() or "parent" in c.lower()), None)
        designation_col = next((c for c in df.columns if "designation" in c.lower()), None)
        theme_col = next((c for c in df.columns if "theme" in c.lower()), None)
        district_col = next((c for c in df.columns if "district" in c.lower()), None)
        mobile_col = next((c for c in df.columns if "mobile" in c.lower() or "phone" in c.lower()), None)
        aadhaar_col = next((c for c in df.columns if "aadhaar" in c.lower() or "aadhar" in c.lower()), None)

        if not name_col:
            name_col = next((c for c in df.columns if c.strip().upper() == "NAME OF DRP"), None)
        if not theme_col:
            theme_col = next((c for c in df.columns if c.strip().upper() == "THEME"), None)
        if not district_col:
            district_col = next((c for c in df.columns if c.strip().upper() == "DISTRICT"), None)

        if not theme_col:
            self.stderr.write(self.style.ERROR("Could not find a 'theme' column. Aborting."))
            return

        canonical_map = build_canonical_map()

        # Prepare district candidates once
        dict_norm_to_obj, district_choices = build_district_candidates()

        district_counters: Dict[Any,int] = {}
        credentials = []
        unmapped_themes = []
        preview_rows = []
        district_suggestions = []

        self.stdout.write(self.style.NOTICE(f"Starting import (dry_run={dry_run})... auto_assign_districts={auto_assign} district_threshold={district_thresh}"))

        with transaction.atomic():
            for idx, row in df.iterrows():
                raw_theme = row.get(theme_col, "") if theme_col else ""
                canonical_theme, theme_reason = map_theme_name_with_user(raw_theme, canonical_map, user_theme_map, threshold=fuzz_thresh)
                if not canonical_theme:
                    unmapped_themes.append({"index": int(idx), "raw_theme": raw_theme, "normalized": normalize_text(raw_theme), "reason": theme_reason})
                    # skip row entirely if theme cannot be mapped (same behavior as before)
                    continue

                # resolve district:
                raw_district = row.get(district_col, "") if district_col else ""
                district_obj = None
                suggestion_name = ""
                suggestion_pk = ""
                suggestion_score = 0.0
                suggestion_reason = ""

                if raw_district and str(raw_district).strip():
                    norm_rd = normalize_text(raw_district)
                    # priority 1: user explicit district mapping file (if provided)
                    if user_district_map and norm_rd in user_district_map:
                        mapped_name = user_district_map[norm_rd]
                        # attempt to find district by mapped_name
                        district_obj = District.objects.filter(district_name_en__iexact=mapped_name).first() or District.objects.filter(district_name_local__iexact=mapped_name).first()
                        if district_obj:
                            suggestion_name = mapped_name
                            suggestion_pk = district_obj.pk
                            suggestion_score = 100.0
                            suggestion_reason = "user_map"
                        else:
                            # mapped name provided but no DB match — still record suggestion
                            suggestion_name = mapped_name
                            suggestion_reason = "user_map_no_db_match"

                    # priority 2: try exact normalized match against district candidates
                    if not district_obj:
                        d_obj, score, reason = find_best_district(raw_district, dict_norm_to_obj, district_choices, threshold=district_thresh)
                        if d_obj:
                            # if auto_assign allowed and score >= threshold, accept
                            suggestion_name = getattr(d_obj, "district_name_local", None) or getattr(d_obj, "district_name_en", None) or ""
                            suggestion_pk = d_obj.pk
                            suggestion_score = score
                            suggestion_reason = reason
                            if auto_assign and score >= district_thresh:
                                district_obj = d_obj
                        else:
                            suggestion_reason = reason

                else:
                    suggestion_reason = "no_raw_district"

                # record suggestion for preview
                preview_entry = {
                    "row_index": int(idx),
                    "raw_theme": raw_theme,
                    "mapped_theme": canonical_theme,
                    "mapping_reason": theme_reason,
                    "raw_district": raw_district,
                    "suggested_district_name": suggestion_name,
                    "suggested_district_pk": suggestion_pk,
                    "suggested_district_score": suggestion_score,
                    "suggested_district_reason": suggestion_reason,
                    "full_name": row.get(name_col) or "",
                    "mobile_no": row.get(mobile_col) or "",
                }

                # skip creating objects in dry-run; still collect preview_rows
                if dry_run:
                    preview_rows.append(preview_entry)
                    continue

                # increment district counter and create user/trainer
                dist_key = district_obj.pk if district_obj else "unknown"
                district_counters.setdefault(dist_key, 0)
                # find next unused counter for this district
                while True:
                    district_counters[dist_key] += 1
                    cnt = district_counters[dist_key]
                    username = generate_username(prefix=username_prefix, district=district_obj, counter=cnt)
                    if not User.objects.filter(username=username).exists():
                        break

                password = generate_password_from_counter(cnt)

                # create user
                try:
                    user = User.objects.create(username=username)
                except TypeError:
                    try:
                        user = User.objects.create_user(username=username)
                    except Exception:
                        user = User.objects.create(username=username)

                user.set_password(password)
                if hasattr(user, "role"):
                    try:
                        setattr(user, "role", "master_trainer")
                    except Exception:
                        pass
                if hasattr(user, "is_active"):
                    user.is_active = True
                user.save()

                mt = MasterTrainer.objects.create(
                    user=user,
                    full_name=preview_entry["full_name"],
                    parent_or_spouse_name=row.get(parent_col) or "" if parent_col else "",
                    designation="DRP",
                    mobile_no=preview_entry["mobile_no"] or None,
                    aadhaar_no=row.get(aadhaar_col) or None,
                    empanel_district=row.get(district_col) or None if district_col else None,
                    district=district_obj,
                    theme=canonical_theme,
                )

                preview_entry.update({
                    "created_username": username,
                    "created_password": password,
                    "master_trainer_id": mt.id
                })
                credentials.append({
                    "username": username,
                    "password": password,
                    "master_trainer_id": mt.id,
                    "full_name": mt.full_name,
                    "mobile_no": mt.mobile_no or "",
                    "theme": mt.theme or ""
                })
                preview_rows.append(preview_entry)

        # outputs
        temp_dir = Path(tempfile.gettempdir())
        cred_path = temp_dir / "master_trainers_credentials.csv"
        preview_path = temp_dir / "master_trainers_preview.csv"
        unmapped_path = temp_dir / "unmapped_themes.csv"

        if not dry_run and credentials:
            with open(cred_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(credentials[0].keys()))
                w.writeheader()
                for r in credentials:
                    w.writerow(r)
            self.stdout.write(self.style.SUCCESS(f"Created {len(credentials)} users/trainers. Credentials saved to {cred_path}"))

        # always write preview for audit
        if preview_rows:
            pd.DataFrame(preview_rows).to_csv(preview_path, index=False, encoding="utf-8-sig")
            self.stdout.write(self.style.SUCCESS(f"Preview CSV written to {preview_path}"))

        if unmapped_themes:
            pd.DataFrame(unmapped_themes).to_csv(unmapped_path, index=False, encoding="utf-8-sig")
            self.stdout.write(self.style.WARNING(f"{len(unmapped_themes)} theme rows could not be mapped. See {unmapped_path}"))

        # summary
        self.stdout.write(self.style.SUCCESS("Import finished (dry_run=%s). Preview saved at: %s" % (dry_run, preview_path)))
        if district_mapping_file:
            self.stdout.write(self.style.NOTICE(f"Used district mapping file: {district_mapping_file}"))
