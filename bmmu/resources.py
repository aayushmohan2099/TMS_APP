# resources.py
from import_export import resources, fields, widgets
from import_export.widgets import ForeignKeyWidget, DateWidget, CharWidget, IntegerWidget
from django.contrib.auth import get_user_model

from .models import (
    User,
    Beneficiary,
    TrainingPlan,
    MasterTrainer,
    MasterTrainerCertificate,
    TrainingPartner,
    TrainingPartnerCentre,
    TrainingPartnerSubmission,
    TrainingPartnerTargets,
    TrainingRequest,
    Batch,
    Block,
)

User = get_user_model()


class FileWidget(widgets.Widget):
    """
    File widget: export returns URL (if available) or filename.
    On import we return the raw value (you can extend to fetch/store files).
    """
    def clean(self, value, row=None, *args, **kwargs):
        # For now, just store whatever is present in import cell (could be a filename or URL)
        return value or None

    def render(self, value, obj=None):
        if not value:
            return ""
        try:
            return getattr(value, 'url', '') or getattr(value, 'name', str(value))
        except Exception:
            return str(value)


# -------------------------
# User
# -------------------------
class UserResource(resources.ModelResource):
    class Meta:
        model = User
        import_id_fields = ("username",)
        skip_unchanged = True
        report_skipped = True
        fields = ("username", "first_name", "last_name", "email", "role")


# -------------------------
# Beneficiary
# -------------------------
class BeneficiaryResource(resources.ModelResource):
    class Meta:
        model = Beneficiary
        import_id_fields = ("member_code",)
        skip_unchanged = True
        report_skipped = True
        exclude = ("id", "created_at", "updated_at")


# -------------------------
# Block
# -------------------------
class BlockResource(resources.ModelResource):
    class Meta:
        model = Block
        import_id_fields = ("block_id",)
        skip_unchanged = True
        report_skipped = True
        fields = ("block_id", "block_name_en", "block_code", "district", "state_id")


# -------------------------
# TrainingPlan
# -------------------------
class TrainingPlanResource(resources.ModelResource):
    theme_expert = fields.Field(attribute="theme_expert", column_name="theme_expert_username",
                                widget=ForeignKeyWidget(User, "username"))

    class Meta:
        model = TrainingPlan
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
        fields = ("id", "training_name", "theme", "type_of_training", "level_of_training", "no_of_days",
                  "approval_status", "theme_expert")


# -------------------------
# MasterTrainer
# -------------------------
class MasterTrainerResource(resources.ModelResource):
    date_of_birth = fields.Field(attribute="date_of_birth", column_name="date_of_birth",
                                 widget=DateWidget(format="%Y-%m-%d"))
    profile_picture = fields.Field(attribute="profile_picture", column_name="profile_picture", widget=FileWidget())

    class Meta:
        model = MasterTrainer
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
        fields = (
            "id", "full_name", "date_of_birth", "mobile_no", "aadhaar_no",
            "empanel_district", "designation", "bank_account_number", "ifsc", "branch_name", "bank_name",
            "skills", "profile_picture",
        )


# -------------------------
# TrainingPartner
# -------------------------
class TrainingPartnerResource(resources.ModelResource):
    user = fields.Field(attribute="user", column_name="user_username", widget=ForeignKeyWidget(User, "username"))
    mou_form = fields.Field(attribute="mou_form", column_name="mou_form", widget=FileWidget())
    signed_report_file = fields.Field(attribute="signed_report_file", column_name="signed_report_file", widget=FileWidget())

    class Meta:
        model = TrainingPartner
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
        fields = (
            "id", "user", "name", "contact_person", "contact_mobile", "email", "address",
            "bank_name", "bank_branch", "bank_ifsc", "bank_account_number",
            "tpm_registration_no", "mou_form", "signed_report_file",
        )


# -------------------------
# TrainingPartnerSubmission
# -------------------------
class TrainingPartnerSubmissionResource(resources.ModelResource):
    centre = fields.Field(attribute="centre", column_name="centre_id", widget=ForeignKeyWidget(TrainingPartnerCentre, "id"))
    uploaded_by = fields.Field(attribute="uploaded_by", column_name="uploaded_by_username", widget=ForeignKeyWidget(User, "username"))
    file = fields.Field(attribute="file", column_name="file", widget=FileWidget())

    class Meta:
        model = TrainingPartnerSubmission
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
        exclude = ("uploaded_on",)
        fields = ("id", "centre", "category", "file", "uploaded_by", "notes")


# -------------------------
# TrainingPartnerTargets
# -------------------------
class TrainingPartnerTargetsResource(resources.ModelResource):
    partner = fields.Field(attribute="partner", column_name="partner_name", widget=ForeignKeyWidget(TrainingPartner, "name"))
    allocated_by = fields.Field(attribute="allocated_by", column_name="allocated_by_username", widget=ForeignKeyWidget(User, "username"))
    evidence_file = fields.Field(attribute="evidence_file", column_name="evidence_file", widget=FileWidget())

    class Meta:
        model = TrainingPartnerTargets
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
        exclude = ("created_at",)
        fields = ("id", "partner", "allocated_by", "target_type", "target_key", "target_count", "notes", "evidence_file")


# -------------------------
# TrainingRequest
# -------------------------
class TrainingRequestResource(resources.ModelResource):
    training_plan = fields.Field(attribute="training_plan", column_name="training_plan_id", widget=ForeignKeyWidget(TrainingPlan, "id"))
    partner = fields.Field(attribute="partner", column_name="partner_id", widget=ForeignKeyWidget(TrainingPartner, "id"))
    created_by = fields.Field(attribute="created_by", column_name="created_by_username", widget=ForeignKeyWidget(User, "username"))

    class Meta:
        model = TrainingRequest
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
        fields = ("id", "training_plan", "training_type", "partner", "level", "status", "rejection_reason", "created_by", "created_at")


# -------------------------
# Batch
# -------------------------
class BatchResource(resources.ModelResource):
    request = fields.Field(attribute="request", column_name="training_request_id", widget=ForeignKeyWidget(TrainingRequest, "id"))
    centre = fields.Field(attribute="centre", column_name="centre_id", widget=ForeignKeyWidget(TrainingPartnerCentre, "id"))
    start_date = fields.Field(attribute="start_date", column_name="start_date", widget=DateWidget(format="%Y-%m-%d"))
    end_date = fields.Field(attribute="end_date", column_name="end_date", widget=DateWidget(format="%Y-%m-%d"))

    class Meta:
        model = Batch
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
        fields = ("id", "code", "request", "centre", "start_date", "end_date", "created_at")
