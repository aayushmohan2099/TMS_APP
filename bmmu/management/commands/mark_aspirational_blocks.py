# mark_aspirational_blocks.py
import argparse
import difflib
import sys
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction

from bmmu.models import Block  # adjust app name if needed

# expected headers in the excel:
# "Block Name" and "Which Blocks are Aspirational?"

def normalize(s):
    if s is None:
        return ""
    return str(s).strip().lower()

class Command(BaseCommand):
    help = "Mark aspirational blocks from Excel. Excel must have headers 'Block Name' and 'Which Blocks are Aspirational?'"

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to Excel file (.xls/.xlsx)")
        parser.add_argument("--dry-run", action="store_true", help="Don't write to DB, only show what would change")
        parser.add_argument("--commit", action="store_true", help="Actually save changes (default is dry-run unless --commit provided)")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            self.stderr.write(f"File not found: {path}")
            sys.exit(1)

        df = pd.read_excel(path, engine="openpyxl", dtype=str)  # read all as strings to avoid dtype issues
        # Normalize header lookups (strip, case-insensitive)
        headers = {c.strip().lower(): c for c in df.columns}
        if "block name" not in headers:
            self.stderr.write("Excel does not contain a 'Block Name' column. Found columns: " + ", ".join(df.columns))
            sys.exit(1)
        aspir_col_key = None
        for k in headers:
            if "aspir" in k:  # matches 'which blocks are aspirational?' or similar
                aspir_col_key = headers[k]
                break
        if aspir_col_key is None:
            # fallback: second column if exists
            cols = list(df.columns)
            if len(cols) >= 2:
                aspir_col_key = cols[1]
            else:
                self.stderr.write("Could not find aspirational marker column. Please include 'Which Blocks are Aspirational?' or provide a second column.")
                sys.exit(1)

        block_name_col = headers["block name"]

        # load existing blocks into lookup: name_lower -> queryset
        blocks = list(Block.objects.all().values("block_id", "block_name_en", "block_code"))
        name_map = {}
        for b in blocks:
            key = normalize(b["block_name_en"]) or normalize(b["block_code"]) or None
            if key:
                name_map.setdefault(key, []).append(b)

        changes = []
        unmatched = []
        suggestions = {}

        for i, row in df.iterrows():
            raw_name = row.get(block_name_col)
            marker = row.get(aspir_col_key)
            if pd.isna(raw_name) or str(raw_name).strip() == "":
                continue
            is_asp = False
            if pd.notna(marker) and str(marker).strip() != "":
                # treat any non-empty marker as aspirational (you can add exact match logic if needed)
                is_asp = True
            key = normalize(raw_name)
            matched = name_map.get(key)
            if matched:
                # mark all that match exact name (rarely multiple)
                for m in matched:
                    changes.append((m["block_id"], m["block_name_en"], is_asp))
            else:
                # try fuzzy matching to suggest
                candidates = list(name_map.keys())
                close = difflib.get_close_matches(key, candidates, n=3, cutoff=0.75)
                suggestions[raw_name] = close
                unmatched.append((raw_name, is_asp))

        # summary
        self.stdout.write(f"Rows parsed: {len(df)}")
        self.stdout.write(f"Exact matches to update: {len(changes)}")
        self.stdout.write(f"Unmatched rows: {len(unmatched)}")

        if unmatched:
            self.stdout.write("\nUnmatched sample (first 20) and suggestions:")
            for u, is_asp in unmatched[:20]:
                s = suggestions.get(u) or []
                self.stdout.write(f"  '{u}' -> aspirational: {is_asp} | suggestions: {s}")

        # apply changes
        if options["dry_run"] and not options["commit"]:
            self.stdout.write("\nDry run mode. No DB changes made. Use --commit to write changes.")
            return

        # Commit updates in a transaction
        updated = 0
        with transaction.atomic():
            for block_id, block_name, is_asp in changes:
                updated_rows = Block.objects.filter(block_id=block_id).update(is_aspirational=is_asp)
                updated += updated_rows

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} block(s) is_aspirational flag."))
