# bmmu/management/commands/seed_training_partners.py
import random
import re
from datetime import date
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.contrib.auth.hashers import make_password

from bmmu.models import TrainingPartner

User = get_user_model()

SAMPLE_PARTNERS = [
    # (org_name, contact_person, district/center_location)
    ("SevaTrust", "Ramesh Kumar", "Agra"),
    ("GramSakha", "Anita Verma", "Lucknow"),
    ("NariShakti Foundation", "Priya Singh", "Kanpur"),
    ("Jeevan Pragati", "Manish Sharma", "Varanasi"),
    ("AshaVikas", "Sunita Patel", "Mathura"),
    ("Sakhi Samuha", "Kavita Yadav", "Firozabad"),
    ("UdaySamaj", "Sanjay Reddy", "Gorakhpur"),
    ("KrishiSahay", "Amit Joshi", "Allahabad"),
    ("Disha NGO", "Neha Gupta", "Meerut"),
    ("NavaJyoti", "Pankaj Kumar", "Prayagraj"),
    ("JanSeva", "Alka Iyer", "Faizabad"),
]

BANKS = [
    ("Punjab National Bank", "PUNB17IF"),
    ("State Bank of India", "SBIN0001234"),
    ("Bank of Baroda", "BARB0XYZ123"),
    ("ICICI Bank", "ICIC0000045"),
    ("HDFC Bank", "HDFC0000123"),
]

def slugify_org(name: str) -> str:
    # simple slug: lowercase, replace spaces with nothing, remove non-alnum
    s = name.lower()
    s = re.sub(r'\s+', '', s)
    s = re.sub(r'[^a-z0-9]', '', s)
    return s or "org"

def random_mobile():
    # returns 10-digit mobile starting with 7-9
    first = random.choice(["7","8","9"])
    return first + "".join(random.choice("0123456789") for _ in range(9))

def random_bank_account():
    return "".join(random.choice("0123456789") for _ in range(12))

class Command(BaseCommand):
    help = "Create 11 realistic TrainingPartner demo records and (by default) associated User accounts."

    def add_arguments(self, parser):
        parser.add_argument("--no-users", action="store_true", help="Do not create User accounts (default is to create).")
        parser.add_argument("--skip-existing", action="store_true", help="Skip partners that already exist with the exact same name.")
        parser.add_argument("--seed", type=int, default=None, help="Optional random seed for reproducibility.")

    def handle(self, *args, **options):
        create_users = not options["no_users"]
        skip_existing = options["skip_existing"]
        seed = options["seed"]

        if seed is not None:
            random.seed(seed)

        self.stdout.write("Seeding TrainingPartner demo data (11 partners).")
        partners_created = 0
        users_created = 0

        # prepare password hash cache to avoid repeated expensive hashing
        hashed_cache = {}

        with transaction.atomic():
            for org_name, contact_person, center_loc in SAMPLE_PARTNERS:
                # check existing by exact name
                if skip_existing and TrainingPartner.objects.filter(name=org_name).exists():
                    self.stdout.write(f"Skipping existing partner (by name): {org_name}")
                    continue

                # generate realistic details
                slug = slugify_org(org_name)
                username = f"{slug}@tp"
                raw_password = f"{slug}@123"
                email = f"{slug}@{slug}.com"  # matches 'org_name.com' style you requested
                contact_mobile = random_mobile()
                bank_name, bank_ifsc = random.choice(BANKS)
                bank_account = random_bank_account()
                tpm_reg = f"TPM-{random.randint(10000, 99999)}"
                address = f"{org_name} Office, Near Market, {center_loc}"

                # create TrainingPartner (no file fields)
                tp = TrainingPartner.objects.create(
                    user=None,
                    name=org_name,
                    contact_person=contact_person,
                    contact_mobile=contact_mobile,
                    email=email,
                    address=address,
                    center_location=center_loc,
                    bank_name=bank_name,
                    bank_branch=f"{center_loc} Branch",
                    bank_ifsc=bank_ifsc,
                    bank_account_number=bank_account,
                    tpm_registration_no=tpm_reg,
                    certifications="Registered NGO / TP (demo data)",
                    photographs_submission=None,
                    targets_allocated=None,
                )
                partners_created += 1
                self.stdout.write(f"Created partner: {tp.name} (contact: {contact_person}, mobile: {contact_mobile})")

                # create and link User if requested
                if create_users:
                    # cache hashed password by raw_password
                    hashed = hashed_cache.get(raw_password)
                    if hashed is None:
                        hashed = make_password(raw_password)
                        hashed_cache[raw_password] = hashed

                    try:
                        user = None
                        # reuse existing user if username present
                        user = User.objects.filter(username=username).first()
                        if user is None:
                            # create user with pre-hashed password to avoid re-hashing
                            user = User(username=username, password=hashed, email=email)
                            # set role if exists
                            if hasattr(user, "role"):
                                try:
                                    user.role = "training_partner"
                                except Exception:
                                    pass
                            user.save()
                            users_created += 1
                            self.stdout.write(f"  -> Created user: {username} (password: {raw_password})")
                        else:
                            # ensure role is set if possible
                            if hasattr(user, "role") and getattr(user, "role", None) != "training_partner":
                                user.role = "training_partner"
                                user.save(update_fields=["role"])
                                self.stdout.write(f"  -> Updated role for existing user: {username}")

                        # link user to training partner if not linked
                        if tp.user_id != user.id:
                            tp.user = user
                            tp.save(update_fields=["user"])
                    except Exception as e:
                        self.stderr.write(f"Warning: could not create/link user for {org_name}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Done. Partners created: {partners_created}; Users created (new): {users_created}"))
        self.stdout.write("Notes:")
        self.stdout.write(" - File fields (mou_form, signed_report_file) and photographs_submission/targets_allocated are left blank as requested.")
        self.stdout.write(" - To inspect created partners run: python manage.py shell_plus (or use admin).")
