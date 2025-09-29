# admin.py
from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from django.urls import path, reverse
from django import forms
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from django.utils.html import format_html

from .models import (
    User,
    Beneficiary,
    TrainingPlan,
    MasterTrainer,
    TrainingPartner,
    Batch,
    MasterTrainerCertificate,
    MasterTrainerExpertise,
    TrainingPartnerAssignment,
    TrainingPartnerSubmission,
    TrainingPartnerTargets,
    TrainingPlanPartner,
    TrainingPartnerBatch,
    TrainerBatchParticipation,
    BeneficiaryBatchRegistration,
    TrainingPartnerTargets,
    # geography models
    District,
    Block,
    Panchayat,
    Village,
    # new models
    Mandal,
    DistrictCategory,
    BmmuBlockAssignment,
    DmmuDistrictAssignment,
)

# Resources (some were in your snippet; if missing add or remove as needed)
from .resources import (
    UserResource,
    BeneficiaryResource,
    TrainingPlanResource,
    MasterTrainerResource,
    MasterTrainerCertificateResource,
    TrainingPartnerResource,
    TrainingPartnerSubmissionResource,
    TrainingPartnerTargetsResource,
    BlockResource
)

from .utils import export_blueprint

# If you used get_user_model() earlier, ensure consistency
User = get_user_model()


# ================= Blueprint Admin Mixin =================
class BlueprintAdminMixin:
    """
    Adds a 'download-blueprint' admin url that returns an Excel blueprint via export_blueprint().
    Exposes 'download_blueprint_url' in changelist extra_context for templates.
    Requires the admin class to define `resource_class`.
    """
    def get_urls(self):
        urls = super().get_urls()
        model_name = self.model._meta.model_name
        app_label = self.model._meta.app_label
        url_name = f"{app_label}_{model_name}_download_blueprint"

        custom_urls = [
            path(
                "download-blueprint/",
                self.admin_site.admin_view(self.download_blueprint),
                name=url_name,
            ),
        ]
        return custom_urls + urls

    def download_blueprint(self, request):
        filename = f"{self.model._meta.model_name}_blueprint.xlsx"
        return export_blueprint(self.resource_class, filename)

    def changelist_view(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}
        url_name = f"{self.model._meta.app_label}_{self.model._meta.model_name}_download_blueprint"
        extra_context["download_blueprint_url"] = reverse(f"admin:{url_name}")
        return super().changelist_view(request, extra_context=extra_context)


# ================= Custom Forms for User Admin =================
class CustomUserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Password confirmation', widget=forms.PasswordInput)

    class Meta:
        model = get_user_model()
        fields = ('username', 'first_name', 'last_name', 'email', 'role')

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords don't match")
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])  # Hash the password
        if commit:
            user.save()
        return user


class CustomUserChangeForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ('username', 'first_name', 'last_name', 'email', 'role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')


# ================= Admin classes =================
@admin.register(User)
class UserAdmin(BlueprintAdminMixin, ImportExportModelAdmin, BaseUserAdmin):
    resource_class = UserResource
    list_display = ('id', 'username', 'role', 'is_active', 'is_staff', 'created_at')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'role')
    list_filter = ('role', 'is_active', 'is_staff', 'created_at')

    add_form = CustomUserCreationForm
    form = CustomUserChangeForm

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'first_name', 'last_name', 'email', 'role', 'password1', 'password2', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
    )

    def save_model(self, request, obj, form, change):
        # If password provided in change form, ensure it's hashed
        raw_password = form.cleaned_data.get("password")
        if raw_password:
            obj.set_password(raw_password)
        super().save_model(request, obj, form, change)


@admin.register(Beneficiary)
class BeneficiaryAdmin(BlueprintAdminMixin, ImportExportModelAdmin):
    resource_class = BeneficiaryResource
    list_display = ('id', 'member_name', 'member_code', 'shg_code', 'district', 'mobile_no', 'aadhaar_no', 'created_at')
    search_fields = ('member_name', 'member_code', 'shg_code', 'mobile_no', 'aadhaar_no')
    list_filter = ('district', 'bank_name', 'social_category', 'created_at')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TrainingPlan)
class TrainingPlanAdmin(BlueprintAdminMixin, ImportExportModelAdmin):
    resource_class = TrainingPlanResource

    list_display = (
        'id',
        'training_name',
        'theme',
        'type_of_training',
        'level_of_training',
        'no_of_days',
        'approval_status',
        'theme_expert',
        'created_at',
    )

    search_fields = (
        'training_name',
        'theme',
        'theme_expert__username',
        'approval_status',
    )

    list_filter = ('type_of_training', 'level_of_training', 'approval_status')

    autocomplete_fields = ('theme_expert',)

    fieldsets = (
        (None, {
            'fields': ('training_name', 'theme', 'type_of_training', 'level_of_training', 'no_of_days')
        }),
        ('Theme Expert', {
            'fields': ('theme_expert',),
            'description': 'SMMU theme expert (nullable).'
        }),
        ('Approval / Meta', {
            'fields': ('approval_status', 'created_at'),
        }),
    )

    readonly_fields = ('created_at',)


class MasterTrainerCertificateInline(admin.TabularInline):
    model = MasterTrainerCertificate
    extra = 0
    readonly_fields = ('created_at',)
    fields = ('certificate_number', 'training_module', 'issued_on', 'certificate_file', 'created_at')
    autocomplete_fields = ('training_module',)


@admin.register(MasterTrainer)
class MasterTrainerAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = MasterTrainerResource
    inlines = (MasterTrainerCertificateInline,)

    list_display = (
        'id',
        'full_name',
        'skills_short',
        'empanel_district',
        'mobile_no',
        'success_rate',
        'created_at',
    )
    search_fields = (
        'full_name', 'skills', 'empanel_district', 'mobile_no', 'aadhaar_no'
    )
    list_filter = ('empanel_district', 'designation')
    readonly_fields = ('created_at',)

    def skills_short(self, obj):
        if not getattr(obj, 'skills', None):
            return "-"
        s = (obj.skills[:80] + '...') if len(obj.skills) > 80 else obj.skills
        return s
    skills_short.short_description = "Skills"


@admin.register(MasterTrainerCertificate)
class MasterTrainerCertificateAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = MasterTrainerCertificateResource
    list_display = ('id', 'trainer', 'certificate_number', 'training_module', 'issued_on', 'created_at')
    search_fields = ('trainer__full_name', 'certificate_number', 'training_module__training_name')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('trainer', 'training_module')


@admin.register(MasterTrainerExpertise)
class MasterTrainerExpertiseAdmin(admin.ModelAdmin):
    list_display = ('id', 'trainer', 'training_plan', 'created_at')
    search_fields = ('trainer__full_name', 'training_plan__training_name')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('training_plan', 'trainer')


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'code', 'training_plan', 'start_date', 'end_date',
        'partner', 'status', 'created_by', 'created_at'
    )
    search_fields = ('code', 'training_plan__training_name', 'training_plan__theme', 'partner__name')
    list_filter = ('status', 'partner', 'training_plan__theme')

    autocomplete_fields = ('training_plan', 'partner', 'created_by')
    readonly_fields = ('created_at',)


@admin.register(TrainingPartnerAssignment)
class TrainingPartnerAssignmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'theme', 'block', 'partner', 'created_at')
    search_fields = ('theme', 'block', 'partner__name')
    list_filter = ('partner',)
    autocomplete_fields = ('partner',)


# Inlines for TrainingPartner
class TrainingPartnerSubmissionInline(admin.TabularInline):
    model = TrainingPartnerSubmission
    extra = 0
    readonly_fields = ('uploaded_on',)
    fields = ('category', 'file', 'uploaded_by', 'uploaded_on', 'notes')
    autocomplete_fields = ('uploaded_by',)


class TrainingPartnerTargetsInline(admin.TabularInline):
    model = TrainingPartnerTargets
    extra = 0
    fields = ('allocated_by', 'target_type', 'target_key', 'target_count', 'notes', 'evidence_file', 'created_at')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('allocated_by',)


@admin.register(TrainingPartner)
class TrainingPartnerAdmin(BlueprintAdminMixin, ImportExportModelAdmin):
    resource_class = TrainingPartnerResource
    inlines = (TrainingPartnerSubmissionInline, TrainingPartnerTargetsInline)

    list_display = ('id', 'name', 'contact_person', 'contact_mobile', 'email', 'center_location', 'tpm_registration_no', 'created_at')
    search_fields = ('name', 'contact_person', 'contact_mobile', 'email', 'tpm_registration_no', 'bank_account_number')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('user',)

    fieldsets = (
        ("Basic", {
            "fields": ('user', 'name', 'contact_person', 'contact_mobile', 'email')
        }),
        ("Location / Address", {
            "fields": ('center_location', 'address')
        }),
        ("Bank Details", {
            "fields": ('bank_name', 'bank_branch', 'bank_account_number', 'bank_ifsc')
        }),
        ("Registration / Docs", {
            "fields": ('tpm_registration_no', 'certifications', 'mou_form', 'signed_report_file')
        }),
        ("Photographs / Submissions", {
            "fields": ('photographs_submission',),
            "description": "Summary/status stored here; actual files are in the inline below."
        }),
        ("Meta", {
            "fields": ('created_at',)
        }),
    )


# TrainingPartnerSubmission admin (also provide resource)
@admin.register(TrainingPartnerSubmission)
class TrainingPartnerSubmissionAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = TrainingPartnerSubmissionResource
    list_display = ('id', 'partner', 'category', 'uploaded_by', 'uploaded_on')
    search_fields = ('partner__name', 'uploaded_by__username', 'category')
    readonly_fields = ('uploaded_on',)
    autocomplete_fields = ('partner', 'uploaded_by')
    list_filter = ('category', 'uploaded_on')


@admin.register(TrainingPartnerTargets)
class TrainingPartnerTargetsAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = TrainingPartnerTargetsResource
    list_display = ('id', 'partner', 'target_type', 'target_key', 'target_count', 'allocated_by', 'created_at')
    search_fields = ('partner__name', 'target_key')
    list_filter = ('target_type',)
    autocomplete_fields = ('partner', 'allocated_by')
    readonly_fields = ('created_at',)


@admin.register(TrainingPlanPartner)
class TrainingPlanPartnerAdmin(admin.ModelAdmin):
    list_display = ('id', 'training_plan', 'partner', 'drp_payments', 'assigned_on', 'assigned_by')
    search_fields = ('training_plan__training_name', 'partner__name')
    autocomplete_fields = ('training_plan', 'partner', 'assigned_by')
    readonly_fields = ('assigned_on',)


@admin.register(TrainingPartnerBatch)
class TrainingPartnerBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'partner', 'batch', 'drp_payment_actual', 'status', 'assigned_on')
    search_fields = ('partner__name', 'batch__code')
    list_filter = ('status',)
    autocomplete_fields = ('partner', 'batch',)
    readonly_fields = ('assigned_on',)


@admin.register(TrainerBatchParticipation)
class TrainerBatchParticipationAdmin(admin.ModelAdmin):
    list_display = ('id', 'trainer', 'batch', 'participated', 'status', 'created_at')
    search_fields = ('trainer__full_name', 'batch__code')
    list_filter = ('status', 'participated')
    autocomplete_fields = ('trainer', 'batch')
    readonly_fields = ('created_at',)


@admin.register(BeneficiaryBatchRegistration)
class BeneficiaryBatchRegistrationAdmin(admin.ModelAdmin):
    list_display = ('id', 'beneficiary', 'batch', 'registered_on', 'attended')
    search_fields = ('beneficiary__member_name', 'beneficiary__member_code', 'batch__code')
    list_filter = ('attended', 'registered_on')
    autocomplete_fields = ('beneficiary', 'batch')
    readonly_fields = ('registered_on',)


# -------------------------
# Geography admin (District / Block / Panchayat / Village / Mandal / DistrictCategory)
# -------------------------

# Inline to display Districts under Mandal admin
class DistrictInlineForMandal(admin.TabularInline):
    model = District
    fields = ('district_id', 'district_name_en', 'state_id')
    readonly_fields = ('district_id', 'district_name_en', 'state_id')
    extra = 0
    can_delete = False
    show_change_link = True


@admin.register(Mandal)
class MandalAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)
    inlines = (DistrictInlineForMandal,)
    ordering = ('name',)


@admin.register(DistrictCategory)
class DistrictCategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'district', 'category_name')
    search_fields = ('district__district_name_en', 'category_name')
    list_filter = ('category_name',)
    autocomplete_fields = ('district',)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ('district_id', 'district_name_en', 'mandal', 'district_code', 'state_id', 'lgd_code', 'language_id')
    search_fields = ('district_name_en', 'district_code', 'lgd_code')
    list_filter = ('state_id', 'language_id', 'mandal')
    readonly_fields = ()
    ordering = ('district_name_en',)
    autocomplete_fields = ('mandal',)


@admin.register(Block)
class BlockAdmin(BlueprintAdminMixin, ImportExportModelAdmin):
    resource_class = BlockResource
    list_display = ('block_id', 'block_name_en', 'block_code', 'district', 'district_name_en', 'state_id', 'rural_urban_area', 'is_aspirational')
    search_fields = ('block_name_en', 'block_code', 'district__district_name_en')
    list_filter = ('state_id', 'rural_urban_area', 'is_aspirational')
    autocomplete_fields = ('district',)
    ordering = ('district', 'block_name_en')


@admin.register(Panchayat)
class PanchayatAdmin(admin.ModelAdmin):
    list_display = ('panchayat_id', 'panchayat_name_en', 'block', 'district', 'state_id', 'rural_urban_area')
    search_fields = ('panchayat_name_en', 'panchayat_code', 'block__block_name_en', 'district__district_name_en')
    list_filter = ('state_id', 'rural_urban_area')
    autocomplete_fields = ('district', 'block')
    ordering = ('district', 'block', 'panchayat_name_en')


@admin.register(Village)
class VillageAdmin(admin.ModelAdmin):
    list_display = ('village_id', 'village_name_english', 'panchayat', 'district_id', 'block_id', 'is_active')
    search_fields = ('village_name_english', 'village_code', 'panchayat__panchayat_name_en')
    list_filter = ('is_active',)
    autocomplete_fields = ('panchayat',)
    ordering = ('panchayat', 'village_name_english')

@admin.register(BmmuBlockAssignment)
class BmmuBlockAssignmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'block', 'assigned_at')
    search_fields = ('user', 'block',)

@admin.register(DmmuDistrictAssignment)
class DmmuDistrictAssignment(admin.ModelAdmin):
    list_display = ('id', 'user', 'district', 'assigned_at')
    search_fields = ('user', 'district',)

# If there are models/resources you haven't yet created in resources.py, remove resource_class for those admin classes
# or create corresponding resources. The BlueprintAdminMixin requires resource_class to be present.
