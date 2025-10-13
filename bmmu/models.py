# models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils.text import slugify
from django.utils import timezone
from django.core.exceptions import ValidationError

# -------------------------
# Core user model
# -------------------------
class User(AbstractUser):
    ROLE_CHOICES = [
        ('bmmu', 'BMMU'),
        ('dmmu', 'DMMU'),
        ('smmu', 'SMMU'),
        ('training_partner', 'Training Partner'),
        ('master_trainer', 'Master Trainer'),
        ('admin', 'Admin'),
    ]

    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default='bmmu')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


# -------------------------
# District, Block, Panchayat, Village models
# -------------------------
class Mandal(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, db_index=True)

    class Meta:
        verbose_name = "Mandal"
        verbose_name_plural = "Mandals"
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return self.name


class District(models.Model):
    district_id = models.BigIntegerField(primary_key=True)   # API id
    district_code = models.CharField(max_length=50, blank=True, null=True)
    state_id = models.IntegerField(blank=True, null=True, db_index=True)
    district_name_en = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    district_short_name_en = models.CharField(max_length=50, blank=True, null=True)
    district_name_local = models.CharField(max_length=255, blank=True, null=True)
    lgd_code = models.CharField(max_length=64, blank=True, null=True)
    language_id = models.CharField(max_length=20, blank=True, null=True)

    mandal = models.ForeignKey(
        Mandal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='districts'
    )

    class Meta:
        verbose_name = "District"
        verbose_name_plural = "Districts"
        indexes = [
            models.Index(fields=['state_id']),
            models.Index(fields=['district_name_en']),
        ]

    def __str__(self):
        return f"{self.district_name_en or self.district_id}"


class Block(models.Model):
    block_id = models.BigIntegerField(primary_key=True)  # API block_id
    block_code = models.CharField(max_length=64, blank=True, null=True)
    block_name_en = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    block_name_local = models.CharField(max_length=255, blank=True, null=True)
    rural_urban_area = models.CharField(max_length=5, blank=True, null=True)
    lgd_code = models.CharField(max_length=64, blank=True, null=True)
    language_id = models.CharField(max_length=20, blank=True, null=True)
    state_id = models.IntegerField(blank=True, null=True, db_index=True)

    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name='blocks', db_index=True)

    district_name_en = models.CharField(max_length=255, blank=True, null=True)

    is_aspirational = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = "Block"
        verbose_name_plural = "Blocks"
        indexes = [
            models.Index(fields=['district']),
            models.Index(fields=['block_name_en']),
        ]

    def __str__(self):
        return f"{self.block_name_en or self.block_id}"


class Panchayat(models.Model):
    panchayat_id = models.BigIntegerField(primary_key=True)
    panchayat_code = models.CharField(max_length=64, blank=True, null=True)
    panchayat_name_en = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    panchayat_name_local = models.CharField(max_length=255, blank=True, null=True)
    rural_urban_area = models.CharField(max_length=5, blank=True, null=True)
    language_id = models.CharField(max_length=20, blank=True, null=True)
    lgd_code = models.CharField(max_length=64, blank=True, null=True)
    state_id = models.IntegerField(blank=True, null=True, db_index=True)

    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name='panchayats', db_index=True)
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='panchayats', db_index=True)

    class Meta:
        verbose_name = "Panchayat"
        verbose_name_plural = "Panchayats"
        indexes = [
            models.Index(fields=['district', 'block']),
            models.Index(fields=['panchayat_name_en']),
        ]

    def __str__(self):
        return f"{self.panchayat_name_en or self.panchayat_id}"


class Village(models.Model):
    village_id = models.BigIntegerField(primary_key=True)   # maps to villageId in API
    village_code = models.CharField(max_length=128, blank=True, null=True)
    village_name_english = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    village_name_local = models.CharField(max_length=255, blank=True, null=True)
    rural_urban_area = models.CharField(max_length=5, blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    lgd_code = models.CharField(max_length=64, blank=True, null=True)

    panchayat = models.ForeignKey(Panchayat, on_delete=models.CASCADE, related_name='villages', db_index=True)
    state_id = models.IntegerField(blank=True, null=True, db_index=True)
    district_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    block_id = models.BigIntegerField(blank=True, null=True, db_index=True)

    class Meta:
        verbose_name = "Village"
        verbose_name_plural = "Villages"
        indexes = [
            models.Index(fields=['panchayat']),
            models.Index(fields=['village_name_english']),
        ]

    def __str__(self):
        return f"{self.village_name_english or self.village_id}"


class DistrictCategory(models.Model):
    id = models.AutoField(primary_key=True)
    district = models.ForeignKey('District', on_delete=models.CASCADE, related_name='categories', db_index=True)
    category_name = models.CharField(max_length=255, db_index=True)

    class Meta:
        verbose_name = "District Category"
        verbose_name_plural = "District Categories"
        unique_together = ('district', 'category_name')
        indexes = [
            models.Index(fields=['district']),
            models.Index(fields=['category_name']),
        ]

    def __str__(self):
        return f"{self.district} -> {self.category_name}"


# -------------------------
# TrainingPlan
# -------------------------
class TrainingPlan(models.Model):
    id = models.AutoField(primary_key=True)
    training_name = models.CharField("Training name", max_length=255)
    theme = models.CharField("THEME", max_length=200, blank=True, null=True)

    TYPE_CHOICES = [
        ("RES", "Residential"),
        ("NON RES", "Non-residential"),
        ("OTHER", "Other"),
    ]
    type_of_training = models.CharField("Type of Training", max_length=20, choices=TYPE_CHOICES, default="OTHER")

    LEVEL_CHOICES = [
        ("VILLAGE", "Village"),
        ("SHG", "SHG"),
        ("CLF", "CLF"),
        ("BLOCK", "Block"),
        ("BLOCK_DISTRICT", "Block/District"),
        ("CMTC/BLOCK", "CMTC/Block"),
        ("DISTRICT", "District"),
        ("STATE", "State"),
        ("WITHIN_STATE", "Within State"),
        ("OUTSIDE_STATE", "Outside State"),
    ]
    level_of_training = models.CharField("Level of training", max_length=32, choices=LEVEL_CHOICES, blank=True, null=True)

    no_of_days = models.PositiveIntegerField("No of Days", blank=True, null=True)

    APPROVAL_CHOICES = [
        ("SANCTIONED", "Sanctioned"),
        ("PENDING", "Pending"),
        ("DENIED", "Denied"),
    ]
    approval_status = models.CharField("Approval of Training Plan", max_length=20, choices=APPROVAL_CHOICES, blank=True, null=True)

    theme_expert = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='theme_training_plans')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Training Plan"
        verbose_name_plural = "Training Plans"
        indexes = [
            models.Index(fields=['training_name']),
            models.Index(fields=['theme']),
        ]

    def __str__(self):
        return f"{self.training_name} ({self.theme or 'No theme'})"


# -------------------------
# Beneficiary
# -------------------------
class Beneficiary(models.Model):
    id = models.AutoField(primary_key=True)

    # Geographical Data
    state = models.CharField(max_length=150, blank=True, null=True, db_index=True)
    district = models.ForeignKey(
        District,
        on_delete=models.SET_NULL,
        related_name='beneficiary_district',
        null=True, blank=True,
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.SET_NULL,
        related_name='beneficiary_block',
        null=True, blank=True,
    )
    gram_panchayat = models.CharField(max_length=150, blank=True, null=True)
    village = models.CharField(max_length=150, blank=True, null=True)

    # SHG Data
    shg_code = models.CharField("SHG Code", max_length=100, blank=True, null=True, db_index=True)
    shg_name = models.CharField("SHG Name", max_length=200, blank=True, null=True)
    date_of_formation = models.DateField(blank=True, null=True)
    member_code = models.CharField("Member Code", max_length=100, blank=True, null=True, unique=True)
    member_name = models.CharField("Member Name", max_length=200, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    date_of_joining_shg = models.DateField(blank=True, null=True)
    designation_in_shg_vo_clf = models.CharField("Designation in SHG/VO/CLF", max_length=200, blank=True, null=True)

    # Member Data
    social_category = models.CharField("Social Category", max_length=50, blank=True, null=True)
    pvtg_category = models.CharField("PVTG Category", max_length=50, blank=True, null=True)
    religion = models.CharField("Religion", max_length=50, blank=True, null=True)
    gender = models.CharField(max_length=20, blank=True, null=True)
    education = models.CharField(max_length=200, blank=True, null=True)
    marital_status = models.CharField(max_length=50, blank=True, null=True)
    insurance_status = models.CharField("Insurance Status", max_length=20, blank=True, null=True)
    disability = models.CharField("Disability", max_length=20, blank=True, null=True)
    disability_type = models.CharField("Disability Type", max_length=200, blank=True, null=True)
    is_head_of_family = models.CharField("HOF", max_length=20, blank=True, null=True)
    parent_or_spouse_name = models.CharField("Father/Mother/Spouse Name", max_length=200, blank=True, null=True)
    relation = models.CharField("Relation for name", max_length=200, blank=True, null=True)

    # Banking Data
    account_number = models.CharField("Account Number (Default)", max_length=50, blank=True, null=True)
    ifsc = models.CharField("IFSC", max_length=20, blank=True, null=True)
    branch_name = models.CharField("Branch Name", max_length=200, blank=True, null=True)
    bank_name = models.CharField("Bank Name", max_length=200, blank=True, null=True)
    account_opening_date = models.DateField(blank=True, null=True)
    account_type = models.CharField("Account Type", max_length=200, blank=True, null=True)

    # Personal Data
    mobile_no = models.CharField("Mobile No.", max_length=20, blank=True, null=True, db_index=True)
    aadhaar_no = models.CharField("Aadhaar No", max_length=20, blank=True, null=True)
    aadhar_kyc = models.CharField("Aadhar KYC", max_length=200, blank=True, null=True)
    ekyc_status = models.CharField("ekyc status", max_length=20, blank=True, null=True)

    # Cadre Data
    cadres_role = models.CharField("Cadres Role", max_length=200, blank=True, null=True)
    primary_livelihood = models.CharField("Primary Livelihood", max_length=200, blank=True, null=True)
    secondary_livelihood = models.CharField("Secondary Livelihood", max_length=200, blank=True, null=True)
    tertiary_livelihood = models.CharField("Tertiary Livelihood", max_length=200, blank=True, null=True)

    # Unique IDs Data
    nrega_no = models.CharField("NREGA Job Card No", max_length=20, blank=True, null=True)
    pmay_id = models.CharField("PMAY-G ID", max_length=20, blank=True, null=True)
    secc_tin = models.CharField("SECC TIN", max_length=20, blank=True, null=True)
    nrlm_id = models.CharField("NRLM MIS ID", max_length=20, blank=True, null=True)
    state_id = models.CharField("STATE MIS ID", max_length=20, blank=True, null=True)
    ebk_id = models.CharField("eBK ID", max_length=20, blank=True, null=True)
    ebk_name = models.CharField("eBK Name", max_length=100, blank=True, null=True)
    ebk_mobile_no = models.CharField("eBK Mobile No.", max_length=20, blank=True, null=True, db_index=True)
    approval_status = models.CharField(max_length=50, blank=True, null=True)
    date_of_approval = models.DateField(blank=True, null=True)
    benef_status = models.CharField("Beneficiary Status", max_length=20, blank=True, null=True)
    inactive_date = models.DateField(blank=True, null=True)
    inactive_reason = models.CharField(max_length=200, blank=True, null=True)
    member_type = models.CharField("Migrated/Lokos", max_length=50, blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Beneficiary"
        verbose_name_plural = "Beneficiaries"
        ordering = ["id"]
        indexes = [
            models.Index(fields=['mobile_no']),
            models.Index(fields=['aadhaar_no']),
        ]

    def __str__(self):
        return f"{self.member_name or self.member_code or 'Beneficiary'} ({self.mobile_no or 'N/A'})"


# -------------------------
# MasterTrainer
# -------------------------
class MasterTrainer(models.Model):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='master_trainer',
        help_text="Optional link to User account for self-service login"
    )

    # Geographical Data
    state = models.CharField(max_length=150, blank=True, null=True, db_index=True)
    district = models.ForeignKey(
        District,
        on_delete=models.SET_NULL,
        related_name='trainer_district',
        null=True, blank=True,
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.SET_NULL,
        related_name='trainer_block',
        null=True, blank=True,
    )
    gram_panchayat = models.ForeignKey(
            Panchayat,
            on_delete=models.SET_NULL,
            related_name='trainer_gp',
            null=True, blank=True,
        )
    village = models.ForeignKey(
        Village,
        on_delete=models.SET_NULL,
        related_name='trainer_village',
        null=True, blank=True,
    )
    
    id = models.AutoField(primary_key=True)
    full_name = models.CharField(max_length=200)
    profile_picture = models.ImageField(upload_to='trainer_pfps/', blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    mobile_no = models.CharField("Mobile No.", max_length=20, blank=True, null=True, db_index=True)
    aadhaar_no = models.CharField("Aadhaar No", max_length=20, blank=True, null=True)
    empanel_district = models.CharField("Empanel District", max_length=255, blank=True, null=True)
    social_category = models.CharField("Social Category", max_length=50, blank=True, null=True)
    gender = models.CharField(max_length=20, blank=True, null=True)
    education = models.CharField(max_length=200, blank=True, null=True)
    marital_status = models.CharField(max_length=50, blank=True, null=True)
    parent_or_spouse_name = models.CharField("Father/Mother/Spouse Name", max_length=200, blank=True, null=True)

    skills = models.TextField("Skills / Thematic Sectors", blank=True, null=True)
    thematic_expert_recommendation = models.CharField(max_length=255, blank=True, null=True)
    success_rate = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    any_other_tots = models.TextField(blank=True, null=True)
    other_achievements = models.TextField(blank=True, null=True)
    recommended_tots_by_dmmu = models.TextField(blank=True, null=True)
    success_story_publications = models.TextField(blank=True, null=True)

    bank_account_number = models.CharField("Account Number", max_length=64, blank=True, null=True)
    ifsc = models.CharField("IFSC", max_length=32, blank=True, null=True)
    branch_name = models.CharField("Branch Name", max_length=200, blank=True, null=True)
    bank_name = models.CharField("Bank Name", max_length=200, blank=True, null=True)

    DESIGNATION_CHOICES = [
        ('BRP', 'BRP'),
        ('DRP', 'DRP'),
        ('SRP', 'SRP'),
    ]
    designation = models.CharField("Designation", max_length=3, choices=DESIGNATION_CHOICES, blank=True, null=True, db_index=True)

    CANONICAL_THEMES = [
        ('Farm LH', 'Farm LH'),
        ('FNHW', 'FNHW'),
        ('M&E', 'M&E'),
        ('MCLF', 'MCLF'),
        ('MF&FI', 'MF&FI'),
        ('Non Farm', 'Non Farm'),
        ('NONFARM LH', 'NONFARM LH'),
        ('SISD', 'SISD'),
        ('SMCB', 'SMCB'),
        ('TNCB', 'TNCB'),
        ('Fishery', 'Fishery')
    ]
    theme = models.CharField(
        "Theme",
        max_length=50,
        choices=CANONICAL_THEMES,
        blank=True,
        null=True,
        db_index=True,
        help_text="Canonical theme mapped from CSV 'theme' column"
    )    

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Master Trainer"
        verbose_name_plural = "Master Trainers"
        indexes = [
            models.Index(fields=['full_name']),
            models.Index(fields=['designation']),
        ]

    def __str__(self):
        return self.full_name


# ---------------------------------
# TrainingPartner
# ---------------------------------
class TrainingPartner(models.Model):
    id = models.AutoField(primary_key=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='training_partner_profile'
    )

    name = models.CharField(max_length=255)
    contact_person = models.CharField(max_length=200, blank=True, null=True)
    contact_mobile = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    bank_name = models.CharField("Bank Name", max_length=255, blank=True, null=True)
    bank_branch = models.CharField("Branch", max_length=255, blank=True, null=True)
    bank_ifsc = models.CharField("IFSC / Routing", max_length=32, blank=True, null=True)
    bank_account_number = models.CharField("Account Number", max_length=64, blank=True, null=True)

    tpm_registration_no = models.CharField("Registration No (TPM/Org)", max_length=128, blank=True, null=True)
    mou_form = models.FileField("Signed MoU (PDF)", upload_to='partner_mous/', blank=True, null=True)

    signed_report_file = models.FileField(upload_to='partner_signed_reports/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Training Partner"
        verbose_name_plural = "Training Partners"
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.name} ({self.tpm_registration_no or 'N/A'})"


# ---------------------------------
# TrainingPartnerCentre
# ---------------------------------
class TrainingPartnerCentre(models.Model):
    id = models.AutoField(primary_key=True)
    partner = models.ForeignKey('TrainingPartner', on_delete=models.CASCADE, related_name='centres')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    # Basic Details
    serial_number = models.IntegerField(blank=True, null=True)
    district = models.ForeignKey(
        'District',
        on_delete=models.SET_NULL,
        related_name='trainingpartner_centre_district',
        null=True, blank=True,
    )
    centre_coord_name = models.CharField("Coordinator Name", max_length=120, blank=True, null=True)
    centre_coord_mob_number = models.CharField("Coordinator Mobile", max_length=30, blank=True, null=True)

    venue_name = models.CharField("Venue Name", max_length=120, blank=True, null=True)
    venue_address = models.CharField("Venue Address", max_length=500, blank=True, null=True)

    # Accommodation details (rooms moved to separate model)
    # Training Hall
    training_hall_count = models.IntegerField("Number of Training Halls", blank=True, null=True)
    training_hall_capacity = models.IntegerField("Training Hall Capacity (max 35 participants/batch)", blank=True, null=True)

    # Facilities
    security_arrangements = models.CharField("Security Arrangements", max_length=255, blank=True, null=True)
    toilets_bathrooms = models.IntegerField("Total Toilets/Bathrooms", blank=True, null=True)
    power_water_facility = models.CharField("Power/Water Availability", max_length=255, blank=True, null=True)
    medical_kit = models.BooleanField("Medical Kit Available", default=False)
    centre_type = models.CharField("Centre Type (Private/Govt/Lodge/Rented)", max_length=255, blank=True, null=True)
    open_space = models.BooleanField("Open Space for Group Activity", default=False)
    field_visit_facility = models.BooleanField("Field Visit Facility", default=False)
    transport_facility = models.BooleanField("Transport Facility", default=False)
    dining_facility = models.BooleanField("Dining Room Facility", default=False)
    other_details = models.TextField("Other Details", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Training Partner Centre"
        verbose_name_plural = "Training Partner Centres"
        indexes = [
            models.Index(fields=['partner', 'district']),
        ]

    def __str__(self):
        return f"{self.partner.name} - {self.venue_name or 'Unnamed Centre'}"


# -------------------------
# TrainingPartnerCentreRooms
# -------------------------
class TrainingPartnerCentreRooms(models.Model):
    id = models.AutoField(primary_key=True)
    centre = models.ForeignKey(TrainingPartnerCentre, on_delete=models.CASCADE, related_name='rooms')
    room_name = models.CharField("Room Name/Number", max_length=100, blank=True, null=True)
    room_capacity = models.IntegerField("Room Capacity (max 20 per room)", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Training Partner Centre Room"
        verbose_name_plural = "Training Partner Centre Rooms"

    def __str__(self):
        return f"{self.centre.venue_name or 'Centre'} - {self.room_name or 'Room'}"


# -------------------------
# TrainingPartnerSubmission
# -------------------------
class TrainingPartnerSubmission(models.Model):
    CATEGORY_CHOICES = [
        ('FOODING', 'Fooding'),
        ('TOILET', 'Toilet'),
        ('CENTRE_FRONT', 'Centre (front)'),
        ('HOSTEL', 'Hostel'),
        ('CCTV_SECURITY', 'CCTV SECURITY'),
        ('ACTIVITY_HALL', 'Activity Hall'),
        ('OTHER', 'Other'),
    ]

    id = models.AutoField(primary_key=True)
    centre = models.ForeignKey(TrainingPartnerCentre, on_delete=models.CASCADE, related_name='submissions', blank=True, null=True)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, default='OTHER')
    file = models.FileField(upload_to='partner_photos_or_pdfs/', blank=True, null=True,
                            help_text='Upload image (jpeg/png) or a PDF containing required photos.')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_on = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Training Partner Submission"
        verbose_name_plural = "Training Partner Submissions"
        indexes = [
            models.Index(fields=['centre', 'category']),
        ]

    def __str__(self):
        centre_name = getattr(self.centre, 'venue_name', str(self.centre))
        return f"{centre_name} - {self.category} ({self.uploaded_on:%Y-%m-%d})"

# -------------------------
# Training Request
# -------------------------
class TrainingRequest(models.Model):
    id = models.AutoField(primary_key=True)
    training_plan = models.ForeignKey(TrainingPlan, on_delete=models.PROTECT, related_name='training_requests')

    # beneficiaries chosen by BMMU/DMMU/SMMU when making the request
    # this uses through model below (BeneficiaryBatchRegistration) which links a beneficiary -> training request
    beneficiaries = models.ManyToManyField(Beneficiary, blank=True, related_name='benefs_for_training', through='BeneficiaryBatchRegistration')

    trainers = models.ManyToManyField(MasterTrainer, blank=True, related_name='trainers_for_training', through='TrainerBatchRegistration')
    
    TRAINING_TYPE_CHOICES = [
        ('BENEFICIARY', 'Beneficiary'),
        ('TRAINER', 'Master Trainer'),
    ]
    training_type = models.CharField("Applicable For", max_length=20, choices=TRAINING_TYPE_CHOICES)    
    
    partner = models.ForeignKey(TrainingPartner, on_delete=models.SET_NULL, null=True, blank=True, related_name='training_requests')

    LEVEL_CHOICES = [
        ('BLOCK', 'Block'),
        ('DISTRICT', 'District'),
        ('STATE', 'State')
    ]
    level = models.CharField(max_length=50, choices=LEVEL_CHOICES, default='BLOCK', blank=True, null=True)

    STATUS_CHOICES = [
        ('BATCHING', 'Batching Phase'),
        ('PENDING', 'Pending Approval'),
        ('ONGOING', 'Ongoing'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='BATCHING')
    rejection_reason = models.CharField(max_length=500, blank=True, null=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_training_requests')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Training"
        verbose_name_plural = "Trainings"
        indexes = [
            models.Index(fields=['partner', 'status']),
            models.Index(fields=['training_plan']),
        ]

    def __str__(self):
        return f"{self.id or f'TrainingRequest-{self.id}'} - {self.training_plan.training_name}"


# -------------------------
# Batch
# -------------------------
class Batch(models.Model):
    id = models.AutoField(primary_key=True)
    request = models.ForeignKey(TrainingRequest, on_delete=models.CASCADE, related_name='request_of_batch', blank=True, null=True)
    trainers = models.ManyToManyField(MasterTrainer, blank=True, related_name='batches', through='TrainerBatchParticipation')
    centre = models.ForeignKey(TrainingPartnerCentre, on_delete=models.SET_NULL, null=True, blank=True, related_name='centre_of_batch')

    # autogenerated code field (see save())
    code = models.CharField(max_length=255, unique=True, blank=True, null=True)

    STATUS_CHOICES = [
        ('PENDING', 'Pending Approval'),
        ('ONGOING', 'Ongoing'),
        ('SCHEDULED', 'SCHEDULED'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Batch"
        verbose_name_plural = "Batches"
        indexes = [
            models.Index(fields=['request', 'centre']),
        ]

    def __str__(self):
        """
        Safe stringification: never assume request or training_plan exist.
        """
        code_part = self.code or f"Batch-{self.id}"
        try:
            if self.request and getattr(self.request, "training_plan", None):
                tp_name = getattr(self.request.training_plan, "training_name", None)
                if tp_name:
                    return f"{code_part} - {tp_name}"
        except Exception:
            # defensive fallback if any unexpected attribute access fails
            pass
        # last fallback: show request id if available, else just code
        try:
            req_part = f"Request-{self.request.id}" if self.request and getattr(self.request, "id", None) else ""
        except Exception:
            req_part = ""
        return f"{code_part}" + (f" - {req_part}" if req_part else "")

    def generate_code_parts(self):
        """
        Build components for the batch code:
        [training_theme]-[location_name]-[state id]-[training-type]-[batch id]
        - training_theme: training_plan.theme or training_name slugified
        - location_name: derived from who created the TrainingRequest (BMMU/DMMU/SMMU) using assignment tables,
                         or from the first beneficiary's block/district as a fallback.
        - state id: attempt to read from district.state_id or beneficiary.state_id
        - training-type: request.training_plan.type_of_training (like RES/NON RES/OTHER). We'll slugify it.
        """
        training_theme = self.request.training_plan.theme or self.request.training_plan.training_name
        theme_part = slugify(str(training_theme))[:80]  # keep compact

        # Determine location_name and state_id
        location_name = 'unknown'
        state_id_part = 'unknown'

        # 1) Prefer assignments based on who created the request
        creator = self.request.created_by
        if creator:
            # if BMMU, try to get BmmuBlockAssignment for that user
            try:
                bmmu_assign = getattr(creator, 'bmmu_block_assignment', None)
                if bmmu_assign and bmmu_assign.block and self.request.level == 'BLOCK':
                    location_name = slugify(str(bmmu_assign.block.block_name_en or bmmu_assign.block.block_id))[:80]
                    # attempt to get state_id from block
                    state_id_part = str(bmmu_assign.block.state_id) if getattr(bmmu_assign.block, 'state_id', None) else state_id_part
            except Exception:
                pass

            # if DMMU, try to get DmmuDistrictAssignment
            try:
                dmmu_assign = getattr(creator, 'dmmu_district_assignment', None)
                if dmmu_assign and dmmu_assign.district and self.request.level == 'DISTRICT':
                    location_name = slugify(str(dmmu_assign.district.district_name_en or dmmu_assign.district.district_id))[:80]
                    state_id_part = str(dmmu_assign.district.state_id) if getattr(dmmu_assign.district, 'state_id', None) else state_id_part
            except Exception:
                pass

            # if SMMU (state level), fallback to creator username or 'state'
            try:
                if getattr(creator, 'role', None) == 'smmu' or self.request.level == 'STATE':
                    # No explicit state model — use district from first beneficiary to determine state
                    location_name = slugify(getattr(creator, 'username', 'state'))[:80]
            except Exception:
                pass

        # 2) If nothing from assignments, try first beneficiary
        if (location_name == 'unknown') and self.request.beneficiaries.exists():
            first_benef = self.request.beneficiaries.first()
            # try block name
            if getattr(first_benef, 'block', None):
                try:
                    # if block is FK, we may attempt to fetch Block model's name
                    if hasattr(first_benef.block, 'block_name_en'):
                        location_name = slugify(str(first_benef.block.block_name_en or first_benef.block.block_id))[:80]
                        state_id_part = str(getattr(first_benef.block, 'state_id', state_id_part))
                except Exception:
                    pass
            # try district name
            if location_name == 'unknown' and getattr(first_benef, 'district', None):
                try:
                    location_name = slugify(str(first_benef.district.district_name_en or first_benef.district.district_id))[:80]
                    state_id_part = str(getattr(first_benef.district, 'state_id', state_id_part))
                except Exception:
                    pass
            # try beneficiary.state field
            if state_id_part == 'unknown' and getattr(first_benef, 'state_id', None):
                state_id_part = str(first_benef.state_id)

        # sanitize training-type
        training_type = slugify(str(self.request.training_plan.type_of_training or 'OTHER'))[:40]

        return theme_part, location_name, state_id_part, training_type

    def save(self, *args, **kwargs):
        today = timezone.localdate()

        # Auto-update status based on start_date
        if self.start_date == today and self.status != 'ONGOING':
            self.status = 'ONGOING'

        # Save first so self.id exists, required for final part of code
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # If code empty, generate it (ensures batch.id is available)
        if not self.code:
            theme_part, location_name, state_id_part, training_type = self.generate_code_parts()
            # last part is batch id
            batch_id_part = str(self.id)
            code = f"{theme_part}-{location_name}-{state_id_part}-{training_type}-{batch_id_part}"
            # make compact and max length protection
            code = code.replace(' ', '-')
            # ensure uniqueness by appending id (already included), and truncate to 255
            code = code[:255]
            # update
            Batch.objects.filter(pk=self.pk).update(code=code)
            # refresh instance attribute
            self.code = code


# -------------------------
# BeneficiaryBatchRegistration (join model used in TrainingRequest)
# -------------------------
class BeneficiaryBatchRegistration(models.Model):
    """
    Join model for Beneficiary ↔ Training Request.
    Stores which beneficiaries were attached to a TrainingRequest (and later mapped to Batches).
    """
    id = models.AutoField(primary_key=True)
    beneficiary = models.ForeignKey(Beneficiary, on_delete=models.CASCADE, related_name='benefs_registrations')
    training = models.ForeignKey(TrainingRequest, on_delete=models.CASCADE, related_name='beneficiary_registrations', blank=True, null=True)
    registered_on = models.DateTimeField(auto_now_add=True)
    attended = models.BooleanField(default=False)
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('beneficiary', 'training')
        verbose_name = "Beneficiary Batch Registration"
        verbose_name_plural = "Beneficiary Batch Registrations"

    def __str__(self):
        """
        Safe display for admin and logs: handle missing beneficiary or training gracefully.
        """
        beneficiary_label = "Beneficiary"
        try:
            if self.beneficiary:
                beneficiary_label = self.beneficiary.member_name or self.beneficiary.member_code or "Beneficiary"
        except Exception:
            beneficiary_label = "Beneficiary"

        training_label = ""
        try:
            if self.training:
                training_label = f" - {self.training.code or f'ID-{self.training.id}'}"
        except Exception:
            training_label = ""

        return f"{beneficiary_label}{training_label}"

# -------------------------
# BatchBeneficiary
# -------------------------
class BatchBeneficiary(models.Model):
    """
    Join model for Beneficiary ↔ Batch.
    Stores which beneficiaries were attached to a Batch
    """
    id = models.AutoField(primary_key=True)
    beneficiary = models.ForeignKey(Beneficiary, on_delete=models.CASCADE, related_name='benefs_batch_participation')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='batch_beneficiaries', blank=True, null=True)
    registered_on = models.DateTimeField(auto_now_add=True)
    attended = models.BooleanField(default=False)
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('beneficiary', 'batch')
        verbose_name = "Beneficiary Batch Participation"
        verbose_name_plural = "Beneficiary Batch Participation"

    def __str__(self):
        """
        Safe display for admin and logs: handle missing beneficiary or training gracefully.
        """
        beneficiary_label = "Beneficiary"
        try:
            if self.beneficiary:
                beneficiary_label = self.beneficiary.member_name or self.beneficiary.member_code or "Beneficiary"
        except Exception:
            beneficiary_label = "Beneficiary"

        batch_label = ""
        try:
            if self.batch:
                batch_label = f" - {self.batch.code or f'ID-{self.batch.id}'}"
        except Exception:
            batch_label = ""

        return f"{beneficiary_label}{batch_label}"


# -------------------------
# TrainerBatchParticipation
# -------------------------
class TrainerBatchParticipation(models.Model):
    id = models.AutoField(primary_key=True)
    trainer = models.ForeignKey(MasterTrainer, on_delete=models.CASCADE, related_name='trainerparticipations')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='trainerparticipations')
    participated = models.BooleanField(default=False)

    STATUS_CHOICES = [
        ('AVAILABLE', 'Available'),
        ('UNAVAILABLE', 'Unavailable'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE', blank=True, null=True)

    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('trainer', 'batch')
        verbose_name = "Trainer Batch Participation"
        verbose_name_plural = "Trainer Batch Participations"

    def __str__(self):
        """
        Safe display of trainer participation; don't assume trainer or batch exist or have names.
        """
        trainer_name = getattr(self.trainer, "full_name", None) or f"Trainer-{getattr(self.trainer, 'id', '')}"
        batch_code = ""
        try:
            if self.batch:
                batch_code = getattr(self.batch, "code", None) or (f"Batch-{getattr(self.batch, 'id', '')}" if getattr(self.batch, 'id', None) else "")
        except Exception:
            batch_code = ""
        status = self.status or ""
        return f"{trainer_name}" + (f" - {batch_code}" if batch_code else "") + (f" [{status}]" if status else "")

# -------------------------
# TrainerBatchRegistration (join model used in TrainingRequest)
# -------------------------
class TrainerBatchRegistration(models.Model):
    """
    Join model for Master Trainer ↔ Training Request.
    Stores which trainers were attached to a TrainingRequest (and later mapped to Batches).
    """
    id = models.AutoField(primary_key=True)
    trainer = models.ForeignKey(MasterTrainer, on_delete=models.CASCADE, related_name='trainer_registrations')
    training = models.ForeignKey(TrainingRequest, on_delete=models.CASCADE, related_name='trainer_request_for_training')
    registered_on = models.DateTimeField(auto_now_add=True)
    attended = models.BooleanField(default=False)
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('trainer', 'training')
        verbose_name = "Trainer Batch Registration"
        verbose_name_plural = "Trainer Batch Registrations"

    def __str__(self):
        return f"{self.trainer.full_name or self.trainer.id} - {self.training.code or self.training.id}"


# -------------------------
# ThemeExpertAssignment
# -------------------------
class ThemeExpertAssignment(models.Model):
    id = models.AutoField(primary_key=True)
    theme_name = models.CharField("Theme name", max_length=255, db_index=True)
    expert = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='theme_assignments')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('theme_name', 'expert')
        verbose_name = "Theme Expert Assignment"
        verbose_name_plural = "Theme Expert Assignments"

    def __str__(self):
        return f"{self.theme_name} -> {self.expert}"


# -------------------------
# MasterTrainerAssignment
# -------------------------
class MasterTrainerAssignment(models.Model):
    id = models.AutoField(primary_key=True)
    trainer = models.ForeignKey(MasterTrainer, on_delete=models.CASCADE, related_name='assignments')
    training_plan = models.ForeignKey(TrainingPlan, on_delete=models.CASCADE, related_name='trainer_assignments')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    assigned_on = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('trainer', 'training_plan')
        verbose_name = "Master Trainer Assignment"
        verbose_name_plural = "Master Trainer Assignments"

    def __str__(self):
        return f"{self.trainer.full_name} -> {self.training_plan.training_name}"

# -------------------------
# MasterTrainerCertificate
# -------------------------
class MasterTrainerCertificate(models.Model):
    id = models.AutoField(primary_key=True)
    trainer = models.ForeignKey(
        MasterTrainer, on_delete=models.CASCADE, related_name='certificates'
    )
    certificate_number = models.CharField("Certificate Number", max_length=255, blank=True, null=True)
    training_module = models.ForeignKey(
        TrainingPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='certificates',
        help_text="Link to the TrainingPlan record for which this certificate was issued (nullable)."
    )
    certificate_file = models.FileField(
        upload_to='trainer_certificates/', blank=True, null=True,
        help_text="Upload certificate image/PDF (jpeg, png, pdf)."
    )
    issued_on = models.DateField("Issued on", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Master Trainer Certificate"
        verbose_name_plural = "Master Trainer Certificates"
        ordering = ('-created_at',)

    def __str__(self):
        if self.certificate_number:
            return f"{self.trainer.full_name} - {self.certificate_number}"
        return f"{self.trainer.full_name} - {self.training_module.training_name if self.training_module else 'Certificate'}"


# -------------------------
# MasterTrainerExpertise
# -------------------------
class MasterTrainerExpertise(models.Model):
    id = models.AutoField(primary_key=True)
    trainer = models.ForeignKey(
        MasterTrainer,
        on_delete=models.CASCADE,
        related_name='expertise'
    )
    training_plan = models.ForeignKey(
        TrainingPlan,
        on_delete=models.CASCADE,
        related_name='recommended_trainers'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('trainer', 'training_plan')
        verbose_name = "Master Trainer Expertise"
        verbose_name_plural = "Master Trainer Expertises"
        indexes = [
            models.Index(fields=['trainer', 'training_plan']),
        ]

    def __str__(self):
        return f"{self.trainer.full_name} -> {self.training_plan.training_name}"


class TrainingPartnerTargets(models.Model):
    TARGET_TYPE_CHOICES = [
        ("DISTRICT", "District"),
        ("MODULE", "Module"),
        ("THEME", "Theme"),
    ]

    id = models.AutoField(primary_key=True)
    partner = models.ForeignKey(TrainingPartner, on_delete=models.CASCADE, related_name='targets')
    allocated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='allocated_targets')

    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES)

    # Module (training plan) FK — required for MODULE targets
    training_plan = models.ForeignKey(TrainingPlan, on_delete=models.CASCADE,
                                      related_name='partner_targets', null=True, blank=True)

    # District FK — required for DISTRICT targets; also required for MODULE targets per your flow
    district = models.ForeignKey(District, on_delete=models.CASCADE,
                                 related_name='tp_district_targets', null=True, blank=True)

    # Theme string (for THEME targets or inferred from training_plan)
    theme = models.CharField(max_length=200, blank=True, null=True)

    target_count = models.PositiveIntegerField("Target count (batches)", default=0)
    notes = models.TextField("Notes / rationale", blank=True, null=True)
    financial_year = models.CharField("Financial year", max_length=9, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    allocated_on = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Training Partner Target"
        verbose_name_plural = "Training Partner Targets"
        indexes = [
            models.Index(fields=['partner', 'target_type']),
            models.Index(fields=['financial_year']),
        ]

    def clean(self):
        # validate basic presence
        if not self.partner:
            raise ValidationError("partner is required.")
        if not self.financial_year:
            raise ValidationError("financial_year is required (e.g. '2023-24').")
        if self.target_count is None:
            raise ValidationError("target_count is required.")

        # rules by target_type
        if self.target_type == "DISTRICT":
            # require district, disallow training_plan
            if not self.district:
                raise ValidationError("district must be set for DISTRICT targets.")
            # training_plan should not be required — but protect accidental module link
            # optional: enforce training_plan is None
        elif self.target_type == "MODULE":
            # require both training_plan and district per your described flow
            if not self.training_plan:
                raise ValidationError("training_plan must be set for MODULE targets.")
            if not self.district:
                raise ValidationError("district must be set for MODULE targets.")
        elif self.target_type == "THEME":
            # no district required; theme must be present either here or via training_plan.theme
            if not (self.theme or (self.training_plan and getattr(self.training_plan, 'theme', None))):
                raise ValidationError("theme must be present for THEME targets (inferred from logged-in SMMU or training_plan).")

        # simple FY format sanity (very permissive)
        if len(self.financial_year) < 5:
            raise ValidationError("financial_year looks invalid (expected e.g. '2023-24').")

    def save(self, *args, **kwargs):
        # populate theme automatically when possible
        if not self.theme and self.training_plan and getattr(self.training_plan, 'theme', None):
            self.theme = self.training_plan.theme
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        scope = self.target_type
        if self.target_type == "MODULE":
            scope += f" - {getattr(self.training_plan, 'training_name', self.training_plan_id)} / {getattr(self.district, 'district_name_en', self.district_id)}"
        elif self.target_type == "DISTRICT":
            scope += f" - {getattr(self.district, 'district_name_en', self.district_id)}"
        else:
            scope += f" - {self.theme or 'N/A'}"
        return f"{self.partner.name} — {scope} = {self.target_count} ({self.financial_year})"
    

# -------------------------
# TrainingPartnerBatch
# -------------------------
class TrainingPartnerBatch(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Approval'),
        ('ONGOING', 'Ongoing'),
        ('SCHEDULED', 'SCHEDULED'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected'),
    ]

    id = models.AutoField(primary_key=True)
    partner = models.ForeignKey(TrainingPartner, on_delete=models.CASCADE, related_name='partnerbatch')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='partnerbatch')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    assigned_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('partner', 'batch')
        verbose_name = "Training Partner Batch"
        verbose_name_plural = "Training Partner Batches"

    def __str__(self):
        return f"{self.partner.name} - {self.batch.code or self.batch.id} ({self.status})"


# Which block has which BMMU?
class BmmuBlockAssignment(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bmmu_block_assignment'
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        related_name='bmmu_user_assignments'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "BMMU Block Assignment"
        verbose_name_plural = "BMMU Block Assignments"
        unique_together = ('user', 'block')

    def __str__(self):
        return f"{self.user.username} -> {self.block.block_name_en}"


# Which district has which DMMU?
class DmmuDistrictAssignment(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='dmmu_district_assignment'
    )
    district = models.ForeignKey(
        District,
        on_delete=models.CASCADE,
        related_name='dmmu_user_assignments'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "DMMU District Assignment"
        verbose_name_plural = "DMMU District Assignments"
        unique_together = ('user', 'district')

    def __str__(self):
        return f"{self.user.username} -> {self.district.district_name_en}"


class SHG(models.Model):
    id = models.AutoField(primary_key=True)

    state = models.CharField(max_length=150, blank=True, null=True, db_index=True)
    district = models.ForeignKey(
        'District',
        on_delete=models.SET_NULL,
        related_name='shgs',
        null=True, blank=True,
    )
    block = models.ForeignKey(
        'Block',
        on_delete=models.SET_NULL,
        related_name='shgs',
        null=True, blank=True,
    )

    shg_code = models.CharField("SHG Code", max_length=100, blank=False, null=False, db_index=True, unique=True)
    shg_name = models.CharField("SHG Name", max_length=200, blank=True, null=True)
    date_of_formation = models.DateField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SHG"
        verbose_name_plural = "SHGs"
        ordering = ["shg_code"]
        indexes = [
            models.Index(fields=['shg_code']),
            models.Index(fields=['state']),
        ]

    def __str__(self):
        return f"{self.shg_name or self.shg_code} ({self.shg_code})"
    
# ---------------------------------
# Batch eKYC Verification
# ---------------------------------
class BatchEkycVerification(models.Model):
    batch = models.ForeignKey('Batch', on_delete=models.CASCADE, related_name='ekyc_verifications')
    participant_id = models.PositiveIntegerField()  # works for both trainers & beneficiaries
    participant_role = models.CharField(max_length=20, choices=[('trainer', 'Trainer'), ('beneficiary', 'Beneficiary')])
    ekyc_status = models.CharField(
        max_length=20,
        choices=[('PENDING', 'Pending'), ('VERIFIED', 'Verified'), ('FAILED', 'Failed')],
        default='PENDING'
    )
    ekyc_document = models.FileField(upload_to='ekyc_documents/', blank=True, null=True)
    verified_on = models.DateTimeField(blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Batch eKYC Verification"
        verbose_name_plural = "Batch eKYC Verifications"
        unique_together = ('batch', 'participant_id', 'participant_role')

    def __str__(self):
        return f"{self.batch.code} - {self.participant_role} {self.participant_id} ({self.ekyc_status})"


# ---------------------------------
# Batch Attendance (Day-wise Attendance)
# ---------------------------------
class BatchAttendance(models.Model):
    batch = models.ForeignKey('Batch', on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField()
    csv_upload = models.FileField(upload_to='attendance_csvs/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Batch Attendance"
        verbose_name_plural = "Batch Attendances"
        unique_together = ('batch', 'date')

    def __str__(self):
        return f"{self.batch.code} - {self.date}"


# ---------------------------------
# Participant-wise Attendance (Trainers + Beneficiaries)
# ---------------------------------
class ParticipantAttendance(models.Model):
    attendance = models.ForeignKey(BatchAttendance, on_delete=models.CASCADE, related_name='participant_records')
    participant_id = models.PositiveIntegerField()
    participant_name = models.CharField(max_length=200)
    participant_role = models.CharField(max_length=50, choices=[('trainer', 'Trainer'), ('beneficiary', 'Beneficiary')])
    present = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.participant_name} - {self.attendance.date}"