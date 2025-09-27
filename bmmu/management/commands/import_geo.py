# main/management/commands/import_geo.py
import csv
import os
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.db import transaction
from bmmu.models import District, Block, Panchayat, Village

# Config
BATCH_SIZE = 1000
WORK_DIR = "."   # change to where CSVs are located, or pass as option later

DISTRICTS_CSV = os.path.join(WORK_DIR, "districts.csv")
BLOCKS_CSV = os.path.join(WORK_DIR, "districts_and_blocks.csv")
PANCHAYATS_CSV = os.path.join(WORK_DIR, "panchayats.csv")
VILLAGES_CSV = os.path.join(WORK_DIR, "villages.csv")

def to_int_safe(val):
    """Convert numeric-like strings (including Excel scientific notation) to int, return None if not possible."""
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    # if contains decimal or E notation, try Decimal then int
    try:
        if any(ch in s for ch in ('.', 'E', 'e')):
            d = Decimal(s)
            return int(d)
        return int(s)
    except (ValueError, InvalidOperation):
        # fallback: try float then int
        try:
            return int(float(s))
        except Exception:
            return None

def bool_from_str(s):
    if s is None:
        return False
    s = str(s).strip().lower()
    return s in ("true", "1", "t", "yes", "y")

class Command(BaseCommand):
    help = "Import districts, blocks, panchayats, villages from CSVs into models"

    def add_arguments(self, parser):
        parser.add_argument("--work-dir", "-d", help="Directory containing CSV files", default=".")
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)

    def handle(self, *args, **options):
        work_dir = options["work_dir"]
        batch_size = options["batch_size"]
        global DISTRICTS_CSV, BLOCKS_CSV, PANCHAYATS_CSV, VILLAGES_CSV
        DISTRICTS_CSV = os.path.join(work_dir, "districts.csv")
        BLOCKS_CSV = os.path.join(work_dir, "districts_and_blocks.csv")
        PANCHAYATS_CSV = os.path.join(work_dir, "panchayats.csv")
        VILLAGES_CSV = os.path.join(work_dir, "villages.csv")

        self.stdout.write(self.style.NOTICE("Starting geo import..."))
        self.import_districts(batch_size)
        self.import_blocks(batch_size)
        self.import_panchayats(batch_size)
        self.import_villages(batch_size)
        self.stdout.write(self.style.SUCCESS("Geo import completed."))

    def import_districts(self, batch_size):
        if not os.path.exists(DISTRICTS_CSV):
            self.stdout.write(self.style.WARNING(f"{DISTRICTS_CSV} not found — skipping districts import"))
            return
        self.stdout.write("Importing districts...")
        created = 0
        objs = []
        seen = 0
        with open(DISTRICTS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                seen += 1
                did = to_int_safe(row.get("district_id") or row.get("districtId") or row.get("districtId"))
                if not did:
                    self.stdout.write(self.style.WARNING(f"Skipping district row without parsable id: {row}"))
                    continue
                obj = District(
                    district_id=did,
                    district_code=row.get("district_code") or row.get("districtCode"),
                    state_id=to_int_safe(row.get("state_id") or row.get("stateId")),
                    district_name_en=row.get("district_name_en") or row.get("districtNameEnglish") or row.get("district_name_local"),
                    district_short_name_en=row.get("district_short_name_en") or row.get("districtShortNameEnglish"),
                    district_name_local=row.get("district_name_local") or row.get("districtNameLocal"),
                    lgd_code=(row.get("lgd_code") or row.get("lgdCode") or "").strip() or None,
                    language_id=row.get("language_id") or row.get("languageId"),
                )
                objs.append(obj)
                if len(objs) >= batch_size:
                    District.objects.bulk_create(objs, ignore_conflicts=True)
                    created += len(objs)
                    objs = []
                    self.stdout.write(f"  inserted {created} districts so far...")
            if objs:
                District.objects.bulk_create(objs, ignore_conflicts=True)
                created += len(objs)
        self.stdout.write(self.style.SUCCESS(f"Imported districts: approx {created} (scanned {seen})"))

    def import_blocks(self, batch_size):
        if not os.path.exists(BLOCKS_CSV):
            self.stdout.write(self.style.WARNING(f"{BLOCKS_CSV} not found — skipping blocks import"))
            return
        self.stdout.write("Importing blocks...")
        # load districts into dict for fast fk assignment
        district_map = {d.district_id: d for d in District.objects.all()}
        created = 0
        objs = []
        seen = 0
        with open(BLOCKS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                seen += 1
                block_id = to_int_safe(row.get("block_id") or row.get("blockId") or row.get("block_id"))
                if not block_id:
                    self.stdout.write(self.style.WARNING(f"Skipping block row without parsable block_id: {row}"))
                    continue
                district_id = to_int_safe(row.get("district_id") or row.get("districtId"))
                district_obj = district_map.get(district_id)
                if not district_obj:
                    # try to create a minimal district if missing? We will skip and log
                    self.stdout.write(self.style.WARNING(f"Block {block_id} references missing district {district_id} — skipping"))
                    continue
                obj = Block(
                    block_id=block_id,
                    block_code=row.get("block_code") or row.get("blockCode"),
                    block_name_en=row.get("block_name_en") or row.get("blockNameEnglish"),
                    block_name_local=row.get("block_name_local") or row.get("blockNameLocal"),
                    rural_urban_area=(row.get("rural_urban_area") or "").strip() or None,
                    lgd_code=(row.get("lgd_code") or row.get("lgdCode") or "").strip() or None,
                    language_id=row.get("language_id") or row.get("languageId"),
                    state_id=to_int_safe(row.get("state_id") or row.get("stateId")),
                    district=district_obj,
                    district_name_en=row.get("district_name_en") or None,
                )
                objs.append(obj)
                if len(objs) >= batch_size:
                    Block.objects.bulk_create(objs, ignore_conflicts=True)
                    created += len(objs)
                    objs = []
                    self.stdout.write(f"  inserted {created} blocks so far...")
            if objs:
                Block.objects.bulk_create(objs, ignore_conflicts=True)
                created += len(objs)
        self.stdout.write(self.style.SUCCESS(f"Imported blocks: approx {created} (scanned {seen})"))

    def import_panchayats(self, batch_size):
        if not os.path.exists(PANCHAYATS_CSV):
            self.stdout.write(self.style.WARNING(f"{PANCHAYATS_CSV} not found — skipping panchayats import"))
            return
        self.stdout.write("Importing panchayats...")
        # cache district and block lookups
        district_map = {d.district_id: d for d in District.objects.all()}
        block_map = {b.block_id: b for b in Block.objects.all()}

        created = 0
        objs = []
        seen = 0
        with open(PANCHAYATS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                seen += 1
                pid = to_int_safe(row.get("panchayat_id") or row.get("panchayatId"))
                if not pid:
                    self.stdout.write(self.style.WARNING(f"Skipping panchayat row without parsable panchayat_id: {row}"))
                    continue
                district_id = to_int_safe(row.get("district_id") or row.get("districtId"))
                block_id = to_int_safe(row.get("block_id") or row.get("blockId"))
                district_obj = district_map.get(district_id)
                block_obj = block_map.get(block_id)
                if not district_obj or not block_obj:
                    self.stdout.write(self.style.WARNING(f"Panchayat {pid} references missing district {district_id} or block {block_id} — skipping"))
                    continue
                obj = Panchayat(
                    panchayat_id=pid,
                    panchayat_code=row.get("panchayat_code") or row.get("panchayatCode"),
                    panchayat_name_en=row.get("panchayat_name_en") or row.get("panchayatNameEnglish"),
                    panchayat_name_local=row.get("panchayat_name_local") or row.get("panchayatNameLocal"),
                    rural_urban_area=(row.get("rural_urban_area") or "").strip() or None,
                    language_id=row.get("language_id") or row.get("languageId"),
                    lgd_code=(row.get("lgd_code") or row.get("lgdCode") or "").strip() or None,
                    state_id=to_int_safe(row.get("state_id") or row.get("stateId")),
                    district=district_obj,
                    block=block_obj
                )
                objs.append(obj)
                if len(objs) >= batch_size:
                    Panchayat.objects.bulk_create(objs, ignore_conflicts=True)
                    created += len(objs)
                    objs = []
                    self.stdout.write(f"  inserted {created} panchayats so far...")
            if objs:
                Panchayat.objects.bulk_create(objs, ignore_conflicts=True)
                created += len(objs)
        self.stdout.write(self.style.SUCCESS(f"Imported panchayats: approx {created} (scanned {seen})"))

    def import_villages(self, batch_size):
        if not os.path.exists(VILLAGES_CSV):
            self.stdout.write(self.style.WARNING(f"{VILLAGES_CSV} not found — skipping villages import"))
            return
        self.stdout.write("Importing villages...")
        # cache panchayats by id
        panchayat_map = {p.panchayat_id: p for p in Panchayat.objects.all()}

        created = 0
        objs = []
        seen = 0
        with open(VILLAGES_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                seen += 1
                # villageId may be 'villageId' or 'village_id' in CSV; try both.
                vid = to_int_safe(row.get("villageId") or row.get("village_id") or row.get("villageId"))
                # panchayat id in CSV:
                pid = to_int_safe(row.get("panchayat_id") or row.get("panchayatId"))
                if not vid or not pid:
                    self.stdout.write(self.style.WARNING(f"Skipping village row without parsable ids: {row}"))
                    continue
                panch = panchayat_map.get(pid)
                if not panch:
                    self.stdout.write(self.style.WARNING(f"Village {vid} references missing panchayat {pid} — skipping"))
                    continue

                is_active = bool_from_str(row.get("isActive") or row.get("is_active") or row.get("is_active"))
                # villageCode may be numeric in scientific notation -> treat as string to preserve formatting
                village_code = (row.get("villageCode") or row.get("village_code") or "").strip() or None

                obj = Village(
                    village_id=vid,
                    village_code=village_code,
                    village_name_english=row.get("villageNameEnglish") or row.get("village_name_english") or row.get("village_name"),
                    village_name_local=row.get("villageNameLocal") or row.get("village_name_local"),
                    rural_urban_area=(row.get("ruralUrbanArea") or row.get("rural_urban_area") or "").strip() or None,
                    is_active=is_active,
                    lgd_code=(row.get("lgdCode") or row.get("lgd_code") or "").strip() or None,
                    panchayat=panch,
                    state_id=to_int_safe(row.get("stateId") or row.get("state_id")),
                    district_id=to_int_safe(row.get("districtId") or row.get("district_id")),
                    block_id=to_int_safe(row.get("blockId") or row.get("block_id")),
                )
                objs.append(obj)
                if len(objs) >= batch_size:
                    Village.objects.bulk_create(objs, ignore_conflicts=True)
                    created += len(objs)
                    objs = []
                    self.stdout.write(f"  inserted {created} villages so far...")
            if objs:
                Village.objects.bulk_create(objs, ignore_conflicts=True)
                created += len(objs)
        self.stdout.write(self.style.SUCCESS(f"Imported villages: approx {created} (scanned {seen})"))
