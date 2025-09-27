# resources.py
from import_export import resources, fields, widgets
from import_export.widgets import ForeignKeyWidget, DateWidget, Widget, CharWidget
from .models import (
    User, Beneficiary, TrainingPlan, MasterTrainer, MasterTrainerCertificate,
    MasterTrainerExpertise, TrainingPartner, TrainingPartnerTargets, TrainingPartnerSubmission, Batch
)
from django.contrib.auth import get_user_model

User = get_user_model()


class FileWidget(Widget):
    """
    Simple widget for file fields: on export, try to return .url or .name; on import,
    return the raw value (you can extend to fetch/store files if needed).
    """
    def clean(self, value, row=None, *args, **kwargs):
        return value or None

    def render(self, value, obj=None):
        if not value:
            return ""
        try:
            url = getattr(value, 'url', None)
            if url:
                return url
        except Exception:
            pass
        return getattr(value, 'name', str(value))


class ChoiceWidget(widgets.Widget):
    """
    Maps between human-readable labels and internal DB values for choices.
    Accepts either internal code or label when importing.
    """
    def __init__(self, choices, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.choices = dict(choices)
        self.reverse_choices = {v: k for k, v in choices}

    def clean(self, value, row=None, *args, **kwargs):
        if value in (None, ""):
            return None
        if value in self.choices:
            return value
        if value in self.reverse_choices:
            return self.reverse_choices[value]
        val = str(value).strip()
        for code, label in self.choices.items():
            if val.lower() == code.lower() or val.lower() == label.lower():
                return code
        raise ValueError(f"Invalid choice: {value}")

    def render(self, value, obj=None):
        if value in self.choices:
            return self.choices[value]
        return value or ""


# ================= Resources =================
class UserResource(resources.ModelResource):
    class Meta:
        model = User
        skip_unchanged = True
        report_skipped = True
        import_id_fields = ('username',)
        exclude = ('created_at',)


class BeneficiaryResource(resources.ModelResource):
    class Meta:
        model = Beneficiary
        skip_unchanged = True
        report_skipped = True
        import_id_fields = ('member_code',)
        exclude = ('id', 'created_at', 'updated_at',)


class TrainingPlanResource(resources.ModelResource):
    """
    TrainingPlan import/export resource consistent with the model (no training_partner field).
    """
    theme_expert = fields.Field(
        column_name='Thematic expert (username)',
        attribute='theme_expert',
        widget=ForeignKeyWidget(User, 'username')
    )

    training_name = fields.Field(column_name='Module (Training Name)', attribute='training_name', widget=CharWidget())
    theme = fields.Field(column_name='theme', attribute='theme', widget=CharWidget())

    type_of_training = fields.Field(
        column_name='Type',
        attribute='type_of_training',
        widget=ChoiceWidget(choices=TrainingPlan.TYPE_CHOICES)
    )

    level_of_training = fields.Field(
        column_name='Level',
        attribute='level_of_training',
        widget=ChoiceWidget(choices=TrainingPlan.LEVEL_CHOICES)
    )

    no_of_days = fields.Field(column_name='Days', attribute='no_of_days', widget=widgets.IntegerWidget())

    approval_status = fields.Field(column_name='Approval', attribute='approval_status', widget=CharWidget())

    class Meta:
        model = TrainingPlan
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True
        exclude = ('created_at',)


class TrainingPartnerResource(resources.ModelResource):
    user = fields.Field(column_name='User (username)', attribute='user', widget=ForeignKeyWidget(User, 'username'))
    name = fields.Field(column_name='Name', attribute='name')
    contact_person = fields.Field(column_name='Contact Person', attribute='contact_person')
    contact_mobile = fields.Field(column_name='Contact Mobile', attribute='contact_mobile')
    email = fields.Field(column_name='Email', attribute='email')
    center_location = fields.Field(column_name='Center Location', attribute='center_location')
    bank_name = fields.Field(column_name='Bank Name', attribute='bank_name')
    bank_branch = fields.Field(column_name='Bank Branch', attribute='bank_branch')
    bank_account_number = fields.Field(column_name='Bank Account Number', attribute='bank_account_number')
    bank_ifsc = fields.Field(column_name='Bank IFSC', attribute='bank_ifsc')
    tpm_registration_no = fields.Field(column_name='TPM Registration No', attribute='tpm_registration_no')
    targets_allocated = fields.Field(column_name='Targets Allocated (summary)', attribute='targets_allocated')

    class Meta:
        model = TrainingPartner
        fields = (
            'user', 'name', 'contact_person', 'contact_mobile', 'email',
            'center_location',
            'bank_name', 'bank_branch', 'bank_account_number', 'bank_ifsc',
            'tpm_registration_no', 'targets_allocated',
        )
        skip_unchanged = True
        report_skipped = True
        import_id_fields = ()


class TrainingPartnerTargetsResource(resources.ModelResource):
    partner = fields.Field(column_name='Partner Name', attribute='partner', widget=ForeignKeyWidget(TrainingPartner, 'name'))
    allocated_by = fields.Field(column_name='Allocated By (username)', attribute='allocated_by', widget=ForeignKeyWidget(User, 'username'))
    target_type = fields.Field(column_name='Target Type', attribute='target_type')
    target_key = fields.Field(column_name='Target Key', attribute='target_key')
    target_count = fields.Field(column_name='Target Count', attribute='target_count')
    evidence_file = fields.Field(column_name='Evidence File', attribute='evidence_file', widget=FileWidget())

    class Meta:
        model = TrainingPartnerTargets
        import_id_fields = ()
        skip_unchanged = True
        report_skipped = True
        exclude = ('created_at',)


class TrainingPartnerSubmissionResource(resources.ModelResource):
    partner = fields.Field(column_name='Partner Name', attribute='partner', widget=ForeignKeyWidget(TrainingPartner, 'name'))
    category = fields.Field(column_name='Category', attribute='category')
    file = fields.Field(column_name='File', attribute='file', widget=FileWidget())

    class Meta:
        model = TrainingPartnerSubmission
        import_id_fields = ()
        skip_unchanged = True
        report_skipped = True
        exclude = ('uploaded_on',)


class MasterTrainerResource(resources.ModelResource):
    full_name = fields.Field(column_name='Full Name', attribute='full_name')
    skills = fields.Field(column_name='Thematic Sector', attribute='skills')
    empanel_district = fields.Field(column_name='Empanel District', attribute='empanel_district')
    date_of_birth = fields.Field(column_name='Date of Birth', attribute='date_of_birth', widget=DateWidget(format='%Y-%m-%d'))
    social_category = fields.Field(column_name='Social Category', attribute='social_category')
    gender = fields.Field(column_name='Gender', attribute='gender')
    education = fields.Field(column_name='Education', attribute='education')
    marital_status = fields.Field(column_name='Marital Status', attribute='marital_status')
    parent_or_spouse_name = fields.Field(column_name='Father/Mother/Spouse Name', attribute='parent_or_spouse_name')
    bank_account_number = fields.Field(column_name='Account Number', attribute='bank_account_number')
    ifsc = fields.Field(column_name='IFSC', attribute='ifsc')
    branch_name = fields.Field(column_name='Branch Name', attribute='branch_name')
    bank_name = fields.Field(column_name='Bank Name', attribute='bank_name')
    mobile_no = fields.Field(column_name='Mobile No.', attribute='mobile_no')
    aadhaar_no = fields.Field(column_name='Aadhaar No', attribute='aadhaar_no')
    profile_picture = fields.Field(column_name='Profile Picture', attribute='profile_picture', widget=FileWidget())

    thematic_expert_recommendation = fields.Field(column_name='Thematic Expert Recommendation', attribute='thematic_expert_recommendation')
    success_rate = fields.Field(column_name='Success Rate', attribute='success_rate')
    any_other_tots = fields.Field(column_name='Any other ToTs', attribute='any_other_tots')
    other_achievements = fields.Field(column_name='Other Achievements', attribute='other_achievements')
    recommended_tots_by_dmmu = fields.Field(column_name='Recommended ToTs by DMMU', attribute='recommended_tots_by_dmmu')
    success_story_publications = fields.Field(column_name='Success Story Publications', attribute='success_story_publications')

    class Meta:
        model = MasterTrainer
        skip_unchanged = True
        report_skipped = True
        import_id_fields = ()
        exclude = ('created_at',)


class MasterTrainerCertificateResource(resources.ModelResource):
    trainer = fields.Field(column_name='Trainer (full_name)', attribute='trainer', widget=ForeignKeyWidget(MasterTrainer, 'full_name'))
    training_module = fields.Field(column_name='Training Module', attribute='training_module', widget=ForeignKeyWidget(TrainingPlan, 'training_name'))
    certificate_number = fields.Field(column_name='Certificate Number', attribute='certificate_number')
    issued_on = fields.Field(column_name='Issued On', attribute='issued_on', widget=DateWidget(format='%Y-%m-%d'))

    class Meta:
        model = MasterTrainerCertificate
        skip_unchanged = True
        report_skipped = True
        import_id_fields = ('certificate_number',)
        exclude = ('created_at',)
