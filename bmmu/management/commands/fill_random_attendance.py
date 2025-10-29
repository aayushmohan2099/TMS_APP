# training_mgmnt/management/commands/fill_random_attendance.py
import random
from datetime import timedelta, date, datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from bmmu.models import (
    Batch,
    BatchAttendance,
    ParticipantAttendance,
    BatchBeneficiary,
)

# Optional: if trainers are stored via TrainerBatchParticipation through-batch relation
try:
    from bmmu.models import TrainerBatchParticipation
    HAVE_TRAINER_PARTICIPATION = True
except Exception:
    TrainerBatchParticipation = None
    HAVE_TRAINER_PARTICIPATION = False


class Command(BaseCommand):
    help = "Populate demo/random attendance records for batches. Skips first day by default."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Overwrite existing attendance participant records for a date (will update present flag).'
        )
        parser.add_argument(
            '--future',
            action='store_true',
            help='Also create attendance rows for future dates up to batch.end_date (default is up to today).'
        )
        parser.add_argument(
            '--prob-trainer',
            type=float,
            default=0.9,
            help='Probability (0-1) that a trainer is present on any given day. Default: 0.9'
        )
        parser.add_argument(
            '--prob-beneficiary',
            type=float,
            default=0.8,
            help='Probability (0-1) that a beneficiary is present on any given day. Default: 0.8'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Optional: limit to N batches (0 = all)'
        )

    def handle(self, *args, **options):
        force = options['force']
        include_future = options['future']
        prob_trainer = float(options['prob_trainer'])
        prob_beneficiary = float(options['prob_beneficiary'])
        limit = int(options.get('limit') or 0)

        # ensure sane ranges
        prob_trainer = max(0.0, min(1.0, prob_trainer))
        prob_beneficiary = max(0.0, min(1.0, prob_beneficiary))

        # today with India timezone for consistency (falls back to django timezone)
        try:
            india_tz = ZoneInfo("Asia/Kolkata")
            today = datetime.now(tz=india_tz).date()
        except Exception:
            today = timezone.localdate()

        batches_qs = Batch.objects.all().select_related('request').order_by('id')
        if limit > 0:
            batches_qs = batches_qs[:limit]

        total_batches = batches_qs.count()
        self.stdout.write(self.style.NOTICE(f"Processing {total_batches} batch(es). Today = {today.isoformat()}"))
        created_attendance = 0
        created_participant_records = 0
        updated_participant_records = 0
        skipped_existing = 0
        errors = 0

        for batch in batches_qs:
            try:
                start = batch.start_date
                end = batch.end_date
                if not start or not end:
                    self.stdout.write(self.style.WARNING(f"Batch {batch.id} ({getattr(batch,'code',None)}) has missing start/end; skipping."))
                    continue
                if end < start:
                    self.stdout.write(self.style.WARNING(f"Batch {batch.id} ({getattr(batch,'code',None)}) end_date < start_date; skipping."))
                    continue

                # last date to create: either end or min(end, today) unless --future passed
                last_date = end if include_future else min(end, today)

                # Build list of dates from start to last_date inclusive
                delta_days = (last_date - start).days
                if delta_days < 0:
                    self.stdout.write(self.style.WARNING(f"Batch {batch.id} has no dates to generate (start after last_date); skipping."))
                    continue

                # Skip first day: we interpret "1st day attendance is done" to mean don't touch start_date
                # We'll create attendance for dates start+1 .. last_date
                first_day = start
                first_day_plus_one = start + timedelta(days=1)
                dates_to_create = []
                for i in range((last_date - start).days + 1):
                    d = start + timedelta(days=i)
                    if d <= last_date and d >= first_day_plus_one:
                        dates_to_create.append(d)

                if not dates_to_create:
                    self.stdout.write(self.style.NOTICE(f"Batch {batch.id} ({getattr(batch,'code',None)}) has no days to auto-fill (maybe only first day or in future)."))
                    continue

                # Collect trainers and beneficiaries for this batch
                # Trainers: prefer TrainerBatchParticipation if present; else fallback to batch.trainers.all()
                trainers = []
                if HAVE_TRAINER_PARTICIPATION and TrainerBatchParticipation:
                    trainers = [tp.trainer for tp in TrainerBatchParticipation.objects.filter(batch=batch).select_related('trainer')]
                else:
                    # fallback: try m2m 'trainers' on Batch
                    try:
                        trainers = list(batch.trainers.all())
                    except Exception:
                        trainers = []

                # Beneficiaries: from BatchBeneficiary join model (very important)
                try:
                    ben_qs = BatchBeneficiary.objects.filter(batch=batch).select_related('beneficiary')
                    beneficiaries = [bb.beneficiary for bb in ben_qs]
                except Exception:
                    beneficiaries = []

                # For each date create BatchAttendance (if missing) and ParticipantAttendance rows
                for attend_date in dates_to_create:
                    try:
                        with transaction.atomic():
                            attendance_obj, attendance_created = BatchAttendance.objects.get_or_create(batch=batch, date=attend_date)
                            if attendance_created:
                                created_attendance += 1
                            else:
                                # If attendance exists and --force is not set, we skip updating participant present flags
                                if not force:
                                    skipped_existing += 1
                                    continue

                            # For each trainer
                            for t in trainers:
                                present = random.random() < prob_trainer
                                pa_defaults = {'participant_name': getattr(t, 'full_name', str(t)), 'present': present, 'participant_role': 'trainer'}
                                obj, created = ParticipantAttendance.objects.update_or_create(
                                    attendance=attendance_obj,
                                    participant_id=t.id,
                                    participant_role='trainer',
                                    defaults=pa_defaults
                                )
                                if created:
                                    created_participant_records += 1
                                else:
                                    # count updates only if we explicitly changed present or force
                                    updated_participant_records += 1

                            # For each beneficiary
                            for b in beneficiaries:
                                present = random.random() < prob_beneficiary
                                pa_defaults = {'participant_name': getattr(b, 'member_name', None) or getattr(b, 'full_name', None) or str(b),
                                               'present': present, 'participant_role': 'beneficiary'}
                                obj, created = ParticipantAttendance.objects.update_or_create(
                                    attendance=attendance_obj,
                                    participant_id=b.id,
                                    participant_role='beneficiary',
                                    defaults=pa_defaults
                                )
                                if created:
                                    created_participant_records += 1
                                else:
                                    updated_participant_records += 1
                    except Exception as e:
                        errors += 1
                        self.stderr.write(self.style.ERROR(f"Error creating attendance for batch {batch.id} on {attend_date}: {e}"))
            except Exception as e:
                errors += 1
                self.stderr.write(self.style.ERROR(f"Unhandled error processing batch {getattr(batch,'id',None)}: {e}"))

        self.stdout.write(self.style.SUCCESS("Random attendance generation complete."))
        self.stdout.write(self.style.SUCCESS(f"Attendance rows created: {created_attendance}"))
        self.stdout.write(self.style.SUCCESS(f"Participant attendance records created: {created_participant_records}"))
        self.stdout.write(self.style.SUCCESS(f"Participant attendance records updated: {updated_participant_records}"))
        self.stdout.write(self.style.NOTICE(f"Existing attendance dates skipped (no --force): {skipped_existing}"))
        if errors:
            self.stdout.write(self.style.ERROR(f"Errors encountered: {errors}"))

        self.stdout.write(self.style.NOTICE("Done."))
