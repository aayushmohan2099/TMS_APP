# bmmu/management/commands/create_shgs_from_beneficiaries.py
from collections import Counter
import itertools
from django.core.management.base import BaseCommand
from django.db import transaction, DatabaseError
from django.db.models import Min
from bmmu.models import Beneficiary, SHG  # <-- adjust 'yourapp' to your app name

class Command(BaseCommand):
    help = "Create SHG rows from Beneficiary data (distinct shg_code). Picks most-common district/block/state/shg_name per SHG."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Do not save, only show what would be created.')
        parser.add_argument('--limit', type=int, default=0, help='Limit number of SHGs to process (0 = all).')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']

        codes_qs = Beneficiary.objects.exclude(shg_code__isnull=True).exclude(shg_code__exact='') \
            .values('shg_code').distinct().order_by('shg_code')
        total_codes = codes_qs.count()
        self.stdout.write(self.style.NOTICE(f"Found {total_codes} distinct shg_code values in Beneficiary table."))

        processed = created = skipped = errors = 0

        codes_iter = (c['shg_code'] for c in codes_qs)
        if limit and limit > 0:
            codes_iter = itertools.islice(codes_iter, limit)

        for shg_code in codes_iter:
            processed += 1
            try:
                # fetch beneficiaries for this SHG code
                b_qs = Beneficiary.objects.filter(shg_code=shg_code).select_related('district', 'block')

                if not b_qs.exists():
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"Skipping '{shg_code}': no beneficiaries found."))
                    continue

                member_count = b_qs.count()

                # Collect most-common district_id and block_id (non-null only)
                district_ids = [b.district_id for b in b_qs if b.district_id]
                block_ids = [b.block_id for b in b_qs if b.block_id]

                district_obj = None
                block_obj = None

                if district_ids:
                    most_common_did, _ = Counter(district_ids).most_common(1)[0]
                    # find one beneficiary with that district id and return its object (safe)
                    district_obj = next((b.district for b in b_qs if b.district_id == most_common_did and b.district), None)

                if block_ids:
                    most_common_bid, _ = Counter(block_ids).most_common(1)[0]
                    block_obj = next((b.block for b in b_qs if b.block_id == most_common_bid and b.block), None)

                # Most common non-empty state and shg_name
                state_vals = [b.state.strip() for b in b_qs if b.state and b.state.strip()]
                shg_name_vals = [b.shg_name.strip() for b in b_qs if b.shg_name and b.shg_name.strip()]

                state = Counter(state_vals).most_common(1)[0][0] if state_vals else None
                shg_name = Counter(shg_name_vals).most_common(1)[0][0] if shg_name_vals else None

                # Safely compute earliest date_of_formation; guard DB errors
                try:
                    min_date = b_qs.aggregate(Min('date_of_formation'))['date_of_formation__min']
                except DatabaseError as db_e:
                    self.stdout.write(self.style.ERROR(f"DB error aggregating date_of_formation for '{shg_code}': {db_e}"))
                    min_date = None

                # Skip if SHG already exists with same code (idempotent)
                if SHG.objects.filter(shg_code=shg_code).exists():
                    self.stdout.write(self.style.WARNING(f"SHG with code '{shg_code}' already exists — skipping."))
                    skipped += 1
                    continue

                # Build SHG instance
                shg_obj = SHG(
                    shg_code=shg_code,
                    shg_name=shg_name,
                    state=state,
                    district=district_obj,
                    block=block_obj,
                    date_of_formation=min_date
                )

                # Build display labels safely
                def label_for(obj, pref_name_candidates=('name', 'district_name', 'title')):
                    if not obj:
                        return "None"
                    # primary key
                    pk = getattr(obj, 'pk', None)
                    name = None
                    for attr in pref_name_candidates:
                        name = getattr(obj, attr, None)
                        if name:
                            break
                    if not name:
                        # fallback to str(obj)
                        name = str(obj)
                    return f"{pk or '(pk?)'} - {name}"

                district_label = label_for(district_obj)
                block_label = label_for(block_obj)

                if dry_run:
                    self.stdout.write(self.style.SUCCESS(
                        "[DRY RUN] Would create SHG: "
                        f"code={shg_code}, name={shg_name or 'None'}, state={state or 'None'}, "
                        f"district={district_label}, block={block_label}, formation={min_date}, members={member_count}"
                    ))
                    created += 1
                else:
                    with transaction.atomic():
                        shg_obj.save()
                    self.stdout.write(self.style.SUCCESS(f"Created SHG id={getattr(shg_obj, 'pk', 'N/A')} code={shg_code} members={member_count}"))
                    created += 1

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f"Error processing '{shg_code}': {e}"))

        # Summary
        self.stdout.write(self.style.NOTICE("=== Summary ==="))
        self.stdout.write(self.style.SUCCESS(f"Processed: {processed}"))
        self.stdout.write(self.style.SUCCESS(f"Created (or would create): {created}"))
        self.stdout.write(self.style.WARNING(f"Skipped: {skipped}"))
        self.stdout.write(self.style.ERROR(f"Errors: {errors}"))
        if dry_run:
            self.stdout.write(self.style.NOTICE("Dry-run mode — no DB objects were created."))
