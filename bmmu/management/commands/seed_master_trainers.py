# bmmu/management/commands/seed_master_trainers.py
import random
import string
from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction

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

DISTRICTS = ["AGRA", "LUCKNOW", "KANPUR", "ALLAHABAD", "GORAKHPUR", "VARANASI", "MATHURA", "FIROZABAD"]
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

def random_mobile():
    first = random.choice(["7","8","9"])
    return first + "".join(random.choice("0123456789") for _ in range(9))

def random_aadhaar():
    return "".join(random.choice("0123456789") for _ in range(12))

def random_bank_account():
    return "".join(random.choice("0123456789") for _ in range(12))

def random_ifsc_and_bank():
    bank, ifsc = random.choice(BANKS)
    if not ifsc or len(ifsc) < 8:
        ifsc = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(11))
    return bank, ifsc

def random_date_between(start_year=1965, end_year=1998):
    start = date(start_year, 1, 1)
    endd = date(end_year, 12, 31)
    delta = (endd - start).days
    return start + timedelta(days=random.randint(0, max(0, delta)))

def sample_skills():
    sectors = [
        "Livelihood", "Financial Inclusion", "Agriculture", "Entrepreneurship",
        "SHG strengthening", "Nutrition", "WASH", "Vocational training",
        "Digital Literacy", "Gender", "Health"
    ]
    picks = random.sample(sectors, k=random.randint(1, 4))
    return ", ".join(picks)

class Command(BaseCommand):
    help = "Seed MasterTrainer and MasterTrainerCertificate demo data. Requires existing TrainingPlan rows."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=310, help="Number of master trainers to create (default 310).")
        parser.add_argument("--max-certs", type=int, default=3, help="Max certificates per trainer (1..max).")
        parser.add_argument("--create-users", action="store_true", help="Also create associated User with username=mobile_no and password=<first_name>@123.")
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

        # gather existing training plan ids — MUST be present
        plan_ids = list(TrainingPlan.objects.values_list("id", flat=True))
        if not plan_ids:
            self.stderr.write("ERROR: No TrainingPlan rows found in the database.")
            self.stderr.write("Please create at least one TrainingPlan (via admin or import) before running this seeder.")
            return 2

        self.stdout.write(f"Found {len(plan_ids)} TrainingPlan rows (certificates will be linked randomly to these).")

        # build trainers in-memory and bulk_create in chunks
        generated_mobiles = []
        trainers_buffer = []
        created_count = 0

        for i in range(count):
            full_name = random_name()
            mobile = random_mobile()
            # ensure unique mobile in this run and avoid collisions with existing MasterTrainer mobiles
            while mobile in generated_mobiles or MasterTrainer.objects.filter(mobile_no=mobile).exists():
                mobile = random_mobile()
            generated_mobiles.append(mobile)

            aadhaar = random_aadhaar()
            dob = random_date_between()
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

            if len(trainers_buffer) >= chunk:
                MasterTrainer.objects.bulk_create(trainers_buffer)
                created_count += len(trainers_buffer)
                self.stdout.write(f"Bulk inserted {len(trainers_buffer)} trainers (total so far {created_count})")
                trainers_buffer = []

        if trainers_buffer:
            MasterTrainer.objects.bulk_create(trainers_buffer)
            created_count += len(trainers_buffer)
            self.stdout.write(f"Final bulk inserted {len(trainers_buffer)} trainers (total {created_count})")
            trainers_buffer = []

        # fetch the created trainers to get their PKs
        trainers_qs = list(MasterTrainer.objects.filter(mobile_no__in=generated_mobiles).order_by('id'))
        trainer_by_mobile = {t.mobile_no: t for t in trainers_qs}
        self.stdout.write(f"Loaded {len(trainers_qs)} MasterTrainer objects from DB.")

        # optionally create Users and attach to trainers
        if create_users:
            created_users = 0
            with transaction.atomic():
                for mobile in generated_mobiles:
                    trainer = trainer_by_mobile.get(mobile)
                    if not trainer:
                        continue
                    username = mobile
                    first_name_token = (trainer.full_name.split()[0] if trainer.full_name else "user")
                    password = f"{first_name_token}@123"
                    email = f"{username}@example.com"
                    try:
                        user = User.objects.filter(username=username).first()
                        if user is None:
                            user = User.objects.create_user(username=username, password=password, email=email)
                        # set role if field exists
                        if hasattr(user, "role"):
                            user.role = "master_trainer"
                            user.save(update_fields=["role"])
                        # link user to trainer
                        if trainer.user_id != user.id:
                            trainer.user = user
                            trainer.save(update_fields=["user"])
                        created_users += 1
                    except Exception as e:
                        self.stdout.write(f"Warning: could not create/link user for mobile {mobile}: {e}")
                        continue
            self.stdout.write(f"Created/linked {created_users} user accounts (username=mobile_no, password=<first_name>@123).")

        # create certificates: every certificate must link to one of existing TrainingPlan rows
        certs_buffer = []
        cert_count = 0
        for trainer in trainers_qs:
            num = random.randint(1, max_certs)
            for _ in range(num):
                cert_no = str(random.randint(10**8, 10**11))
                plan_id = random.choice(plan_ids)
                training_module = TrainingPlan.objects.get(id=plan_id)
                issued_on = date.today() - timedelta(days=random.randint(10, 600))
                cert = MasterTrainerCertificate(
                    trainer=trainer,
                    certificate_number=cert_no,
                    training_module=training_module,
                    certificate_file=None,
                    issued_on=issued_on
                )
                certs_buffer.append(cert)
                cert_count += 1

                if len(certs_buffer) >= chunk:
                    MasterTrainerCertificate.objects.bulk_create(certs_buffer)
                    self.stdout.write(f"Bulk inserted {len(certs_buffer)} certificates (total so far {cert_count})")
                    certs_buffer = []

        if certs_buffer:
            MasterTrainerCertificate.objects.bulk_create(certs_buffer)
            self.stdout.write(f"Final bulk inserted {len(certs_buffer)} certificates (total {cert_count})")
            certs_buffer = []

        self.stdout.write(self.style.SUCCESS(f"Done. Trainers created: {created_count}; Certificates created: {cert_count}"))
        return
