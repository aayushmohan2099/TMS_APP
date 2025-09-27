# bmmu/management/commands/seed_master_trainers.py
import random
import string
from datetime import date, timedelta, datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db import IntegrityError

from bmmu.models import MasterTrainer, MasterTrainerCertificate, TrainingPlan

User = get_user_model()

FIRST_NAMES = [
    "Imran","Asha","Sunita","Rajesh","Suresh","Priya","Amit","Neha","Rahul","Shreya",
    "Vikram","Anita","Ramesh","Deepa","Pooja","Kavita","Mohit","Sanjay","Pankaj","Alka",
    "Nita","Arjun","Ritu","Manish","Seema","Kiran","Gaurav","Sneha","Ishaan","Alvi"
]
LAST_NAMES = [
    "Patel","Kumar","Sharma","Singh","Verma","Gupta","Jain","Choudhary","Yadav","Khan",
    "Reddy","Nair","Mehta","Iyer","Joshi","Saxena","Agarwal","Bhat","Alvi","Malhotra"
]

DISTRICTS = ["AGRA", "LUCKNOW", "KANPUR", "ALLAHABAD", "GORAKHPUR", "VARANASI", "GORAKHPUR", "MATHURA", "FIROZABAD"]
BANKS = [
    ("Punjab National Bank", "PUNB17IF"),
    ("State Bank of India", "SBIN0001234"),
    ("Bank of Baroda", "BARB0XYZ123"),
    ("ICICI Bank", "ICIC0000045"),
    ("HDFC Bank", "HDFC0000123"),
]
SOCIAL_CATS = ["UR", "SC", "ST", "OBC"]
GENDERS = ["Male", "Female", "Other"]
DESIGNS = ["DRP", "SRP"]

def random_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

def random_mobile(prefix="9"):
    # produce 10-digit mobile starting with 7-9
    first = random.choice(["7","8","9"])
    return first + "".join(random.choice("0123456789") for _ in range(9))

def random_aadhaar():
    # 12-digit-ish number (not real Aadhaar)
    return "".join(random.choice("0123456789") for _ in range(12))

def random_bank_account():
    return "".join(random.choice("0123456789") for _ in range(12))

def random_ifsc_and_bank():
    bank, ifsc = random.choice(BANKS)
    # ensure IFSC length plausible; allow existing or create pseudo IFSC
    if not ifsc or len(ifsc) < 8:
        ifsc = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(11))
    return bank, ifsc

def random_date_between(start_year=1970, end_year=1998):
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(0, delta)))

def sample_skills():
    sectors = [
        "Livelihood", "Financial Inclusion", "Agriculture", "Entrepreneurship",
        "SHG strengthening", "Nutrition", "Water Sanitation", "WASH", "Vocational training",
        "Digital Literacy", "Gender", "Health"
    ]
    picks = random.sample(sectors, k=random.randint(1, 4))
    return ", ".join(picks)

class Command(BaseCommand):
    help = "Seed MasterTrainer and MasterTrainerCertificate demo data (300-320 trainers by default)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=310, help="Number of master trainers to create (default 310).")
        parser.add_argument("--max-certs", type=int, default=3, help="Max certificates per trainer (1..max).")
        parser.add_argument("--create-users", action="store_true", help="Also create associated User with username=mobile_no and password='password'.")
        parser.add_argument("--chunk", type=int, default=200, help="Chunk size for bulk_create.")
        parser.add_argument("--seed", type=int, default=None, help="Optional random seed for reproducibility.")

    def handle(self, *args, **options):
        count = options["count"]
        max_certs = max(1, options["max_certs"])
        create_users = options["create_users"]
        chunk = max(50, options["chunk"])
        seed = options["seed"]

        if seed is not None:
            random.seed(seed)

        self.stdout.write(f"Seeding {count} MasterTrainer rows (max_certs={max_certs}, create_users={create_users})")

        # collect mobiles for lookup after bulk_create
        generated_mobiles = []
        trainers_buffer = []

        # Ensure we have TrainingPlan IDs available for linking certificates (optional)
        plan_ids = list(TrainingPlan.objects.values_list("id", flat=True))
        self.stdout.write(f"Found {len(plan_ids)} TrainingPlan rows to possibly link certificates.")

        # create trainer dicts
        for i in range(count):
            full_name = random_name()
            mobile = random_mobile()
            # ensure unique mobile in this run
            while mobile in generated_mobiles or MasterTrainer.objects.filter(mobile_no=mobile).exists():
                mobile = random_mobile()
            generated_mobiles.append(mobile)

            aadhaar = random_aadhaar()
            # date_of_birth between 1965 and 1998
            dob = random_date_between(1965, 1998)
            bank_name, ifsc = random_ifsc_and_bank()
            acc = random_bank_account()
            district = random.choice(DISTRICTS)
            designation = random.choice(DESIGNS)
            social = random.choice(SOCIAL_CATS)
            gender = random.choice(GENDERS)
            education = random.choice(["LITERATE", "HIGH SCHOOL", "GRADUATE", "POST GRADUATE"])
            parent_name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
            skills = sample_skills()

            mt = MasterTrainer(
                full_name=full_name,
                date_of_birth=dob,
                mobile_no=mobile,
                aadhaar_no=aadhaar,
                empanel_district=district,
                social_category=social,
                gender=gender,
                education=education,
                marital_status=random.choice(["Unmarried","Married"]),
                parent_or_spouse_name=parent_name,
                skills=skills,
                thematic_expert_recommendation=None,
                success_rate=round(random.uniform(60.0, 99.0), 2),
                any_other_tots="Generated demo ToTs",
                other_achievements="Demo achievements",
                recommended_tots_by_dmmu="Auto-recommended",
                success_story_publications="None",
                bank_account_number=acc,
                ifsc=ifsc,
                branch_name=f"{district} Branch",
                bank_name=bank_name,
                designation=designation
            )
            trainers_buffer.append(mt)

            # bulk-create in chunks
            if len(trainers_buffer) >= chunk:
                MasterTrainer.objects.bulk_create(trainers_buffer)
                self.stdout.write(f"Bulk inserted {len(trainers_buffer)} trainers (total so far {len(generated_mobiles)})")
                trainers_buffer = []

        # flush remainder
        if trainers_buffer:
            MasterTrainer.objects.bulk_create(trainers_buffer)
            self.stdout.write(f"Final bulk inserted {len(trainers_buffer)} trainers (total {len(generated_mobiles)})")
            trainers_buffer = []

        # optionally create associated User accounts
        if create_users:
            created_users = 0
            for mobile in generated_mobiles:
                username = mobile
                if User.objects.filter(username=username).exists():
                    continue
                try:
                    u = User.objects.create_user(username=username, password="password", email=f"{username}@example.com")
                    # set role if custom user model supports it
                    if hasattr(u, "role"):
                        u.role = "master_trainer"
                        u.save()
                    created_users += 1
                except Exception as e:
                    self.stdout.write(f"Could not create user for {username}: {e}")
            self.stdout.write(f"Created {created_users} user accounts (username=mobile_no, password='password').")

        # Now fetch created trainers by mobile numbers (ensures we have PKs)
        trainers_qs = list(MasterTrainer.objects.filter(mobile_no__in=generated_mobiles).order_by('id'))
        self.stdout.write(f"Loaded {len(trainers_qs)} MasterTrainer objects from DB for certificate creation.")

        # Build certificates
        certs_buffer = []
        cert_count = 0
        for trainer in trainers_qs:
            num = random.randint(1, max_certs)
            for j in range(num):
                # generate certificate_number as readable 9-12 digit string
                cert_no = str(random.randint(10**8, 10**11))
                title_samples = [
                    "SRP ORIENTATION (TNCB)",
                    "DRP ORIENTATION ON BOR (MCLF)",
                    "VO EC MEMBER M2 TRAINING (SMCB)",
                    "SHG MANAGEMENT TRAINING",
                    "FINANCIAL LITERACY TO TRAINERS",
                    "AGRICULTURE SUSTAINABILITY MODULE"
                ]
                training_module_id = random.choice(plan_ids) if plan_ids and random.random() < 0.6 else None
                training_module = None
                if training_module_id:
                    try:
                        training_module = TrainingPlan.objects.get(id=training_module_id)
                    except TrainingPlan.DoesNotExist:
                        training_module = None

                issued_on = date.today() - timedelta(days=random.randint(10, 600))  # within last ~2 years
                cert = MasterTrainerCertificate(
                    trainer=trainer,
                    certificate_number=cert_no,
                    training_module=training_module,
                    certificate_file=None,   # leave blank as requested
                    issued_on=issued_on
                )
                certs_buffer.append(cert)
                cert_count += 1

                # flush certs in chunks
                if len(certs_buffer) >= chunk:
                    MasterTrainerCertificate.objects.bulk_create(certs_buffer)
                    self.stdout.write(f"Bulk inserted {len(certs_buffer)} certificates (total so far {cert_count})")
                    certs_buffer = []

        # flush remaining certificates
        if certs_buffer:
            MasterTrainerCertificate.objects.bulk_create(certs_buffer)
            self.stdout.write(f"Final bulk inserted {len(certs_buffer)} certificates (total {cert_count})")
            certs_buffer = []

        self.stdout.write(self.style.SUCCESS(f"Done. Trainers created: {len(generated_mobiles)}; Certificates created: {cert_count}"))
        return
