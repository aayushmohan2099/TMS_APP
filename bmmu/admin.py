# admin.py
from django.contrib import admin
from django import forms
from django.urls import path, reverse
from django.utils.html import format_html
from django.contrib.auth import get_user_model
from import_export.admin import ImportExportModelAdmin

from .models import *

from .resources import *


User = get_user_model()


class BlueprintAdminMixin:
    """Adds a 'download-blueprint' URL which calls the resource to export a blueprint."""
    def get_urls(self):
        urls = super().get_urls()
        model_name = self.model._meta.model_name
        app_label = self.model._meta.app_label
        name = f"admin:{app_label}_{model_name}_download_blueprint"
        custom = [
            path("download-blueprint/", self.admin_site.admin_view(self.download_blueprint), name=f"{app_label}_{model_name}_download_blueprint"),
        ]
        return custom + urls

    def download_blueprint(self, request):
        # If you have a helper for blueprint export, call it; fallback: use resource export
        resource = getattr(self, "resource_class", None)
        if resource:
            res = resource()
            dataset = res.export(res.get_queryset())
            response = admin.HttpResponse(dataset.xlsx, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response['Content-Disposition'] = f'attachment; filename={self.model._meta.model_name}_blueprint.xlsx'
            return response
        raise NotImplementedError("Resource class not defined for blueprint export.")


# -------------------------
# User admin
# -------------------------
class CustomUserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Password confirmation", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "role")

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords don't match.")
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        p = self.cleaned_data.get("password1")
        if p:
            user.set_password(p)
        if commit:
            user.save()
        return user


@admin.register(User)
class UserAdmin(BlueprintAdminMixin, ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = UserResource
    list_display = ("id", "username", "role", "is_active", "is_staff", "date_joined")
    search_fields = ("username", "first_name", "last_name", "email", "role")
    list_filter = ("role", "is_active", "is_staff")
    ordering = ("-date_joined",)
    add_form = CustomUserCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "email")}),
        ("Permissions", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )


# -------------------------
# Geography admin
# -------------------------
@admin.register(Mandal)
class MandalAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("district_id", "district_name_en", "state_id", "mandal")
    search_fields = ("district_name_en", "district_code", "lgd_code")
    list_filter = ("state_id",)
    ordering = ("district_name_en",)


@admin.register(Block)
class BlockAdmin(BlueprintAdminMixin, ImportExportModelAdmin):
    resource_class = BlockResource
    list_display = ("block_id", "block_name_en", "district", "state_id", "is_aspirational")
    search_fields = ("block_name_en", "block_code")
    list_filter = ("state_id", "is_aspirational")
    autocomplete_fields = ("district",)


@admin.register(Panchayat)
class PanchayatAdmin(admin.ModelAdmin):
    list_display = ("panchayat_id", "panchayat_name_en", "block", "district")
    search_fields = ("panchayat_name_en",)
    autocomplete_fields = ("block", "district")


@admin.register(Village)
class VillageAdmin(admin.ModelAdmin):
    list_display = ("village_id", "village_name_english", "panchayat", "is_active")
    search_fields = ("village_name_english", "village_code")
    autocomplete_fields = ("panchayat",)


@admin.register(DistrictCategory)
class DistrictCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "district", "category_name")
    search_fields = ("district__district_name_en", "category_name")
    list_filter = ("category_name",)


# -------------------------
# SHG
# -------------------------
@admin.register(SHG)
class SHGAdmin(admin.ModelAdmin):
    list_display = ("shg_code", "shg_name", "state", "district", "block")
    search_fields = ("shg_code", "shg_name")
    list_filter = ("state", "district")


# -------------------------
# Beneficiary
# -------------------------
@admin.register(Beneficiary)
class BeneficiaryAdmin(BlueprintAdminMixin, ImportExportModelAdmin):
    resource_class = BeneficiaryResource
    list_display = ("id", "member_name", "member_code", "shg_code", "district", "mobile_no", "created_at")
    search_fields = ("member_name", "member_code", "shg_code", "mobile_no", "aadhaar_no")
    list_filter = ("district",)


# -------------------------
# Training Plan / Master Trainer
# -------------------------
@admin.register(TrainingPlan)
class TrainingPlanAdmin(BlueprintAdminMixin, ImportExportModelAdmin):
    resource_class = TrainingPlanResource
    list_display = ("id", "training_name", "theme", "type_of_training", "level_of_training", "no_of_days", "approval_status", "created_at")
    search_fields = ("training_name", "theme")
    list_filter = ("type_of_training", "level_of_training", "approval_status")
    autocomplete_fields = ("theme_expert",)


class MasterTrainerCertificateInline(admin.TabularInline):
    model = MasterTrainerCertificate
    extra = 0
    readonly_fields = ("created_at",)
    fields = ("certificate_number", "training_module", "issued_on", "certificate_file", "created_at")
    autocomplete_fields = ("training_module",)


@admin.register(MasterTrainer)
class MasterTrainerAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = MasterTrainerResource
    list_display = ("id", "full_name", "designation", "parent_or_spouse_name", "mobile_no", "theme", "district")
    search_fields = ("full_name", "theme", "empanel_district")
    list_filter = ("designation",)
    inlines = (MasterTrainerCertificateInline,)


@admin.register(MasterTrainerCertificate)
class MasterTrainerCertificateAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    list_display = ("id", "trainer", "certificate_number", "training_module", "issued_on", "created_at")
    search_fields = ("trainer__full_name", "certificate_number")
    autocomplete_fields = ("trainer", "training_module")
    readonly_fields = ("created_at",)


@admin.register(MasterTrainerExpertise)
class MasterTrainerExpertiseAdmin(admin.ModelAdmin):
    list_display = ("id", "trainer", "training_plan", "created_at")
    search_fields = ("trainer__full_name", "training_plan__training_name")
    autocomplete_fields = ("trainer", "training_plan")


# -------------------------
# Training Partner & Centres
# -------------------------
class TrainingPartnerCentreInline(admin.TabularInline):
    model = TrainingPartnerCentre
    extra = 0
    readonly_fields = ("created_at",)
    fields = ("serial_number", "district", "venue_name", "venue_address", "created_at")


class TrainingPartnerTargetsInline(admin.TabularInline):
    model = TrainingPartnerTargets
    extra = 0
    readonly_fields = ("created_at",)
    fields = ("allocated_by", "target_type", "target_count", "notes", "created_at")
    autocomplete_fields = ("allocated_by",)


@admin.register(TrainingPartner)
class TrainingPartnerAdmin(BlueprintAdminMixin, ImportExportModelAdmin):
    resource_class = TrainingPartnerResource
    list_display = ("id", "name", "contact_person", "contact_mobile", "email", "tpm_registration_no", "created_at")
    search_fields = ("name", "contact_person", "contact_mobile", "email")
    inlines = (TrainingPartnerCentreInline, TrainingPartnerTargetsInline)
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)


@admin.register(TrainingPartnerCentre)
class TrainingPartnerCentreAdmin(admin.ModelAdmin):
    list_display = ("id", "partner", "venue_name", "district", "training_hall_capacity", "created_at")
    search_fields = ("venue_name", "partner__name")
    autocomplete_fields = ("partner", "district", "uploaded_by")
    readonly_fields = ("created_at",)


@admin.register(TrainingPartnerCentreRooms)
class TrainingPartnerCentreRoomsAdmin(admin.ModelAdmin):
    list_display = ("id", "centre", "room_name", "room_capacity", "created_at")
    search_fields = ("centre__venue_name", "room_name")
    autocomplete_fields = ("centre",)
    readonly_fields = ("created_at",)


@admin.register(TrainingPartnerSubmission)
class TrainingPartnerSubmissionAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = TrainingPartnerSubmissionResource
    list_display = ("id", "centre", "category", "uploaded_by", "uploaded_on")
    search_fields = ("centre__venue_name", "uploaded_by__username")
    autocomplete_fields = ("centre", "uploaded_by")
    readonly_fields = ("uploaded_on",)


@admin.register(TrainingPartnerTargets)
class TrainingPartnerTargetsAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'partner_link',
        'target_type',
        'display_scope',
        'target_count',
        'financial_year',
        'allocated_by',
        'allocated_on',
        'created_at',
    )
    list_filter = (
        'target_type',
        'financial_year',
        'partner',
        'district',
    )
    search_fields = (
        'partner__name',
        'training_plan__training_name',
        'theme',
        'notes',
        'financial_year',
    )
    readonly_fields = ('created_at', 'allocated_on')
    list_select_related = ('partner', 'training_plan', 'district', 'allocated_by')
    ordering = ('-created_at',)

    fieldsets = (
        ('Basic', {
            'fields': ('partner', 'allocated_by', 'allocated_on', 'created_at', 'financial_year')
        }),
        ('Scope', {
            'fields': ('target_type', 'district', 'training_plan', 'theme', 'target_count')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
    )

    def partner_link(self, obj):
        if obj.partner_id:
            url = f"/admin/{obj.partner._meta.app_label}/{obj.partner._meta.model_name}/{obj.partner_id}/change/"
            return format_html('<a href="{}">{}</a>', url, obj.partner.name)
        return '-'
    partner_link.short_description = 'Partner'
    partner_link.admin_order_field = 'partner__name'

    def display_scope(self, obj):
        if obj.target_type == 'MODULE':
            plan = getattr(obj, 'training_plan', None)
            plan_name = plan.training_name if plan else f"plan:{obj.training_plan_id or 'N/A'}"
            district = getattr(obj, 'district', None)
            district_name = district.district_name_en if district else (obj.district_id or 'N/A')
            return f"Module: {plan_name} / District: {district_name}"
        elif obj.target_type == 'DISTRICT':
            district = getattr(obj, 'district', None)
            return f"District: {district.district_name_en if district else (obj.district_id or 'N/A')}"
        else:
            return f"Theme: {obj.theme or 'N/A'}"
    display_scope.short_description = 'Scope'

    # show more columns in change list if needed via custom methods (already included)
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('partner', 'training_plan', 'district', 'allocated_by')

# -------------------------
# TrainingRequest and Batch flow
# -------------------------
@admin.register(TrainingRequest)
class TrainingRequestAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = TrainingRequestResource
    list_display = ("id", "training_plan", "training_type", "partner", "level", "status", "created_by", "created_at")
    search_fields = ("training_plan__training_name", "partner__name", "created_by__username")
    list_filter = ("training_type", "level", "status", "partner")
    autocomplete_fields = ("training_plan", "partner", "created_by", "beneficiaries", "trainers")
    readonly_fields = ("created_at",)


@admin.register(Batch)
class BatchAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = BatchResource
    list_display = ("id", "code", "request", "centre", "start_date", "end_date", "created_at")
    search_fields = ("code", "request__code", "request__training_plan__training_name")
    list_filter = ("start_date", "end_date")
    autocomplete_fields = ("request", "centre", "trainers")
    readonly_fields = ("created_at",)


@admin.register(TrainingPartnerBatch)
class TrainingPartnerBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "partner", "batch", "status", "assigned_on")
    search_fields = ("partner__name", "batch__code")
    list_filter = ("status",)
    autocomplete_fields = ("partner", "batch")
    readonly_fields = ("assigned_on",)


@admin.register(TrainerBatchParticipation)
class TrainerBatchParticipationAdmin(admin.ModelAdmin):
    list_display = ("id", "trainer", "batch", "participated", "status", "created_at")
    search_fields = ("trainer__full_name", "batch__code")
    list_filter = ("participated", "status")
    autocomplete_fields = ("trainer", "batch")
    readonly_fields = ("created_at",)


@admin.register(BatchBeneficiary)
class BatchBeneficiaryAdmin(admin.ModelAdmin):
    list_display = ("id", "beneficiary", "batch", "registered_on", "attended")
    search_fields = ("beneficiary__member_name", "beneficiary__member_code", "batch__code")
    list_filter = ("attended",)
    readonly_fields = ("registered_on",)
    autocomplete_fields = ("beneficiary", "batch")

@admin.register(BeneficiaryBatchRegistration)
class BeneficiaryBatchRegistrationAdmin(admin.ModelAdmin):
    list_display = ("id", "beneficiary", "training", "registered_on", "attended")
    search_fields = ("beneficiary__member_name", "beneficiary__member_code", "training__code")
    list_filter = ("attended",)
    readonly_fields = ("registered_on",)
    autocomplete_fields = ("beneficiary", "training")

@admin.register(TrainerBatchRegistration)
class TrainerBatchRegistrationAdmin(admin.ModelAdmin):
    list_display = ("id", "trainer", "training", "registered_on", "attended")
    search_fields = ("trainer__full_name", "training__code")
    readonly_fields = ("registered_on",)
    autocomplete_fields = ("trainer", "training")


# -------------------------
# Assignment models
# -------------------------
@admin.register(BmmuBlockAssignment)
class BmmuBlockAssignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "block", "assigned_at")
    search_fields = ("user__username", "block__block_name_en")
    autocomplete_fields = ("user", "block")


@admin.register(DmmuDistrictAssignment)
class DmmuDistrictAssignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "district", "assigned_at")
    search_fields = ("user__username", "district__district_name_en")
    autocomplete_fields = ("user", "district")

# ---------------------------------
# Batch eKYC Verification Admin
# ---------------------------------
@admin.register(BatchEkycVerification)
class BatchEkycVerificationAdmin(admin.ModelAdmin):
    list_display = ('batch', 'participant_id', 'participant_role', 'ekyc_status', 'verified_on', 'created_at')
    list_filter = ('participant_role', 'ekyc_status', 'batch__code')
    search_fields = ('batch__code', 'participant_id')
    date_hierarchy = 'verified_on'
    autocomplete_fields = ['batch']
    readonly_fields = ('created_at',)


# ---------------------------------
# Participant Attendance Inline
# (for use inside BatchAttendance admin)
# ---------------------------------
class ParticipantAttendanceInline(admin.TabularInline):
    model = ParticipantAttendance
    extra = 0
    fields = ('participant_id', 'participant_name', 'participant_role', 'present')
    readonly_fields = ()
    show_change_link = True


# ---------------------------------
# Batch Attendance Admin
# ---------------------------------
@admin.register(BatchAttendance)
class BatchAttendanceAdmin(admin.ModelAdmin):
    list_display = ('batch', 'date', 'csv_upload', 'created_at')
    list_filter = ('batch__code',)
    search_fields = ('batch__code',)
    date_hierarchy = 'date'
    inlines = [ParticipantAttendanceInline]
    autocomplete_fields = ['batch']
    readonly_fields = ('created_at',)


# ---------------------------------
# Participant Attendance Admin
# ---------------------------------
@admin.register(ParticipantAttendance)
class ParticipantAttendanceAdmin(admin.ModelAdmin):
    list_display = ('participant_name', 'participant_role', 'present', 'attendance', 'attendance_date')
    list_filter = ('participant_role', 'present', 'attendance__batch__code')
    search_fields = ('participant_name', 'participant_id')
    autocomplete_fields = ['attendance']

    def attendance_date(self, obj):
        return obj.attendance.date
    attendance_date.short_description = 'Date'