# training_mgmnt/bmmu/management/commands/assign_bmmu_blocks.py
import re
import unicodedata
from difflib import get_close_matches

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db.models import Q

from bmmu.models import Block, BmmuBlockAssignment, District

User = get_user_model()

# Normalizer: lower-case, remove diacritics, remove non-alphanumerics
def normalize_text(s: str) -> str:
    if not s:
        return ""
    # normalize unicode -> remove accents
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # replace common punctuation with space, then remove non-alnum
    s = s.replace("-", " ").replace("(", " ").replace(")", " ").replace("/", " ").replace(",", " ")
    s = re.sub(r"[^0-9a-zA-Z\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

# compact form (remove spaces) helpful for tokens like "AalampurJafarabad"
def compact_text(s: str) -> str:
    return re.sub(r"\s+", "", normalize_text(s))

class Command(BaseCommand):
    help = "Robustly auto-assign BMMU users to Blocks based on username (improved fuzzy matching)."

    def add_arguments(self, parser):
        parser.add_argument('--fuzzy-cutoff', type=float, default=0.75, help="Fuzzy match cutoff (0-1), default 0.75")
        parser.add_argument('--dry-run', action='store_true', help="Don't create assignments; just print matches")

    def handle(self, *args, **options):
        fuzzy_cutoff = float(options.get('fuzzy_cutoff') or 0.75)
        dry_run = options.get('dry_run')

        users = User.objects.filter(role__iexact='bmmu')
        created_count = 0
        skipped = 0

        # Build global block name maps (for fallback)
        all_blocks = list(Block.objects.select_related('district').all())
        norm_map = {}
        compact_map = {}
        for b in all_blocks:
            n = normalize_text(b.block_name_en or "")
            c = compact_text(b.block_name_en or "")
            norm_map.setdefault(n, []).append(b)
            compact_map.setdefault(c, []).append(b)

        # Build district normalization map
        district_names = [d.district_name_en for d in District.objects.all() if d.district_name_en]
        district_norms = {normalize_text(name): name for name in district_names}

        def split_block_and_district(parts):
            """
            Given username tokens after 'BMM', return (block_token, district_name).
            """
            # Try longest suffix that matches a district
            for i in range(1, len(parts) + 1):
                suffix = " ".join(parts[-i:])
                if normalize_text(suffix) in district_norms:
                    block = " ".join(parts[:-i]) if parts[:-i] else ""
                    return block, district_norms[normalize_text(suffix)]
            # fallback: assume last token is district
            return "_".join(parts[:-1]), parts[-1] if parts else ("", "")

        for u in users:
            uname = u.username or ""
            parts = uname.split("_")
            if len(parts) < 2:
                self.stdout.write(self.style.WARNING(f"Skipped {uname}: username too short / unexpected format"))
                skipped += 1
                continue

            # strip leading role token if it's 'BMM' or 'BMMU'
            idx = 0
            if parts[0].lower().startswith('bmm'):
                idx = 1
            core_parts = parts[idx:]

            block_token_raw, district_token_raw = split_block_and_district(core_parts)
            block_token_n = normalize_text(block_token_raw)
            block_token_c = compact_text(block_token_raw)
            district_token_n = normalize_text(district_token_raw)

            matched_block = None
            reason = None

            # 1) Try exact/normalized/compact match within district
            if district_token_raw:
                qs = Block.objects.filter(district__district_name_en__iexact=district_token_raw)
                if not qs.exists():
                    dmatch = District.objects.filter(district_name_en__icontains=district_token_raw).first()
                    if not dmatch:
                        dmatch = District.objects.filter(
                            district_name_en__iexact=district_token_n
                        ).first()
                    if dmatch:
                        qs = Block.objects.filter(district=dmatch)

                if qs.exists():
                    b_exact = qs.filter(block_name_en__iexact=block_token_raw).first()
                    if b_exact:
                        matched_block = b_exact
                        reason = f"exact block match within district ({district_token_raw})"
                    else:
                        for b in qs:
                            if normalize_text(b.block_name_en) == block_token_n:
                                matched_block = b
                                reason = "normalized exact match within district"
                                break
                        if not matched_block:
                            for b in qs:
                                if compact_text(b.block_name_en) == block_token_c:
                                    matched_block = b
                                    reason = "compact match within district"
                                    break

            # 2) Try global normalized match
            if not matched_block:
                candidates = norm_map.get(block_token_n) or compact_map.get(block_token_c)
                if candidates:
                    matched_block = candidates[0]
                    reason = "global normalized exact match"

            # 3) Fuzzy match within district
            if not matched_block and district_token_raw:
                try:
                    district_obj = District.objects.filter(
                        Q(district_name_en__iexact=district_token_raw) |
                        Q(district_name_en__icontains=district_token_raw) |
                        Q(district_name_en__iexact=district_token_n)
                    ).first()
                except Exception:
                    district_obj = None

                block_candidates = list(Block.objects.filter(district=district_obj)) if district_obj else []
                if not block_candidates:
                    block_candidates = all_blocks

                names = [normalize_text(b.block_name_en or "") for b in block_candidates]
                close = get_close_matches(block_token_n, names, n=3, cutoff=fuzzy_cutoff) if block_token_n else []
                if not close and block_token_c:
                    close = get_close_matches(block_token_c, names, n=3, cutoff=fuzzy_cutoff)

                if close:
                    best_name = close[0]
                    for b in block_candidates:
                        if normalize_text(b.block_name_en or "") == best_name:
                            matched_block = b
                            reason = f"fuzzy match within district (cutoff={fuzzy_cutoff}) -> '{best_name}'"
                            break

            # 4) Global fuzzy match
            if not matched_block:
                names_all = [normalize_text(b.block_name_en or "") for b in all_blocks]
                close = get_close_matches(block_token_n or block_token_c, names_all, n=3, cutoff=fuzzy_cutoff)
                if close:
                    best_name = close[0]
                    for b in all_blocks:
                        if normalize_text(b.block_name_en or "") == best_name:
                            matched_block = b
                            reason = f"global fuzzy match (cutoff={fuzzy_cutoff}) -> '{best_name}'"
                            break

            # Final handling
            if matched_block:
                if dry_run:
                    self.stdout.write(self.style.SUCCESS(
                        f"[DRY] Would assign {uname} -> {matched_block.block_name_en}  (reason: {reason})"
                    ))
                else:
                    assignment, created = BmmuBlockAssignment.objects.get_or_create(user=u, block=matched_block)
                    if created:
                        created_count += 1
                        self.stdout.write(self.style.SUCCESS(
                            f"Assigned {uname} -> {matched_block.block_name_en}  (reason: {reason})"
                        ))
                    else:
                        self.stdout.write(self.style.NOTICE(
                            f"Already assigned {uname} -> {matched_block.block_name_en}  (reason: {reason})"
                        ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"No block found for {uname} (parsed block token='{block_token_raw}', normalized='{block_token_n}', district_token='{district_token_raw}')"
                ))
                skipped += 1

        self.stdout.write(self.style.SUCCESS(f"Done. {created_count} new assignments created. {skipped} users skipped."))
