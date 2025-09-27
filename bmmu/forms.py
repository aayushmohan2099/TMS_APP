# forms.py
import re
from django.contrib.auth import get_user_model
from django import forms
from .models import TrainingPlan, Batch, TrainingPartner, MasterTrainer, TrainingPartnerSubmission, MasterTrainerCertificate

User = get_user_model()

class TrainingPlanForm(forms.ModelForm):
    class Meta:
        model = TrainingPlan
        # Use explicit fields to avoid exposing FK fields you don't want edited via public forms,
        # but for admin/internal use, __all__ is acceptable.
        fields = '__all__'


class BatchNominateForm(forms.ModelForm):
    class Meta:
        model = Batch
        # Exclude fields BMMU should not set now (start_date, end_date)
        exclude = ('start_date', 'end_date', 'created_at', 'status', 'partner')


class SignupForm(forms.Form):
    """
    Minimal signup: only username + password (and optional email).
    Role must be provided (training_partner or master_trainer).
    Note: role is hidden so your view must set initial role or override it on form save.
    """
    username = forms.CharField(max_length=150, label="Username")
    email = forms.EmailField(required=False, label="Email (optional)")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")
    role = forms.ChoiceField(choices=[('training_partner', 'Training Partner'), ('master_trainer', 'Master Trainer')],
                             widget=forms.HiddenInput)

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords don't match.")
        return cleaned


class TrainingPartnerProfileForm(forms.ModelForm):
    class Meta:
        model = TrainingPartner
        # Exclude 'user' so a partner cannot reassign the owner
        exclude = ('user',)

    def clean_mou_form(self):
        f = self.cleaned_data.get('mou_form')
        if f:
            name = getattr(f, 'name', '').lower()
            if not (name.endswith('.pdf') or name.endswith('.jpg') or name.endswith('.jpeg') or name.endswith('.png')):
                raise forms.ValidationError("MoU must be a PDF or an image (jpg/png).")
        return f

    def clean_signed_report_file(self):
        f = self.cleaned_data.get('signed_report_file')
        if f:
            name = getattr(f, 'name', '').lower()
            if not (name.endswith('.pdf') or name.endswith('.jpg') or name.endswith('.jpeg') or name.endswith('.png')):
                raise forms.ValidationError("Signed report must be PDF or image (jpg/png).")
        return f

    def clean_contact_mobile(self):
        m = self.cleaned_data.get('contact_mobile') or ''
        digits = ''.join(ch for ch in m if ch.isdigit())
        if digits and len(digits) < 7:
            raise forms.ValidationError("Please enter a valid mobile number.")
        # Return normalized digits-only string (or empty string)
        return digits or ''


class TrainingPartnerSubmissionForm(forms.ModelForm):
    class Meta:
        model = TrainingPartnerSubmission
        fields = ('category', 'file', 'notes')

    def clean_file(self):
        f = self.cleaned_data.get('file')
        if f:
            name = getattr(f, 'name', '').lower()
            if not (name.endswith('.pdf') or name.endswith('.jpg') or name.endswith('.jpeg') or name.endswith('.png')):
                raise forms.ValidationError("Upload must be a PDF or an image (jpg/png).")
        return f


class MasterTrainerForm(forms.ModelForm):
    class Meta:
        model = MasterTrainer
        # keeps admin-only fields like 'user' available in admin (for linking)
        fields = [
            'user',
            'full_name', 'skills', 'empanel_district', 'date_of_birth', 'social_category',
            'gender', 'education', 'marital_status', 'parent_or_spouse_name',
            'bank_account_number', 'ifsc', 'branch_name', 'bank_name',
            'mobile_no', 'aadhaar_no', 'profile_picture',
            'thematic_expert_recommendation', 'success_rate', 'any_other_tots',
            'other_achievements', 'recommended_tots_by_dmmu', 'success_story_publications',
            'designation',
        ]

    def clean_skills(self):
        s = self.cleaned_data.get('skills') or ''
        parts = [part.strip() for part in re.split(r'[;,|]', s) if part.strip()]
        normalized = ",".join(parts)
        return normalized


class MasterTrainerCertificateForm(forms.ModelForm):
    issued_on = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    class Meta:
        model = MasterTrainerCertificate
        fields = [
            'training_module',    # FK to TrainingPlan (nullable)
            'certificate_number',
            'issued_on',
            'certificate_file',
        ]
        widgets = {
            'training_module': forms.Select(attrs={'class': 'form-select'}),
            'certificate_number': forms.TextInput(attrs={'class': 'form-control'}),
            'certificate_file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def clean_certificate_file(self):
        f = self.cleaned_data.get('certificate_file')
        if f:
            name = getattr(f, 'name', '').lower()
            if not (name.endswith('.pdf') or name.endswith('.jpg') or name.endswith('.jpeg') or name.endswith('.png')):
                raise forms.ValidationError("Certificate must be a PDF or image (jpg/png).")
        return f


class PublicMasterTrainerProfileForm(forms.ModelForm):
    class Meta:
        model = MasterTrainer
        fields = [
            'full_name',
            'skills',
            'empanel_district',
            'date_of_birth',
            'social_category',
            'gender',
            'education',
            'marital_status',
            'parent_or_spouse_name',
            'bank_account_number',
            'ifsc',
            'branch_name',
            'bank_name',
            'mobile_no',
            'aadhaar_no',
            'profile_picture',
        ]

    def clean_skills(self):
        s = self.cleaned_data.get('skills') or ''
        parts = [part.strip() for part in re.split(r'[;,|]', s) if part.strip()]
        normalized = ",".join(parts)
        return normalized
