# models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

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

    # mandal FK -> A mandal can have many districts (District belongs to one Mandal)
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

    # relations
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name='blocks', db_index=True)

    # optional convenience column if CSV contains district_name_en in block rows
    district_name_en = models.CharField(max_length=255, blank=True, null=True)

    # aspirational (True/False)
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

    # relations
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

    # relations
    panchayat = models.ForeignKey(Panchayat, on_delete=models.CASCADE, related_name='villages', db_index=True)
    # duplicate parent ids for convenience / query speed
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
# Beneficiary
# -------------------------
class Beneficiary(models.Model):
    id = models.AutoField(primary_key=True)

    # Geographical Data
    state = models.CharField(max_length=150, blank=True, null=True, db_index=True)
    district = models.ForeignKey(
        District,
        on_delete=models.CASCADE,
        related_name='beneficiary_district',
        null=True, blank=True,
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
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

    # Primary Fields
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

    # extra fields that admin/forms expect
    skills = models.TextField("Skills / Thematic Sectors", blank=True, null=True)
    thematic_expert_recommendation = models.CharField(max_length=255, blank=True, null=True)
    success_rate = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    any_other_tots = models.TextField(blank=True, null=True)
    other_achievements = models.TextField(blank=True, null=True)
    recommended_tots_by_dmmu = models.TextField(blank=True, null=True)
    success_story_publications = models.TextField(blank=True, null=True)

    # Banking Details
    bank_account_number = models.CharField("Account Number", max_length=64, blank=True, null=True)
    ifsc = models.CharField("IFSC", max_length=32, blank=True, null=True)
    branch_name = models.CharField("Branch Name", max_length=200, blank=True, null=True)
    bank_name = models.CharField("Bank Name", max_length=200, blank=True, null=True)

    # Secondary fields
    DESIGNATION_CHOICES = [
        ('DRP', 'DRP'),
        ('SRP', 'SRP'),
    ]
    designation = models.CharField("Designation", max_length=3, choices=DESIGNATION_CHOICES, blank=True, null=True, db_index=True)
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


# -------------------------
# TrainingPartner
# -------------------------
class TrainingPartner(models.Model):
    id = models.AutoField(primary_key=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='training_partner_profile'
    )

    # Standardized field names used across admin/resources/forms
    name = models.CharField(max_length=255)
    contact_person = models.CharField(max_length=200, blank=True, null=True)
    contact_mobile = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    # optional additional location field referenced in admin
    center_location = models.CharField(max_length=255, blank=True, null=True)

    # Banking Details
    bank_name = models.CharField("Bank Name", max_length=255, blank=True, null=True)
    bank_branch = models.CharField("Branch", max_length=255, blank=True, null=True)
    bank_ifsc = models.CharField("IFSC / Routing", max_length=32, blank=True, null=True)
    bank_account_number = models.CharField("Account Number", max_length=64, blank=True, null=True)

    tpm_registration_no = models.CharField("Registration No (TPM/Org)", max_length=128, blank=True, null=True)
    mou_form = models.FileField("Signed MoU (PDF)", upload_to='partner_mous/', blank=True, null=True)

    # fields referenced by admin/resources that were missing previously
    certifications = models.TextField(blank=True, null=True)
    signed_report_file = models.FileField(upload_to='partner_signed_reports/', blank=True, null=True)
    photographs_submission = models.TextField(blank=True, null=True, help_text="Summary / meta about photographs")
    targets_allocated = models.TextField(blank=True, null=True, help_text="Optional summary of targets allocated")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Training Partner"
        verbose_name_plural = "Training Partners"
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.name} ({self.tpm_registration_no or 'N/A'})"


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

    # fields referenced by admin/resources
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
# Batch
# -------------------------
class Batch(models.Model):
    id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=100, unique=True, blank=True, null=True)
    training_plan = models.ForeignKey(TrainingPlan, on_delete=models.PROTECT, related_name='batches')
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    partner = models.ForeignKey(TrainingPartner, on_delete=models.SET_NULL, null=True, blank=True, related_name='batches')

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING', 'Pending Approval'),
        ('ONGOING', 'Ongoing'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    centre_proposed = models.CharField("Centre (proposed by partner)", max_length=255, blank=True, null=True)

    # submissions: many-to-many linking to TrainingPartnerSubmission (if you want photos per batch)
    submissions = models.ManyToManyField('TrainingPartnerSubmission', blank=True, related_name='batches')

    # Trainers and beneficiaries relation will remain ManyToMany for convenience,
    # but meaningful meta stored in join models via through.
    trainers = models.ManyToManyField(MasterTrainer, blank=True, related_name='batches', through='TrainerBatchParticipation')
    beneficiaries = models.ManyToManyField(Beneficiary, blank=True, related_name='batches', through='BeneficiaryBatchRegistration')

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_batches')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Batch"
        verbose_name_plural = "Batches"
        indexes = [
            models.Index(fields=['partner', 'status']),
            models.Index(fields=['training_plan']),
        ]

    def __str__(self):
        return f"{self.code or f'Batch-{self.id}'} - {self.training_plan.training_name}"


# -------------------------
# (Missing) BeneficiaryBatchRegistration (join model used in Batch)
# -------------------------
class BeneficiaryBatchRegistration(models.Model):
    """
    Join model for Beneficiary ↔ Batch registration. (Was referenced but not present.)
    """
    id = models.AutoField(primary_key=True)
    beneficiary = models.ForeignKey(Beneficiary, on_delete=models.CASCADE, related_name='registrations')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='beneficiary_registrations')
    registered_on = models.DateTimeField(auto_now_add=True)
    attended = models.BooleanField(default=False)
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('beneficiary', 'batch')
        verbose_name = "Beneficiary Batch Registration"
        verbose_name_plural = "Beneficiary Batch Registrations"

    def __str__(self):
        return f"{self.beneficiary.member_name or self.beneficiary.member_code} - {self.batch.code or self.batch.id}"


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
# TrainerBatchParticipation
# -------------------------
class TrainerBatchParticipation(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('ONGOING', 'Ongoing'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.AutoField(primary_key=True)
    trainer = models.ForeignKey(MasterTrainer, on_delete=models.CASCADE, related_name='trainerparticipations')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='trainerparticipations')
    participated = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('trainer', 'batch')
        verbose_name = "Trainer Batch Participation"
        verbose_name_plural = "Trainer Batch Participations"

    def __str__(self):
        return f"{self.trainer.full_name} - {self.batch.code or self.batch.id} [{self.status}]"


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


# -------------------------
# TrainingPartnerSubmission
# -------------------------
class TrainingPartnerSubmission(models.Model):
    CATEGORY_CHOICES = [
        ('FOODING', 'Fooding'),
        ('TOILET', 'Toilet'),
        ('CENTRE_FRONT', 'Centre (front)'),
        ('HOSTEL', 'Hostel'),
        ('ACTIVITY_HALL', 'Activity Hall'),
        ('OTHER', 'Other'),
    ]

    id = models.AutoField(primary_key=True)
    partner = models.ForeignKey(TrainingPartner, on_delete=models.CASCADE, related_name='submissions')
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
            models.Index(fields=['partner', 'category']),
        ]

    def __str__(self):
        partner_name = getattr(self.partner, 'name', str(self.partner))
        return f"{partner_name} - {self.category} ({self.uploaded_on:%Y-%m-%d})"


# -------------------------
# TrainingPartnerTargets
# -------------------------
class TrainingPartnerTargets(models.Model):
    TARGET_TYPE_CHOICES = [
        ("DISTRICT", "District"),
        ("MODULE", "Module"),
        ("THEME", "Theme"),
    ]

    id = models.AutoField(primary_key=True)
    partner = models.ForeignKey(TrainingPartner, on_delete=models.CASCADE, related_name='targets')
    allocated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='allocated_targets')
    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES)
    target_key = models.CharField("Target key (District/Module/Theme)", max_length=255)
    target_count = models.PositiveIntegerField("Target count", blank=True, null=True)
    notes = models.TextField("Notes / rationale", blank=True, null=True)
    evidence_file = models.FileField("Evidence (PDF/JPG)", upload_to='target_evidence/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Training Partner Target"
        verbose_name_plural = "Training Partner Targets"
        indexes = [
            models.Index(fields=['partner', 'target_type']),
        ]

    def __str__(self):
        return f"{self.partner.name} - {self.target_type}:{self.target_key} = {self.target_count or 'N/A'}"


# -------------------------
# TrainingPlanPartner
# -------------------------
class TrainingPlanPartner(models.Model):
    id = models.AutoField(primary_key=True)
    training_plan = models.ForeignKey(TrainingPlan, on_delete=models.CASCADE, related_name='plan_partners')
    partner = models.ForeignKey(TrainingPartner, on_delete=models.CASCADE, related_name='plan_partners')
    drp_payments = models.DecimalField("DRP Payments / Estimated Cost", max_digits=12, decimal_places=2, blank=True, null=True)
    assigned_on = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = ('training_plan', 'partner')
        verbose_name = "Training Plan Partner"
        verbose_name_plural = "Training Plan Partners"

    def __str__(self):
        return f"{self.training_plan.training_name} <-> {self.partner.name} ({self.drp_payments or 'N/A'})"


# -------------------------
# TrainingPartnerAssignment
# -------------------------
class TrainingPartnerAssignment(models.Model):
    id = models.AutoField(primary_key=True)
    partner = models.ForeignKey(
        TrainingPartner,
        on_delete=models.CASCADE,
        related_name='assignments'
    )
    theme = models.CharField(max_length=255, help_text="Theme name (text)")
    block = models.CharField(max_length=255, help_text="Block name / identifier")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('theme', 'block')
        verbose_name = "Training Partner Assignment"
        verbose_name_plural = "Training Partner Assignments"

    def __str__(self):
        return f"{self.theme} / {self.block} -> {self.partner.name}"


# -------------------------
# TrainingPartnerBatch
# -------------------------
class TrainingPartnerBatch(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('ONGOING', 'Ongoing'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.AutoField(primary_key=True)
    partner = models.ForeignKey(TrainingPartner, on_delete=models.CASCADE, related_name='partnerbatch')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='partnerbatch')
    drp_payment_actual = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    notes = models.TextField(blank=True, null=True)
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

    # Geographical Data
    state = models.CharField(max_length=150, blank=True, null=True, db_index=True)
    district = models.ForeignKey(
        'District',
        on_delete=models.SET_NULL,
        related_name='shgs',  # shorter name
        null=True, blank=True,
    )
    block = models.ForeignKey(
        'Block',
        on_delete=models.SET_NULL,
        related_name='shgs',
        null=True, blank=True,
    )

    # SHG Data
    shg_code = models.CharField("SHG Code", max_length=100, blank=False, null=False, db_index=True, unique=True)
    shg_name = models.CharField("SHG Name", max_length=200, blank=True, null=True)
    date_of_formation = models.DateField(blank=True, null=True)

    # optional metadata
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
        # If shg_code isn't globally unique in your data, comment the unique=True above
        # and use:
        # unique_together = ('shg_code', 'block')

    def __str__(self):
        return f"{self.shg_name or self.shg_code} ({self.shg_code})"