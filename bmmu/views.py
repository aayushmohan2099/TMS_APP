import os
import json
import logging
import random

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponse, JsonResponse, HttpResponseBadRequest
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.forms import modelform_factory
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.urls import reverse
from django.db import transaction
from django.conf import settings
from django import forms

from .models import *

from .resources import UserResource, BeneficiaryResource, TrainingPlanResource, MasterTrainerResource
from .utils import export_blueprint
from .forms import *

from django.db.models import Q, F, Count

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.db.models import Prefetch
from datetime import date, datetime
from django.db.models import OuterRef, Subquery
from datetime import timedelta
from django.db.utils import OperationalError
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date
from zoneinfo import ZoneInfo
from urllib.parse import unquote, unquote_plus


logger = logging.getLogger(__name__)

def _get_trainer_for_user(user):
    """Return linked MasterTrainer instance or None (safe)."""
    try:
        return getattr(user, 'master_trainer', None)
    except Exception:
        return None
    
def _get_partner_for_user(user):
    """Return linked TrainingPartner instance or None (safe)."""
    try:
        return user.training_partner_profile
    except Exception:
        return None


def home_view(request):
    return render(request, "login.html")


def custom_login(request):
    if request.method == "POST":
        login_type = request.POST.get("login_type")
        username = request.POST.get("username")
        password = request.POST.get("password")

        logger.warning(f"Trying login: user={username}, type={login_type}")

        user = authenticate(request, username=username, password=password)

        if user:
            logger.warning(f"Auth successful for {user.username}, role={getattr(user, 'role', None)}")
        else:
            logger.warning(f"Authentication failed for {username}")

        # Basic checks
        if user is None:
            messages.error(request, "Invalid username or password.")
            return render(request, "login.html")

        # Optional: check active flag
        if not getattr(user, "is_active", True):
            messages.error(request, "This account is inactive. Contact admin.")
            return render(request, "login.html")

        # Ensure login_type provided and matches user's role (case-insensitive)
        if not login_type:
            messages.error(request, "Please select a login type.")
            return render(request, "login.html")

        if getattr(user, "role", "").lower() != login_type.lower():
            messages.error(request, "Invalid username, password, or role.")
            return render(request, "login.html")

        # All good -> log in
        login(request, user)

        # Redirect by role (same as previously)
        user_role = getattr(user, "role", "").lower()
        if user_role == "training_partner":
            return redirect("training_partner_dashboard")
        if user_role == "bmmu":
            return redirect("dashboard")
        if user_role == "smmu":
            return redirect("smmu_dashboard")
        if user_role == "dmmu":
            return redirect("dashboard")
        if user_role == "master_trainer":
            return redirect("master_trainer_dashboard")

        return redirect("dashboard")

    return render(request, "login.html")

@login_required
def custom_logout(request):
    logout(request)
    return redirect("custom_login")


def signup(request):
    """
    Accepts POST (AJAX preferred) to create a minimal user account.
    Returns JSON when X-Requested-With == 'XMLHttpRequest' (AJAX).
    Creates a TrainingPartner or MasterTrainer linked to the user.
    On success, logs the user in and returns {'ok': True, 'redirect': <url>}.
    """
    # Only allow the two roles for public signup
    allowed_roles = ('training_partner', 'master_trainer')

    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data.get('email') or ''
            password = form.cleaned_data['password1']
            role = form.cleaned_data['role'].lower().strip()

            if role not in allowed_roles:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'ok': False, 'errors': {'role': ['Invalid role']}}, status=400)
                else:
                    return HttpResponseForbidden("Signups are allowed only for Master Trainer or Training Partner.")

            UserModel = get_user_model()
            try:
                with transaction.atomic():
                    user = UserModel.objects.create_user(username=username, email=email, password=password)
                    user.role = role
                    user.save()

                    # create minimal linked profile
                    if role == 'training_partner':
                        TrainingPartner.objects.create(user=user, name=user.get_full_name() or user.username)
                    else:
                        MasterTrainer.objects.create(user=user, full_name=user.get_full_name() or user.username)

                    # authenticate & login (so response can redirect to dashboard)
                    logger.warning(f"Attempting to authenticate user: {username}")
                    user = authenticate(request, username=username, password=password)
                    if user:
                        logger.warning(f"User {user.username} authenticated successfully.")
                        login(request, user)
                    else:
                        logger.warning(f"Authentication failed for {username}")

                    # determine redirect based on role
                    if role == 'training_partner':
                        redirect_url = reverse('training_partner_dashboard')
                    else:
                        # trainers use generic dashboard in your app
                        redirect_url = reverse('dashboard')

                    # If AJAX: return JSON instructing client to redirect
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'ok': True, 'redirect': redirect_url})
                    # Non-AJAX fallback
                    messages.success(request, "Account created and logged in. Please complete your profile.")
                    return redirect(redirect_url)
            except Exception as e:
                logger.exception("signup: failed to create user: %s", e)
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'ok': False, 'errors': {'__all__': ['Server error creating account']}}, status=500)
                messages.error(request, "Server error creating account, try again.")
                return redirect('custom_login')
        else:
            # invalid form: return errors as JSON or render page with errors
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                # convert errors to simple dict of lists
                errors = {k: [str(x) for x in v] for k, v in form.errors.items()}
                return JsonResponse({'ok': False, 'errors': errors}, status=400)
            else:
                # Non-AJAX fallback - redirect back to login and show messages
                messages.error(request, "Please fix the errors and try again.")
                return redirect('custom_login')
    else:
        # GET to signup may be used by direct link; redirect to login with role querystring
        role = (request.GET.get('role') or '').lower().strip()
        if role in allowed_roles:
            return redirect(f"{reverse('custom_login')}?role={role}")
        return HttpResponseForbidden("Signups are allowed only for Master Trainer or Training Partner.")
    

@login_required
def dashboard(request):
    """
    Wrapper dashboard which injects app fragments into the content area.
    If user is BMMU, render BMMU fragment as default_content.
    If user is SMMU, render smmu_dashboard fragment as default_content.
    If user is TrainingPartner, redirect to partner-specific dashboard view.
    Fallback: render wrapper with empty content.
    """
    user_role = getattr(request.user, "role", "").lower()

    # Training partner has its own full dashboard (separate template)
    if user_role == "training_partner":
        return redirect("training_partner_dashboard")
    
    # Master Trainer has its own full dashboard (separate template)
    if user_role == "master_trainer":
        return redirect("master_trainer_dashboard")

    # BMMU: render bmmu fragment into wrapper
    if user_role == "bmmu":
        context = _bmmu_fragment_context(request)
        default_content = render_to_string("bmmu_dashboard.html", context, request=request)
        return render(request, "dashboard.html", {"user": request.user, "default_content": default_content})

    # DMMU: redirect to dmmu fragment
    if user_role == "dmmu":
        return redirect("dmmu_dashboard")

    # SMMU: render SMMU fragment into wrapper
    if user_role == "smmu":
        # Reuse smmu_dashboard view logic to build context (keep parity)
        # copy small portion of smmu_dashboard context building:
        chart1 = [random.randint(0, 100) for _ in range(10)]
        chart2 = [random.randint(0, 100) for _ in range(10)]
        chart_labels = [f'Metric {i+1}' for i in range(10)]

        themes = list(TrainingPlan.objects.filter(theme_expert=request.user).values_list('theme', flat=True).distinct())
        themes = [t for t in themes if t]

        batches = []
        try:
            available_statuses = [c[0] for c in Batch._meta.get_field('status').choices]
            interesting = [s for s in ('PENDING', 'ONGOING', 'PENDING_APPROVAL', 'PROPOSED', 'NOMINATED') if s in available_statuses]
            if interesting:
                batch_qs = Batch.objects.filter(status__in=interesting)
            else:
                batch_qs = Batch.objects.all().order_by('-created_at')

            if themes:
                batch_qs = batch_qs.filter(training_plan__theme__in=themes)

            batch_qs = batch_qs.select_related('training_plan', 'partner')[:300]
            for b in batch_qs:
                tp = getattr(b, 'training_plan', None)
                batches.append({
                    'id': b.id,
                    'code': b.code or f'Batch-{b.id}',
                    'theme': getattr(tp, 'theme', '') if tp else '',
                    'module': getattr(tp, 'training_name', '') if tp else '',
                    'start': b.start_date.isoformat() if b.start_date else None,
                    'end': b.end_date.isoformat() if b.end_date else None,
                    'days': getattr(tp, 'no_of_days', None) if tp else None,
                    'trainers_count': b.trainers.count() if hasattr(b, 'trainers') else 0,
                    'participants_count': b.beneficiaries.count() if hasattr(b, 'beneficiaries') else 0,
                    'partner': b.partner.name if getattr(b, 'partner', None) else None,
                    'status': b.status
                })
        except Exception:
            logger.exception("dashboard: failed to build smmu batches")

        context = {
            'chart1': chart1,
            'chart2': chart2,
            'chart_labels': chart_labels,
            'chart1_json': json.dumps(chart1),
            'chart2_json': json.dumps(chart2),
            'chart_labels_json': json.dumps(chart_labels),
            'batches': batches,
            'themes': themes,
        }
        default_content = render_to_string('smmu/smmu_dashboard.html', context, request=request)
        return render(request, 'dashboard.html', {"user": request.user, "default_content": default_content})

    # Fallback: render wrapper dashboard with no default content
    return render(request, "dashboard.html", {"user": request.user, "default_content": ""})


@login_required
def load_app_content(request, app_name):
    """
    AJAX loader for app fragments inside the wrapper dashboard.

    For 'tms' this returns the same rich context as training_program_management,
    so /dashboard/load/tms/ (used by the dashboard sidebar) will populate
    SERVER_TRAINERS / SERVER_TRAINERS_MAP / SERVER_BATCHES etc.
    """
    role = getattr(request.user, "role", "").lower()

    template_map = {
        "tms": {"allowed_roles": ["bmmu", "dmmu", "smmu"], "template": "apps/tms.html"},
        "app2": {"allowed_roles": ["bmmu", "dmmu", "smmu"], "template": "apps/app2.html"},
        "app3": {"allowed_roles": ["bmmu", "dmmu", "smmu"], "template": "apps/app3.html"},
        "bmmu": {"allowed_roles": ["bmmu"], "template": "bmmu_dashboard.html"},
        "bmmu_add": {"allowed_roles": ["bmmu"], "template": "bmmu_add_beneficiary.html"},
        "bmmu_delete": {"allowed_roles": ["bmmu"], "template": "bmmu_delete_beneficiaries.html"},
    }

    app_config = template_map.get(app_name)
    if not app_config:
        return render(request, "apps/not_found.html", {"app": app_name})

    if role not in app_config["allowed_roles"]:
        return HttpResponseForbidden("🚫 Not authorized for this section.")

    # bmmu fragment context for simple fragments
    if app_name == "bmmu":
        context = _bmmu_fragment_context(request)
        html = render_to_string(app_config["template"], context, request=request)
        return HttpResponse(html)

    # bmmu_add
    if app_name == "bmmu_add":
        BeneficiaryForm = modelform_factory(Beneficiary, exclude=[])
        context = {"form": BeneficiaryForm()}
        html = render_to_string(app_config["template"], context, request=request)
        return HttpResponse(html)

    # bmmu_delete
    if app_name == "bmmu_delete":
        context = _bmmu_fragment_context(request, paginate=True)
        html = render_to_string(app_config["template"], context, request=request)
        return HttpResponse(html)

    # tms branch: build same rich context as training_program_management
    if app_name == "tms":
        themes = []
        modules_map = {}
        partners = []
        beneficiaries = []
        trainers = []
        trainers_map = {}
        batches = []
        try:
            # themes distinct
            themes_qs = TrainingPlan.objects.values_list('theme', flat=True).distinct()
            themes = [t for t in themes_qs if t]

            # modules -> use TrainingPlan.id as module id (client expects id)
            tp_qs = TrainingPlan.objects.all().only('id', 'theme', 'training_name', 'no_of_days')[:2000]
            for tp in tp_qs:
                th = tp.theme or ''
                mod_entry = {
                    'id': tp.id,
                    'name': tp.training_name or f'Plan {tp.id}',
                    'days': getattr(tp, 'no_of_days', None) or ''
                }
                modules_map.setdefault(th, []).append(mod_entry)

            # partners
            partners_qs = TrainingPartner.objects.all()[:200]
            partners = [{'id': p.id, 'name': p.name} for p in partners_qs]

            # beneficiaries
            ben_qs = Beneficiary.objects.all()[:500]
            beneficiaries = [
                {
                    'id': b.id,
                    'member_name': getattr(b, 'member_name', '') or str(b),
                    'shg_name': getattr(b, 'shg_name', '') or '',
                    'village': getattr(b, 'village', '') or '',
                    'district': getattr(b, 'district', '') or '',
                    'mobile': getattr(b, 'mobile_no', '') or getattr(b, 'mobile', '') or '',
                    'category': getattr(b, 'social_category', '') or ''
                } for b in ben_qs
            ]

            # trainers (MasterTrainer)
            mt_qs = MasterTrainer.objects.all().prefetch_related('certificates')[:1000]
            trainers = []
            for t in mt_qs:
                # get latest certificate_number (prefer issued_on then id)
                cert_num = ''
                # certificates related_name is 'certificates' per your model
                latest = None
                try:
                    # attempt to find the latest using issued_on then id
                    latest = next(iter(sorted(t.certificates.all(), key=lambda c: ((c.issued_on or ''), c.id), reverse=True)), None)
                except Exception:
                    # fallback: use queryset ordering
                    latest_q = t.certificates.order_by('-issued_on', '-id').values_list('certificate_number', flat=True)
                    cert_num = latest_q.first() or ''
                else:
                    if latest:
                        cert_num = latest.certificate_number or ''

                trainers.append({
                    'id': t.id,
                    'full_name': t.full_name,
                    'certificate_number': cert_num,
                    'skills': getattr(t, 'skills', '') or ''
                })

            # trainers_map: explicit MasterTrainerExpertise if available
            try:
                # Import locally to avoid hard import error if model isn't added everywhere
                from .models import MasterTrainerExpertise
                for e in MasterTrainerExpertise.objects.select_related('trainer', 'training_plan').all():
                    tp_id = e.training_plan_id
                    trainers_map.setdefault(tp_id, [])
                    if e.trainer_id not in trainers_map[tp_id]:
                        trainers_map[tp_id].append(e.trainer_id)
            except Exception:
                # Model may not exist or not populated — ignore and fallback to skill matching
                pass

            # Build quick tokens for skills matching
            trainer_skill_tokens = {}
            for t in mt_qs:
                tokens = set()
                sk = getattr(t, 'skills', '') or ''
                for tok in [x.strip().lower() for x in sk.split(',') if x.strip()]:
                    tokens.add(tok)
                trainer_skill_tokens[t.id] = tokens

            # Fallback: match trainers whose token intersects training name/theme tokens
            for tp in tp_qs:
                tp_id = tp.id
                trainers_map.setdefault(tp_id, [])
                name_tokens = set([tok.strip().lower() for tok in ((tp.training_name or '') + ' ' + (tp.theme or '')).split() if tok.strip()])
                if name_tokens:
                    for t_id, toks in trainer_skill_tokens.items():
                        if toks and (toks & name_tokens):
                            if t_id not in trainers_map[tp_id]:
                                trainers_map[tp_id].append(t_id)

            # Live batches: ONGOING / PENDING if present otherwise recent
            batch_status_choices = []
            try:
                batch_status_choices = [c[0] for c in Batch._meta.get_field('status').choices]
            except Exception:
                batch_status_choices = []
            statuses_of_interest = [s for s in ('ONGOING', 'PENDING') if s in batch_status_choices]

            # select related only on fields that actually exist on Batch
            # Batch has 'request' and 'centre' FKs; training_plan and partner live on request
            base_qs = Batch.objects.select_related('request', 'centre')

            if statuses_of_interest:
                batch_qs = base_qs.filter(status__in=statuses_of_interest)[:200]
            else:
                batch_qs = base_qs.order_by('-created_at')[:50]

            # prefetch the training_plan and partner via request to avoid extra queries
            batch_qs = batch_qs.prefetch_related('request__training_plan', 'request__partner')

            for b in batch_qs:
                tp = None
                try:
                    tp = getattr(b.request, 'training_plan', None)
                except Exception:
                    tp = None
                batches.append({
                    'id': b.id,
                    'code': b.code or f'Batch-{b.id}',
                    'theme': getattr(tp, 'theme', '') if tp else '',
                    'module': getattr(tp, 'training_name', '') if tp else '',
                    'start': b.start_date.isoformat() if b.start_date else None,
                    'end': b.end_date.isoformat() if b.end_date else None,
                    'days': getattr(tp, 'no_of_days', None) if tp else None,
                    'trainers_count': b.trainers.count() if hasattr(b, 'trainers') else 0,
                    'participants_count': b.beneficiaries.count() if hasattr(b, 'beneficiaries') else 0,
                    'status': b.status
                })

        except Exception as e:
            logger.exception("load_app_content (tms): failed to build context: %s", e)

        context = {
            'role': role,
            'themes_json': json.dumps(themes, default=str),
            'modules_map_json': json.dumps(modules_map, default=str),
            'partners_json': json.dumps(partners, default=str),
            'beneficiaries_json': json.dumps(beneficiaries, default=str),
            'trainers_json': json.dumps(trainers, default=str),
            'trainers_map_json': json.dumps(trainers_map, default=str),
            'batches_json': json.dumps(batches, default=str),
        }
        html = render_to_string(app_config["template"], context, request=request)
        return HttpResponse(html)

    # fallback
    context = {"role": role}
    html = render_to_string(app_config["template"], context, request=request)
    return HttpResponse(html)


@login_required
def bmmu_trainings_list(request):
    if getattr(request.user, 'role', '').lower() != 'bmmu':
        return HttpResponseForbidden("Not authorized")

    assigned_block = None
    try:
        assignment = BmmuBlockAssignment.objects.filter(user=request.user).select_related('block').first()
        if assignment:
            assigned_block = assignment.block
    except Exception:
        assigned_block = None

    qs = TrainingRequest.objects.none()
    try:
        # Build base qs depending on assigned_block (same logic as before)
        if assigned_block:
            try:
                if request.user:
                    qs_block = TrainingRequest.objects.filter(level__iexact='BLOCK', created_by=request.user)
                else:
                    qs_block = TrainingRequest.objects.none()
            except Exception:
                qs_block = TrainingRequest.objects.none()

            try:
                qs_other = TrainingRequest.objects.filter(block=assigned_block)
            except Exception:
                qs_other = TrainingRequest.objects.none()
        else:
            qs_block = TrainingRequest.objects.none()
            qs_other = TrainingRequest.objects.none()

        qs = (qs_block | qs_other).distinct().order_by('-created_at')

        # Read status filter from GET param (case-insensitive)
        requested_status = (request.GET.get('status') or '').strip().upper()

        # Valid status tokens derived from model choices
        VALID_STATUSES = [c[0].upper() for c in getattr(TrainingRequest, 'STATUS_CHOICES', [])]

        # If a status filter is provided and valid, apply it.
        if requested_status:
            if requested_status in VALID_STATUSES:
                qs = qs.filter(status__iexact=requested_status)
            else:
                # invalid filter -> zero results (do not fallback)
                qs = TrainingRequest.objects.none()
        else:
            # No explicit status filter: keep existing fallback behavior if qs empty
            if not qs.exists():
                qs = TrainingRequest.objects.filter(level__iexact='BLOCK').order_by('-created_at')[:200]

        # Annotate beneficiary counts for faster rendering
        try:
            # If qs is a sliced queryset (like [:200]) it's a list, so guard:
            if hasattr(qs, 'annotate'):
                qs = qs.annotate(beneficiary_count=Count('beneficiaries'))
            else:
                # convert list to queryset-like list of objects and manually add beneficiary_count attribute
                # but simplest safe fallback: loop and attach count attribute
                for tr in qs:
                    try:
                        tr.beneficiary_count = tr.beneficiaries.count()
                    except Exception:
                        tr.beneficiary_count = 0
        except Exception:
            logger.exception("bmmu_trainings_list: annotation failed")
    except Exception as e:
        logger.exception("bmmu_trainings_list: unexpected error building queryset: %s", e)
        qs = TrainingRequest.objects.none()

    # Prepare status choices for template (include an 'ALL' option)
    status_choices = [('','All')] + [(c[0], c[1]) for c in getattr(TrainingRequest, 'STATUS_CHOICES', [])]

    fragment = render_to_string('bmmu_view_trainings.html', {
        'requests': qs,
        'status_choices': status_choices,
        'selected_status': requested_status,
    }, request=request)
    return render(request, 'dashboard.html', {'user': request.user, 'default_content': fragment})
    

@login_required
def bmmu_request_detail(request, request_id):
    """
    Render the BMMU training-request fragment INSIDE dashboard.html
    so the dashboard chrome (navbar/sidebar/footer) remains.
    """
    if getattr(request.user, 'role', '').lower() != 'bmmu':
        return HttpResponseForbidden("Not authorized")

    tr = get_object_or_404(
        TrainingRequest.objects.select_related('training_plan', 'partner', 'created_by'),
        id=request_id
    )

    if not tr.created_by or tr.created_by.id != request.user.id:
        return HttpResponseForbidden("Not authorized to view this request")

    try:
        batches_qs = Batch.objects.filter(request=tr)\
            .select_related('centre')\
            .prefetch_related('batch_beneficiaries__beneficiary', 'trainerparticipations__trainer', 'attendances')\
            .order_by('start_date', 'id')
    except Exception as e:
        logger.exception("bmmu_request_detail: error fetching batches for request %s: %s", tr.id, e)
        batches_qs = Batch.objects.none()

    batch_details = []
    for b in batches_qs:
        try:
            beneficiaries = [bb.beneficiary for bb in b.batch_beneficiaries.select_related('beneficiary').all()]
        except Exception:
            beneficiaries = []
        try:
            attendance_dates = list(b.attendances.order_by('date').values_list('date', flat=True))
        except Exception:
            attendance_dates = []
        centre = getattr(b, 'centre', None)
        batch_details.append({
            'batch': b,
            'centre': centre,
            'beneficiaries': beneficiaries,
            'attendance_dates': attendance_dates,
        })

    try:
        participants = list(tr.beneficiaries.all())
    except Exception:
        participants = []

    # minimal enrichment for display
    try:
        india_tz = ZoneInfo("Asia/Kolkata")
    except Exception:
        india_tz = None
    today = datetime.now(tz=india_tz).date() if india_tz else timezone.localdate()
    
    for p in participants:
        dob = getattr(p, 'date_of_birth', None)
        age = None
        if dob:
            try:
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            except Exception:
                age = None
        setattr(p, 'age', age)
        display_name = getattr(p, 'member_name', None) or getattr(p, 'full_name', None) or getattr(p, 'member_code', None) or str(p)
        setattr(p, 'display_name', display_name)
        mobile = getattr(p, 'mobile_number', None) or getattr(p, 'mobile_no', None) or getattr(p, 'mobile', None) or ''
        setattr(p, 'display_mobile', mobile)
        try:
            loc_parts = []
            v = getattr(p, 'village', None)
            if v:
                loc_parts.append(str(v))
            b = getattr(p, 'block', None)
            if b:
                loc_parts.append(getattr(b, 'block_name_en', str(b)))
            setattr(p, 'display_location', ", ".join([x for x in loc_parts if x]))
        except Exception:
            setattr(p, 'display_location', '')

    fragment = render_to_string('bmmu_training_detail.html', {
        'training_request': tr,
        'batches': batch_details,
        'participants': participants,
    }, request=request)

    return render(request, 'dashboard.html', {'user': request.user, 'default_content': fragment})


@login_required
def bmmu_batch_view(request, batch_id):
    """
    Render batch page INSIDE dashboard.html (so the dashboard chrome persists).
    """
    if getattr(request.user, 'role', '').lower() != 'bmmu':
        return HttpResponseForbidden("Not authorized")

    try:
        b = Batch.objects.select_related('request__created_by', 'request__training_plan', 'centre')\
            .prefetch_related(
                'batch_beneficiaries__beneficiary',
                'trainerparticipations__trainer',
                'attendances__participant_records'
            ).get(id=batch_id)
    except Batch.DoesNotExist:
        return HttpResponseForbidden("Batch not found or not accessible")
    except Exception as e:
        logger.exception("bmmu_batch_view: DB error fetching batch %s: %s", batch_id, e)
        return HttpResponseForbidden("Server error")

    try:
        if not b.request or not b.request.created_by or b.request.created_by.id != request.user.id:
            return HttpResponseForbidden("Not authorized to view this batch")
    except Exception:
        return HttpResponseForbidden("Not authorized")

    try:
        beneficiaries = [bb.beneficiary for bb in b.batch_beneficiaries.select_related('beneficiary').all()]
    except Exception:
        beneficiaries = []

    try:
        trainers = [tp.trainer for tp in b.trainerparticipations.select_related('trainer').all()]
    except Exception:
        trainers = []

    try:
        attendance_dates = list(b.attendances.order_by('date').values_list('date', flat=True))
    except Exception:
        attendance_dates = []

    centre_info = {}
    try:
        c = b.centre
        if c:
            centre_info = {
                'venue_name': getattr(c, 'venue_name', None),
                'venue_address': getattr(c, 'venue_address', None),
                'serial_number': getattr(c, 'serial_number', None),
                'coord_name': getattr(c, 'centre_coord_name', None),
                'coord_mobile': getattr(c, 'centre_coord_mob_number', None),
            }
    except Exception:
        centre_info = {}

    fragment = render_to_string('bmmu_batch_detail.html', {
        'batch': b,
        'beneficiaries': beneficiaries,
        'trainers': trainers,
        'attendance_dates': attendance_dates,
        'centre_info': centre_info,
    }, request=request)

    return render(request, 'dashboard.html', {'user': request.user, 'default_content': fragment})


@login_required
@require_http_methods(["GET"])
def bmmu_batch_attendance_date(request, batch_id, date_str):
    """
    AJAX attendance fetch (unchanged) - returns JSON with html fragment.
    """
    if getattr(request.user, 'role', '').lower() != 'bmmu':
        return HttpResponseForbidden("Not authorized")

    raw = unquote(date_str or '').strip()
    the_date = None
    parse_attempts = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]
    for fmt in parse_attempts:
        try:
            the_date = datetime.datetime.strptime(raw, fmt).date()
            break
        except Exception:
            continue
    if the_date is None:
        try:
            the_date = datetime.date.fromisoformat(raw.split('T')[0])
        except Exception:
            try:
                from dateutil import parser as _du_parser
                the_date = _du_parser.parse(raw).date()
            except Exception:
                the_date = None

    if the_date is None:
        return JsonResponse({'ok': False, 'error': f'Invalid date: {date_str}'}, status=400)

    try:
        att = BatchAttendance.objects.select_related('batch').prefetch_related('participant_records').get(batch_id=batch_id, date=the_date)
    except BatchAttendance.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Attendance not found'}, status=404)
    except Exception as e:
        logger.exception("bmmu_batch_attendance_date: DB error for batch %s date %s: %s", batch_id, the_date, e)
        return JsonResponse({'ok': False, 'error': 'Server error'}, status=500)

    try:
        if not att.batch or not getattr(att.batch, 'request', None) or not getattr(att.batch.request, 'created_by', None) or att.batch.request.created_by.id != request.user.id:
            return HttpResponseForbidden("Not authorized to view this attendance")
    except Exception:
        return HttpResponseForbidden("Not authorized")

    try:
        html = render_to_string('bmmu/partials/attendance_list.html', {'attendance': att}, request=request)
        return JsonResponse({'ok': True, 'html': html})
    except Exception as e:
        logger.exception("bmmu_batch_attendance_date: render error: %s", e)
        return JsonResponse({'ok': False, 'error': 'Render error'}, status=500)

def _apply_search_filter_sort(queryset, params):
    """
    Apply search, filters and sorting via GET params.

    This function now guarantees that the returned queryset is a normal
    Beneficiary model queryset (not a values/annotated queryset), by
    re-querying the model using the PKs after filters are applied.
    """
    from django.db.models import CharField, TextField, ForeignKey
    from django.db.models.query import QuerySet

    # Whitelist of fields allowed for global search (text-like fields only)
    allowed_search_fields = {"member_name", "shg_name", "gram_panchayat", "village"}
    # Additional exact/partial extras
    extras_icontains = {"mobile_no", "aadhaar_no", "member_lokos_code", "shg_lokos_code"}

    search = params.get("search", "").strip()
    if search:
        q_obj = Q()
        model_fields = {f.name: f for f in Beneficiary._meta.fields}
        # search only allowed text fields
        for f in allowed_search_fields:
            if f in model_fields:
                fld_obj = model_fields[f]
                # only if field is char/text-like
                if isinstance(fld_obj, (CharField, TextField)):
                    q_obj |= Q(**{f"{f}__icontains": search})
        # extras: mobile/aadhaar etc.
        for extra in extras_icontains:
            if extra in model_fields:
                q_obj |= Q(**{f"{extra}__icontains": search})
        queryset = queryset.filter(q_obj)

    # Filters passed as filter_<field>=value
    model_fields = {f.name: f for f in Beneficiary._meta.fields}
    for key, val in params.items():
        if not key.startswith("filter_") or not val:
            continue
        field = key.replace("filter_", "")
        if field not in model_fields:
            continue

        fld_obj = model_fields[field]
        # multiple values comma separated
        if "," in val:
            values = [v.strip() for v in val.split(",") if v.strip()]
            if not values:
                continue
            # If field is FK, attempt to use <field>_id if provided numeric ids, otherwise skip FK filtering
            if isinstance(fld_obj, ForeignKey):
                int_vals = []
                for vv in values:
                    try:
                        int_vals.append(int(vv))
                    except Exception:
                        # non-int value: cannot safely filter FK by non-id -> skip
                        int_vals = []
                        break
                if int_vals:
                    queryset = queryset.filter(**{f"{field}_id__in": int_vals})
                # otherwise skip FK filter
            else:
                queryset = queryset.filter(**{f"{field}__in": values})
        else:
            # single value
            single = val.strip()
            if isinstance(fld_obj, (CharField, TextField)):
                # partial match for text fields
                queryset = queryset.filter(**{f"{field}__icontains": single})
            elif isinstance(fld_obj, ForeignKey):
                # if value looks like integer, match by id; else skip to avoid FieldError
                try:
                    iid = int(single)
                except Exception:
                    # skip FK filter (frontend shouldn't be sending names for FK fields)
                    continue
                else:
                    queryset = queryset.filter(**{f"{field}_id": iid})
            else:
                # fallback to case-insensitive exact for other field types
                queryset = queryset.filter(**{f"{field}__iexact": single})

    # --- COERCE BACK TO A NORMAL MODEL QUERYSET ---
    try:
        # If queryset is already a QuerySet of models (has .model and model is Beneficiary),
        # we still re-query to be safe (ensures instance objects, not values/annotations).
        if isinstance(queryset, QuerySet):
            # collect current PKs (this works for normal queryset and many annotated querysets)
            pk_list = list(queryset.values_list('pk', flat=True))
            # Rebuild a fresh model queryset preserving only these PKs
            if pk_list:
                queryset = Beneficiary.objects.filter(pk__in=pk_list).select_related('district', 'block')
            else:
                # empty result: return empty queryset of model
                queryset = Beneficiary.objects.none()
        else:
            # Not a Django QuerySet (unlikely) — try to leave it untouched
            pass
    except Exception:
        # In case anything goes wrong, fallback to original queryset (avoid crashing)
        try:
            queryset = Beneficiary.objects.filter(pk__in=list(queryset.values_list('pk', flat=True)))
        except Exception:
            # ultimate fallback: full set (safe but broader)
            queryset = Beneficiary.objects.all().select_related('district', 'block')

    # Sorting
    sort_by = params.get("sort_by", "")
    order = params.get("order", "asc")
    model_field_names = [f.name for f in Beneficiary._meta.fields]
    if sort_by and sort_by in model_field_names:
        if order == "desc":
            queryset = queryset.order_by(f"-{sort_by}")
        else:
            queryset = queryset.order_by(sort_by)
    else:
        queryset = queryset.order_by("id")

    return queryset


def _bmmu_fragment_context(request, paginate=True):
    """
    Build context dict for bmmu fragment(s).

    NOTE: If current user is role 'bmmu', restrict beneficiaries to block(s)
    assigned to that BMMU via BmmuBlockAssignment.
    """
    chart1 = [random.randint(0, 100) for _ in range(10)]
    chart2 = [random.randint(0, 100) for _ in range(10)]
    chart_labels = [f'Metric {i+1}' for i in range(10)]

    # Start with full queryset, then restrict if current user is a BMMU.
    beneficiaries_qs = Beneficiary.objects.all()
    all_qs_for_groupables = Beneficiary.objects.all()

    # If the logged-in user is a BMMU, restrict to assigned block(s).
    try:
        user_role = getattr(request.user, "role", "").lower()
        if user_role == "bmmu":
            assigned_block_ids = list(
                BmmuBlockAssignment.objects.filter(user=request.user)
                .values_list("block_id", flat=True)
            )
            if assigned_block_ids:
                beneficiaries_qs = beneficiaries_qs.filter(block_id__in=assigned_block_ids)
                all_qs_for_groupables = all_qs_for_groupables.filter(block_id__in=assigned_block_ids)
            else:
                # No assigned blocks: restrict to empty queryset (BMMU sees nothing).
                beneficiaries_qs = beneficiaries_qs.none()
                all_qs_for_groupables = all_qs_for_groupables.none()
    except Exception:
        # Fail-safe: if anything unexpected happens, log and keep full queryset
        logger.exception("Failed to apply BMMU block restriction; falling back to full dataset.")
        beneficiaries_qs = Beneficiary.objects.all()
        all_qs_for_groupables = Beneficiary.objects.all()

    groupable_fields = [
        "district", "block", "gram_panchayat", "village",
        "shg_name", "designation_in_shg_vo_clf",
        "social_category", "gender", "marital_status",
        "bank_name", "bank_loan_status", "cadres_role"
    ]

    groupable_values = {}
    model_fields = [f.name for f in Beneficiary._meta.fields]
    for fld in groupable_fields:
        if fld in model_fields:
            vals = list(all_qs_for_groupables.order_by(fld).values_list(fld, flat=True).distinct())
            vals = [v for v in vals if v is not None and str(v).strip() != ""]
            if len(vals) > 500:
                vals = vals[:500]
            groupable_values[fld] = vals

    # Apply search / filters / sorting on the (possibly restricted) beneficiaries_qs
    beneficiaries_qs = _apply_search_filter_sort(beneficiaries_qs, request.GET)

    if paginate:
        paginator = Paginator(beneficiaries_qs, 20)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
    else:
        paginator = None
        page_obj = beneficiaries_qs

    field_list = [(f.name, f.verbose_name) for f in Beneficiary._meta.fields]
    groupable_values_json = json.dumps(groupable_values, default=str)
    chart1_json = json.dumps(chart1)
    chart2_json = json.dumps(chart2)
    chart_labels_json = json.dumps(chart_labels)

    return {
        "chart1": chart1,
        "chart2": chart2,
        "chart_labels": chart_labels,
        "chart1_json": chart1_json,
        "chart2_json": chart2_json,
        "chart_labels_json": chart_labels_json,
        "page_obj": page_obj,
        "paginator": paginator,
        "field_list": field_list,
        "search_query": request.GET.get("search", ""),
        "sort_by": request.GET.get("sort_by", ""),
        "order": request.GET.get("order", "asc"),
        "groupable_values": groupable_values,
        "groupable_values_json": groupable_values_json,
    }

def bmmu_beneficiary_detail(request, pk):
    """
    Return JSON with all fields for beneficiary `pk`.

    - Only authenticated users may access.
    - If user.role == 'bmmu', ensure the beneficiary's block is assigned to that BMMU.
    """
    from datetime import date, datetime
    from django.http import Http404
    if not request.user.is_authenticated:
        return HttpResponseForbidden("Authentication required")

    try:
        beneficiary = Beneficiary.objects.select_related('district', 'block').get(pk=pk)
    except Beneficiary.DoesNotExist:
        raise Http404("Beneficiary not found")

    # If role is bmmu, ensure this beneficiary is in one of their assigned blocks
    user_role = getattr(request.user, "role", "").lower()
    if user_role == "bmmu":
        assigned_block_ids = list(
            BmmuBlockAssignment.objects.filter(user=request.user)
            .values_list("block_id", flat=True)
        )
        if not assigned_block_ids or (beneficiary.block_id not in assigned_block_ids):
            return HttpResponseForbidden("Not allowed")

    # Build a JSON-safe dict of fields (convert dates / complex objects to strings)
    data = {}
    for f in Beneficiary._meta.fields:
        name = f.name
        try:
            val = getattr(beneficiary, name)
        except Exception:
            val = None

        if val is None:
            data[name] = None
        elif isinstance(val, (date, datetime)):
            data[name] = val.isoformat()
        elif isinstance(val, (int, float, bool, str)):
            data[name] = val
        else:
            # related objects or other complex types -> stringify
            try:
                data[name] = str(val)
            except Exception:
                data[name] = None

    return JsonResponse({"ok": True, "data": data})

@require_http_methods(["POST"])
@login_required
def bmmu_beneficiary_update(request, pk):
    """
    Robust update endpoint for Beneficiary used by the AJAX edit modal.
    Accepts JSON or form-encoded POST. Supports client-side aliases (phone_number -> mobile_no, aadhaar_number -> aadhaar_no).
    Returns JSON {ok, data, message} or {ok: False, error}.
    """
    # fetch the beneficiary
    try:
        beneficiary = Beneficiary.objects.select_related('district', 'block').get(pk=pk)
    except Beneficiary.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Beneficiary not found."}, status=404)

    # permission check (same as detail)
    user_role = getattr(request.user, "role", "").lower()
    if user_role == "bmmu":
        assigned_block_ids = list(
            BmmuBlockAssignment.objects.filter(user=request.user)
            .values_list("block_id", flat=True)
        )
        if not assigned_block_ids or (beneficiary.block_id not in assigned_block_ids):
            return JsonResponse({"ok": False, "error": "Not allowed"}, status=403)

    # Read incoming data
    data = {}
    content_type = (request.META.get('CONTENT_TYPE') or request.content_type or '').lower()
    if content_type.startswith('application/json'):
        try:
            data = json.loads(request.body.decode('utf-8') or "{}")
        except Exception as e:
            logger.exception("Invalid JSON payload for beneficiary update: %s", e)
            return JsonResponse({"ok": False, "error": "Invalid JSON payload"}, status=400)
    else:
        data = request.POST.dict()

    if not data:
        return JsonResponse({"ok": False, "error": "No data provided"}, status=400)

    # Model fields set
    model_field_names = {f.name for f in Beneficiary._meta.fields}

    # Client aliases -> actual model fields
    ALIAS_MAP = {
        'phone_number': 'mobile_no',
        'mobile_no': 'mobile_no',
        'aadhaar_number': 'aadhaar_no',
        'aadhaar_no': 'aadhaar_no',
        'aadhar_kyc': 'aadhar_kyc',
        # add other friendly aliases here if needed
    }

    # Build a mapped dict: map incoming keys to actual model field names
    mapped = {}
    for key, val in data.items():
        # prefer direct match
        if key in model_field_names:
            mapped[key] = val
            continue
        # try alias
        if key in ALIAS_MAP:
            tgt = ALIAS_MAP[key]
            if tgt in model_field_names:
                mapped[tgt] = val
                continue
        # also check lowercase/no-space variants if needed
        low = key.lower().replace(' ', '_')
        if low in model_field_names:
            mapped[low] = val
            continue
        if low in ALIAS_MAP:
            tgt = ALIAS_MAP[low]
            if tgt in model_field_names:
                mapped[tgt] = val
                continue
        # otherwise ignore unknown field

    if not mapped:
        return JsonResponse({"ok": False, "error": "No valid editable fields provided."}, status=400)

    # Optional: explicit whitelist of editable fields (keeps control)
    EDITABLE_WHITELIST = {
        'member_name','date_of_birth','shg_name','social_category',
        'designation_in_shg_vo_clf','religion','gender','gram_panchayat',
        'village','mobile_no','aadhaar_no','aadhar_kyc'
    }
    writable = [k for k in mapped.keys() if k in model_field_names and (k in EDITABLE_WHITELIST)]

    # If whitelist filtered everything out, allow intersection with model fields (more permissive)
    if not writable:
        writable = [k for k in mapped.keys() if k in model_field_names]

    if not writable:
        return JsonResponse({"ok": False, "error": "No writable fields after filtering."}, status=400)

    changed = {}
    for key in writable:
        raw_val = mapped.get(key)
        if raw_val == '':
            val = None
        else:
            val = raw_val

        # convert date_of_birth if provided
        if key == 'date_of_birth' and val:
            parsed = parse_date(val)  # returns date or None
            if parsed:
                val = parsed
            # else leave as-is and let validation catch it

        try:
            old = getattr(beneficiary, key)
        except Exception:
            old = None

        # Compare and set (note: DB fields might be date objects)
        try:
            if old != val:
                setattr(beneficiary, key, val)
                changed[key] = {'old': old, 'new': val}
        except Exception as e:
            logger.exception("Failed to set attribute %s on Beneficiary %s: %s", key, pk, e)

    if not changed:
        return JsonResponse({"ok": True, "data": {}, "message": "No changes detected."})

    # Validate + save
    try:
        beneficiary.full_clean()
        beneficiary.save()
    except ValidationError as ve:
        logger.warning("Validation error updating beneficiary %s: %s", pk, ve)
        return JsonResponse({"ok": False, "error": ve.message_dict}, status=400)
    except Exception as e:
        logger.exception("Error saving beneficiary %s: %s", pk, e)
        return JsonResponse({"ok": False, "error": str(e)}, status=500)

    logger.info("Beneficiary %s updated fields: %s by user=%s", pk, list(changed.keys()), request.user.username)

    resp_data = {}
    for f in writable:
        val = getattr(beneficiary, f, None)
        if hasattr(val, 'isoformat'):
            resp_data[f] = val.isoformat()
        else:
            resp_data[f] = val

    return JsonResponse({"ok": True, "data": resp_data, "message": "Successfully updated beneficiary details!"})

@login_required
def bmmu_dashboard(request):
    if getattr(request.user, "role", "").lower() != 'bmmu':
        return HttpResponseForbidden("🚫 Not authorized for this dashboard.")

    if request.method == "POST" and request.FILES.get("import_file"):
        import_file = request.FILES["import_file"]
        dataset = BeneficiaryResource().import_data(import_file, dry_run=True)
        if not dataset.has_errors():
            BeneficiaryResource().import_data(import_file, dry_run=False)
            messages.success(request, "Beneficiaries imported successfully!")
            return redirect("dashboard")
        else:
            messages.error(request, "Errors found in import file. Please check and retry.")
            return redirect("dashboard")

    if 'export' in request.GET:
        dataset = BeneficiaryResource().export()
        response = HttpResponse(
            dataset.xlsx,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="beneficiaries.xlsx"'
        return response

    if 'blueprint' in request.GET:
        return export_blueprint(BeneficiaryResource, "beneficiaries_blueprint.xlsx")

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        context = _bmmu_fragment_context(request)
        html = render_to_string("bmmu_dashboard.html", context, request=request)
        return HttpResponse(html)

    return redirect("dashboard")


@login_required
def bmmu_add_beneficiary(request):
    if getattr(request.user, "role", "").lower() != 'bmmu':
        return HttpResponseForbidden("🚫 Not authorized.")

    BeneficiaryForm = modelform_factory(Beneficiary, exclude=[])

    if request.method == "POST":
        form = BeneficiaryForm(request.POST, request.FILES or None)
        if form.is_valid():
            form.save()
            messages.success(request, "Beneficiary added.")
            if request.POST.get("save_and_add_next"):
                form = BeneficiaryForm()
                context = {"form": form, "just_saved": True}
                html = render_to_string("bmmu_add_beneficiary.html", context, request=request)
                return HttpResponse(html)
            else:
                return redirect("dashboard")
    else:
        form = BeneficiaryForm()

    context = {"form": form}
    html = render_to_string("bmmu_add_beneficiary.html", context, request=request)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return HttpResponse(html)
    return redirect("dashboard")


@login_required
def bmmu_delete_beneficiaries(request):
    if getattr(request.user, "role", "").lower() != 'bmmu':
        return HttpResponseForbidden("🚫 Not authorized.")
    
    if request.method == "POST":
        ids = request.POST.getlist("delete_ids[]") or request.POST.getlist("delete_ids")
        if ids:
            qs = Beneficiary.objects.filter(id__in=ids)
            count = qs.count()
            qs.delete()
            messages.success(request, f"Deleted {count} beneficiaries.")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"deleted": count})
        else:
            messages.error(request, "No beneficiaries selected for deletion.")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"error": "No beneficiaries selected"}, status=400)
        return redirect("dashboard")

@login_required
def training_program_management(request):
    """
    AJAX fragment for TMS. If request is AJAX (X-Requested-With), return the fragment HTML
    with JSON-serializable lists:
      - themes_json: list of theme ids/names
      - modules_map_json: mapping theme -> list of {id,name,days}
      - partners_json: list of {id,name}
      - beneficiaries_json: list of beneficiary dicts (id,member_name,shg_name,...)
      - trainers_json: list of trainers (id, full_name, skills, certificate_number)
      - trainers_map_json: mapping training_plan.id -> [trainer_id,...]
      - batches_json: list of current batches (live)
    If non-AJAX, redirect to wrapper dashboard.
    """
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        themes = []
        modules_map = {}
        partners = []
        beneficiaries = []
        trainers = []
        trainers_map = {}
        batches = []
        try:
            # themes: distinct theme names (safe)
            themes_qs = TrainingPlan.objects.values_list('theme', flat=True).distinct()
            themes = [t for t in themes_qs if t]

            # Build a modules map: treat each TrainingPlan.training_name as a module entry
            tp_qs = TrainingPlan.objects.all().only('id', 'theme', 'training_name', 'no_of_days')[:2000]
            for tp in tp_qs:
                th = tp.theme or ''
                mod_entry = {
                    'id': tp.id,
                    'name': tp.training_name or f'Plan {tp.id}',
                    'days': getattr(tp, 'no_of_days', None) or ''
                }
                modules_map.setdefault(th, []).append(mod_entry)

            # partners list (limited)
            partners_qs = TrainingPartner.objects.all()[:200]
            partners = [{'id': p.id, 'name': p.name} for p in partners_qs]

            # beneficiaries list (limited)
            ben_qs = Beneficiary.objects.all()[:500]
            beneficiaries = [
                {
                    'id': b.id,
                    'member_name': getattr(b, 'member_name', '') or str(b),
                    'shg_name': getattr(b, 'shg_name', '') or '',
                    'village': getattr(b, 'village', '') or '',
                    'district': getattr(b, 'district', '') or '',
                    'mobile': getattr(b, 'mobile_no', '') or getattr(b, 'mobile', '') or '',
                    'category': getattr(b, 'social_category', '') or ''
                } for b in ben_qs
            ]

            # trainers: all master trainers (limited)
            mt_qs = MasterTrainer.objects.all().prefetch_related('certificates')[:1000]
            trainers = []
            for t in mt_qs:
                cert_num = ''
                latest = None
                try:
                    latest = next(iter(sorted(t.certificates.all(), key=lambda c: ((c.issued_on or ''), c.id), reverse=True)), None)
                except Exception:
                    latest_q = t.certificates.order_by('-issued_on', '-id').values_list('certificate_number', flat=True)
                    cert_num = latest_q.first() or ''
                else:
                    if latest:
                        cert_num = latest.certificate_number or ''

                trainers.append({
                    'id': t.id,
                    'full_name': t.full_name,
                    'certificate_number': cert_num,
                    'skills': (t.skills or '')
                })

            # trainers_map: first use explicit MasterTrainerExpertise if present
            # fall back to matching trainer.skills contains training_name or theme tokens
            try:
                # explicit expertise entries
                for e in MasterTrainerExpertise.objects.select_related('trainer', 'training_plan').all():
                    tp_id = e.training_plan_id
                    trainers_map.setdefault(tp_id, [])
                    if e.trainer_id not in trainers_map[tp_id]:
                        trainers_map[tp_id].append(e.trainer_id)
            except Exception:
                # if MasterTrainerExpertise model not present, ignore
                pass

            # fallback matching by skills: if modules_map entries exist, try to attach trainers by skills
            # build a quick lookup of trainers' skills tokens
            trainer_skill_tokens = {}
            for t in mt_qs:
                tokens = set()
                if t.skills:
                    for tok in [x.strip().lower() for x in t.skills.split(',') if x.strip()]:
                        tokens.add(tok)
                trainer_skill_tokens[t.id] = tokens

            # for each training plan, try to find trainers whose skills match training_name or theme
            for tp in tp_qs:
                tp_id = tp.id
                if tp_id not in trainers_map:
                    trainers_map[tp_id] = []
                search_candidates = []
                name_tokens = set([tok.strip().lower() for tok in ((tp.training_name or '') + ' ' + (tp.theme or '')).split() if tok.strip()])
                if name_tokens:
                    for t_id, toks in trainer_skill_tokens.items():
                        if toks and (toks & name_tokens):
                            if t_id not in trainers_map[tp_id]:
                                trainers_map[tp_id].append(t_id)

            # live batches: pick ONGOING and PENDING (common statuses)
            # Safe check if Batch model has expected fields
            batch_status_choices = [c[0] for c in Batch._meta.get_field('status').choices]
            statuses_of_interest = [s for s in ('ONGOING', 'PENDING') if s in batch_status_choices]
            if statuses_of_interest:
                batch_qs = Batch.objects.filter(status__in=statuses_of_interest).select_related('training_plan', 'partner')[:200]
            else:
                # fallback: show last 50 batches if none of those statuses exist
                batch_qs = Batch.objects.all().select_related('training_plan', 'partner').order_by('-created_at')[:50]

            for b in batch_qs:
                tp = getattr(b, 'training_plan', None)
                batches.append({
                    'id': b.id,
                    'code': b.code or f'Batch-{b.id}',
                    'theme': getattr(tp, 'theme', '') if tp else '',
                    'module': getattr(tp, 'training_name', '') if tp else '',
                    'start': b.start_date.isoformat() if b.start_date else None,
                    'end': b.end_date.isoformat() if b.end_date else None,
                    'days': getattr(tp, 'no_of_days', None) if tp else None,
                    'trainers_count': b.trainers.count() if hasattr(b, 'trainers') else 0,
                    'participants_count': b.beneficiaries.count() if hasattr(b, 'beneficiaries') else 0,
                    'status': b.status
                })
        except Exception as e:
            logger.exception("training_program_management: failed to load server data: %s", e)

        context = {
            'themes_json': json.dumps(themes, default=str),
            'modules_map_json': json.dumps(modules_map, default=str),
            'partners_json': json.dumps(partners, default=str),
            'beneficiaries_json': json.dumps(beneficiaries, default=str),
            'trainers_json': json.dumps(trainers, default=str),
            'trainers_map_json': json.dumps(trainers_map, default=str),
            'batches_json': json.dumps(batches, default=str),
        }
        html = render_to_string("apps/tms.html", context, request=request)
        return HttpResponse(html)

    # Non-AJAX: redirect to wrapper dashboard so UI/styling are intact
    return redirect("dashboard")

@login_required
def master_trainer_dashboard(request):
    """
    Dashboard for Master Trainer users. Mirrors Training Partner dashboard layout/behavior.
    """
    if getattr(request.user, "role", "").lower() != "master_trainer":
        return HttpResponseForbidden("Not authorized")

    mt = _get_trainer_for_user(request.user)
    if not mt:
        # Create a skeleton MasterTrainer record so profile editing is available.
        # Do not populate sensitive fields automatically; keep minimal data.
        mt = MasterTrainer.objects.create(
            user=request.user,
            full_name=request.user.get_full_name() or request.user.username
        )
        # refresh relation
        request.user.refresh_from_db()

    # Example KPIs / lists similar to TrainingPartner dashboard (non-exhaustive)
    # You can replace the dummy data with real ORM queries as needed.
    # For consistency with partner dashboard, attempt to show batches assigned to this trainer
    assigned_batches = Batch.objects.filter(trainerparticipations__trainer=mt).select_related('training_plan', 'partner').order_by('-start_date')[:50]

    # Ongoing batches for quick actions
    status_choices = [c[0] for c in Batch._meta.get_field('status').choices]
    ongoing_tokens = [t for t in status_choices if t.upper() == 'ONGOING' or t.lower() == 'ongoing']
    if ongoing_tokens:
        ongoing_qs = Batch.objects.filter(trainerparticipations__trainer=mt, status__in=ongoing_tokens).select_related('training_plan', 'partner').order_by('start_date')
    else:
        ongoing_qs = Batch.objects.none()

    # simple derived KPI values
    total_assigned = assigned_batches.count()
    upcoming_count = assigned_batches.filter(start_date__gte=timezone.now().date()).count() if assigned_batches else 0
    avg_attendance_pct = 0
    invoices_pending = 0

    context = {
        'master_trainer': mt,
        'assigned_batches': assigned_batches,
        'ongoing': ongoing_qs,
        'kpi_total_trainings': total_assigned,
        'kpi_upcoming': upcoming_count,
        'kpi_attendance_pct': avg_attendance_pct,
        'kpi_invoices': invoices_pending,
    }
    return render(request, 'master_trainer/dashboard.html', context)

@login_required
def master_trainer_education(request):
    if getattr(request.user, "role", "").lower() != "master_trainer":
        return HttpResponseForbidden("Not authorized")

    mt = _get_trainer_for_user(request.user)
    if not mt:
        mt = MasterTrainer.objects.create(user=request.user, full_name=request.user.get_full_name() or request.user.username)
        request.user.refresh_from_db()

    # show achievements editing (other_achievements on master_trainer)
    tab = request.GET.get('tab', 'achievements')

    # certificate form / list
    certs_qs = MasterTrainerCertificate.objects.filter(trainer=mt).order_by('-issued_on', '-id')

    if request.method == 'POST':
        # handle certificate upload form (we use a single POST endpoint here)
        if 'add_certificate' in request.POST:
            cert_form = MasterTrainerCertificateForm(request.POST, request.FILES)
            if cert_form.is_valid():
                cert = cert_form.save(commit=False)
                cert.trainer = mt
                cert.save()
                messages.success(request, "Certificate added.")
                return redirect(reverse('master_trainer_education') + '?tab=certificates')
            else:
                messages.error(request, "Fix errors in certificate form.")
        elif 'save_achievements' in request.POST:
            # update free-text 'other_achievements'
            other = request.POST.get('other_achievements', '')
            mt.other_achievements = other
            mt.save()
            messages.success(request, "Achievements saved.")
            return redirect(reverse('master_trainer_education') + '?tab=achievements')
    else:
        cert_form = MasterTrainerCertificateForm()

    context = {
        'master_trainer': mt,
        'tab': tab,
        'certs': certs_qs,
        'cert_form': cert_form,
    }
    return render(request, 'master_trainer/education.html', context)


@login_required
def master_trainer_certificate_delete(request, pk):
    if getattr(request.user, "role", "").lower() != "master_trainer":
        return HttpResponseForbidden("Not authorized")
    cert = get_object_or_404(MasterTrainerCertificate, pk=pk, trainer__user=request.user)
    if request.method == 'POST':
        cert.delete()
        messages.success(request, "Certificate removed.")
        return redirect(reverse('master_trainer_education') + '?tab=certificates')
    # if GET, show a simple confirm page or redirect
    return render(request, 'master_trainer/certificate_confirm_delete.html', {'cert': cert})

@login_required
def master_trainer_profile(request):
    """
    Profile edit for MasterTrainer. Allows the master trainer to edit their profile.
    Mirrors partner_profile flow but uses MasterTrainer + MasterTrainerForm.
    """
    if getattr(request.user, "role", "").lower() != "master_trainer":
        return HttpResponseForbidden("Not authorized")

    mt = _get_trainer_for_user(request.user)
    if not mt:
        # create a skeleton profile (minimal) so forms have an instance
        mt = MasterTrainer.objects.create(
            user=request.user,
            full_name=request.user.get_full_name() or request.user.username
        )
        request.user.refresh_from_db()

    if request.method == 'POST':
        form = PublicMasterTrainerProfileForm(request.POST, request.FILES, instance=mt)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect('master_trainer_dashboard')
        else:
            messages.error(request, "Fix errors below.")
    else:
        form = PublicMasterTrainerProfileForm(instance=mt)

    return render(request, 'master_trainer/profile.html', {'master_trainer': mt, 'form': form})

@login_required
def training_partner_dashboard(request):
    """
    Training Partner dashboard — show TrainingRequests (assignments) that require partner action.
    Defensive: does not assume Batch has 'partner' or 'status' fields. Uses Batch.request__partner where possible.
    """
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)

    # TrainingRequest: show PENDING requests that are either unassigned or assigned to this partner
    requests_qs = TrainingRequest.objects.filter(status='BATCHING').order_by('-created_at')
    if partner:
        reqs_for_partner = requests_qs.filter(Q(partner__isnull=True) | Q(partner=partner))
    else:
        reqs_for_partner = requests_qs.filter(partner__isnull=True)
    assignments = reqs_for_partner[:200]

    # Build "ongoing" batches for this partner, but do NOT reference Batch.partner since your model lacks it.
    ongoing = Batch.objects.none()
    try:
        # First attempt: use Batch.request relation to find batches whose TrainingRequest is assigned to this partner.
        # This assumes Batch has a ForeignKey 'request' (your trace shows 'request' exists).
        if partner:
            # Prefer batches linked to TrainingRequests assigned to this partner and that are currently active by date.
            today = timezone.now().date()
            # if Batch has start_date & end_date fields (your trace shows they exist) consider date-range ongoing
            field_names = [f.name for f in Batch._meta.fields]
            has_dates = 'start_date' in field_names and 'end_date' in field_names

            if has_dates:
                ongoing_qs = Batch.objects.filter(
                    request__partner=partner,
                    start_date__lte=today,
                    end_date__gte=today
                ).select_related('training_plan')[:50]
            else:
                # No dates: fall back to recent batches for this partner via request relation
                ongoing_qs = Batch.objects.filter(request__partner=partner).select_related('training_plan')[:50]

            # If the query returned nothing, also try to return recent batches linked to partner requests (no date filter)
            if not ongoing_qs.exists():
                ongoing_qs = Batch.objects.filter(request__partner=partner).select_related('training_plan')[:50]

            ongoing = ongoing_qs
        else:
            # No partner object: show recent batches (safe fallback)
            ongoing = Batch.objects.all().select_related('training_plan').order_by('-created_at')[:50]
    except Exception:
        # Any unexpected model schema issue -> safe fallback: recent batches (no partner filter)
        try:
            ongoing = Batch.objects.all().select_related('training_plan').order_by('-created_at')[:50]
        except Exception:
            ongoing = Batch.objects.none()

    context = {
        'partner': partner,
        'training_requests': assignments,
        'assignments': assignments,  # backward compatibility for templates
        'ongoing': ongoing,
    }
    return render(request, 'training_partner/dashboard.html', context)



@login_required
def partner_profile(request):
    if getattr(request.user, 'role', '').lower() != 'training_partner':
        return HttpResponseForbidden("Not authorized")

    partner = getattr(request.user, 'training_partner_profile', None)
    if not partner:
        partner = TrainingPartner.objects.create(user=request.user, name=request.user.get_full_name() or request.user.username)
        request.user.refresh_from_db()

    if request.method == 'POST':
        form = TrainingPartnerProfileForm(request.POST, request.FILES, instance=partner)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect('training_partner_dashboard')
        else:
            messages.error(request, "Fix errors below.")
    else:
        form = TrainingPartnerProfileForm(instance=partner)

    return render(request, 'training_partner/profile.html', {'partner': partner, 'form': form})

@login_required
def training_partner_centre_registration(request):
    """
    Centre Registration page:
    - Left: list of centres (click to edit)
    - Right: 'Add new centre' button (reveals full form). When a centre is selected (?centre_id=NN) the right side shows edit/delete + submissions.
    """
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    # ensure partner exists (best-effort)
    partner = _get_partner_for_user(request.user)
    if not partner:
        partner = TrainingPartner.objects.create(user=request.user, name=request.user.get_full_name() or request.user.username)
        request.user.refresh_from_db()

    centre_id = request.GET.get("centre_id") or request.POST.get("centre_id")
    centre_instance = None
    if centre_id:
        try:
            centre_instance = TrainingPartnerCentre.objects.get(id=centre_id, partner=partner)
        except TrainingPartnerCentre.DoesNotExist:
            centre_instance = None

    partner_centres_qs = TrainingPartnerCentre.objects.filter(partner=partner).order_by("-created_at")

    # Submissions: only show those for the selected centre; otherwise show recent across centres
    submissions_qs = TrainingPartnerSubmission.objects.none()
    if centre_instance:
        submissions_qs = TrainingPartnerSubmission.objects.filter(centre=centre_instance).order_by("-uploaded_on")[:200]
    else:
        centre_ids = list(partner_centres_qs.values_list("id", flat=True))
        if centre_ids:
            submissions_qs = TrainingPartnerSubmission.objects.filter(centre_id__in=centre_ids).order_by("-uploaded_on")[:200]

    # initialize forms (POST handling below)
    if request.method == "POST":
        # Save centre + rooms
        if "save_centre" in request.POST:
            form = TrainingPartnerCentreForm(request.POST, instance=centre_instance)
            rooms_formset = TrainingPartnerCentreRoomsFormSet(request.POST, instance=centre_instance)
            if form.is_valid() and rooms_formset.is_valid():
                try:
                    with transaction.atomic():
                        centre = form.save(commit=False)
                        centre.partner = partner
                        centre.uploaded_by = request.user
                        centre.save()
                        rooms_formset.instance = centre
                        rooms_formset.save()
                        messages.success(request, "Centre saved successfully.")
                        return redirect(f"{reverse('training_partner_centre_registration')}?centre_id={centre.id}")
                except Exception as e:
                    messages.error(request, f"Failed to save centre: {e}")
            else:
                messages.error(request, "Fix errors in centre or rooms form.")
        # Upload submissions (multiple files)
        elif "upload_submissions" in request.POST:
            if not centre_instance:
                messages.error(request, "Select or save a centre first.")
            else:
                submission_form = TrainingPartnerSubmissionForm(request.POST, request.FILES)
                # We use the form for category/notes validation; actual files via submission_files input (multiple)
                if submission_form.is_valid():
                    category = submission_form.cleaned_data.get("category")
                    notes = submission_form.cleaned_data.get("notes")
                    files = request.FILES.getlist("submission_files")
                    if not files:
                        messages.error(request, "No files selected.")
                    else:
                        uploaded = 0
                        for f in files:
                            try:
                                sub = TrainingPartnerSubmission(
                                    centre=centre_instance,
                                    category=category,
                                    file=f,
                                    uploaded_by=request.user,
                                    notes=notes
                                )
                                sub.save()
                                uploaded += 1
                            except Exception as e:
                                messages.error(request, f"Upload failed for {getattr(f, 'name', '')}: {e}")
                        if uploaded:
                            messages.success(request, f"Uploaded {uploaded} file(s).")
                            return redirect(f"{reverse('training_partner_centre_registration')}?centre_id={centre_instance.id}")
                else:
                    messages.error(request, "Fix errors in submission form.")
        elif "delete_submission" in request.POST:
            sid = request.POST.get("submission_id")
            if sid and centre_instance:
                try:
                    s = TrainingPartnerSubmission.objects.get(id=sid, centre=centre_instance)
                    s.delete()
                    messages.success(request, "Submission deleted.")
                except TrainingPartnerSubmission.DoesNotExist:
                    messages.error(request, "Submission not found.")
            return redirect(f"{reverse('training_partner_centre_registration')}?centre_id={centre_instance.id}" if centre_instance else reverse('training_partner_centre_registration'))
        elif "delete_centre" in request.POST:
            if centre_instance:
                try:
                    centre_instance.delete()
                    messages.success(request, "Centre deleted.")
                except Exception as e:
                    messages.error(request, f"Could not delete centre: {e}")
            return redirect(reverse('training_partner_centre_registration'))
        else:
            messages.error(request, "Unknown action.")
    else:
        # GET: unbound forms
        form = TrainingPartnerCentreForm(instance=centre_instance)
        rooms_formset = TrainingPartnerCentreRoomsFormSet(instance=centre_instance)
        submission_form = TrainingPartnerSubmissionForm()

    # ensure submission_form exists
    if request.method == "POST" and 'submission_form' not in locals():
        submission_form = TrainingPartnerSubmissionForm()

    context = {
        "partner": partner,
        "centre": centre_instance,
        "partner_centres": partner_centres_qs,
        "form": form,
        "rooms_formset": rooms_formset,
        "submission_form": submission_form,
        "submissions": submissions_qs,
    }
    return render(request, "training_partner/centre_registration.html", context)

@require_POST
@login_required
def partner_propose_dates(request):
    if getattr(request.user, "role", "").lower() != "training_partner":
        return JsonResponse({'ok': False, 'error': 'unauthorized'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
        batch_id = int(data.get('batch_id'))
        centre = data.get('centre')
        start = data.get('start')
        end = data.get('end')
    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'invalid payload: {e}'}, status=400)

    partner = _get_partner_for_user(request.user)
    if not partner:
        return JsonResponse({'ok': False, 'error': 'no partner profile'}, status=400)

    batch = get_object_or_404(Batch, id=batch_id)

    if batch.partner_id != partner.id:
        return JsonResponse({'ok': False, 'error': 'batch not assigned to you'}, status=403)

    with transaction.atomic():
        # Save proposed centre to centre_proposed (new field)
        if centre is not None:
            batch.centre_proposed = centre

        # Save start/end (robust, avoid errors)
        from datetime import datetime
        try:
            if start:
                batch.start_date = datetime.fromisoformat(start).date()
        except Exception:
            # ignore invalid format (or you can return error)
            pass
        try:
            if end:
                batch.end_date = datetime.fromisoformat(end).date()
        except Exception:
            pass

        # Try to set status to 'proposed' if available
        try:
            status_field = Batch._meta.get_field('status')
            choices = [c[0] for c in getattr(status_field, 'choices', [])]
            if 'proposed' in choices:
                batch.status = 'proposed'
            elif 'PENDING' in choices:
                # fall back to an uppercase value if you use uppercase choices
                batch.status = 'PENDING'
        except Exception:
            pass

        batch.save()

        # Notify theme expert (SMMU) if present
        try:
            tp = getattr(batch, 'training_plan', None)
            if tp and getattr(tp, 'theme_expert', None):
                expert = tp.theme_expert
                # only send if they have an email
                if getattr(expert, 'email', None):
                    subject = f"Batch proposed for approval: {tp.training_name} - {batch.code or batch.id}"
                    context = {
                        'expert': expert,
                        'batch': batch,
                        'training_plan': tp,
                        'partner': partner,
                    }
                    # simple html/text message - you can create a template later
                    html_message = render_to_string('emails/tms_batch_proposed.html', context) if False else \
                        f"""
                        Dear {expert.get_full_name() or expert.username},

                        A training batch has been proposed by partner "{partner.name if partner else partner}" for training:
                        "{tp.training_name}" (Theme: {tp.theme}).

                        Proposed Centre: {batch.centre_proposed or 'N/A'}
                        Start Date: {batch.start_date or 'N/A'}
                        End Date: {batch.end_date or 'N/A'}

                        Please review and approve/reject in the SMMU portal.

                        Thanks,
                        Training Management Portal
                        """
                    send_mail(subject, strip_tags(html_message), None, [expert.email], html_message=html_message)
        except Exception:
            # logging but do not interrupt user flow
            logger.exception("Failed sending notification to theme expert for batch %s", batch.id)

    return JsonResponse({'ok': True, 'new_status': getattr(batch, 'status', None)})

@login_required
def partner_view_request(request, request_id):
    """
    Render detail page for a TrainingRequest (anchored on TrainingRequest).
    Adds safe display fields to beneficiaries so templates don't fail on missing attrs.
    """
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)
    training_request = get_object_or_404(TrainingRequest, id=request_id)

    # Only allow partner assigned to request or any partner if request has no partner yet
    if training_request.partner and (partner is None or training_request.partner_id != partner.id):
        return HttpResponseForbidden("Not authorized for this TrainingRequest")

    # gather partner's registered centres
    try:
        centre_qs = TrainingPartnerCentre.objects.filter(partner=partner).order_by('-training_hall_capacity') if partner else TrainingPartnerCentre.objects.none()
    except Exception:
        centre_qs = TrainingPartnerCentre.objects.none()

    # recent submissions (for preview) - defensive: try centre__partner, then uploaded_by fallback
    submissions = TrainingPartnerSubmission.objects.none()
    try:
        submission_fields = [f.name for f in TrainingPartnerSubmission._meta.fields]
        if 'centre' in submission_fields:
            try:
                submissions = TrainingPartnerSubmission.objects.filter(centre__partner=partner).order_by('-uploaded_on')[:8]
            except Exception:
                centre_ids = [c.id for c in centre_qs] if centre_qs else []
                if centre_ids:
                    submissions = TrainingPartnerSubmission.objects.filter(centre_id__in=centre_ids).order_by('-uploaded_on')[:8]
                else:
                    submissions = TrainingPartnerSubmission.objects.none()
        else:
            if 'uploaded_by' in submission_fields:
                submissions = TrainingPartnerSubmission.objects.filter(uploaded_by=request.user).order_by('-uploaded_on')[:8]
            else:
                submissions = TrainingPartnerSubmission.objects.none()
    except Exception:
        try:
            if 'uploaded_by' in [f.name for f in TrainingPartnerSubmission._meta.fields]:
                submissions = TrainingPartnerSubmission.objects.filter(uploaded_by=request.user).order_by('-uploaded_on')[:8]
            else:
                submissions = TrainingPartnerSubmission.objects.none()
        except Exception:
            submissions = TrainingPartnerSubmission.objects.none()

    # beneficiaries list attached to TrainingRequest (through BeneficiaryBatchRegistration)
    try:
        beneficiaries_qs = training_request.beneficiaries.all().order_by('id')
        beneficiaries = list(beneficiaries_qs)
    except Exception:
        beneficiaries = []

    # helper to safely pick first existing attribute value from a list of candidate names
    def _first_attr(obj, candidates, default=None):
        for attr in candidates:
            try:
                # use getattr with default sentinel to avoid raising AttributeError in property access
                val = getattr(obj, attr, None)
            except Exception:
                # Some model properties may raise; ignore and continue
                val = None
            if val not in (None, ''):
                return val
        return default

    # compute display-friendly attributes for each beneficiary to avoid missing-field lookups in templates
    today = date.today()
    for b in beneficiaries:
        # display name
        display_name = _first_attr(b, ['full_name', 'name', 'beneficiary_name', 'first_name', 'person_name'], default=None)
        if display_name is None:
            # fallback to str(b)
            try:
                display_name = str(b)
            except Exception:
                display_name = '-'
        setattr(b, 'display_name', display_name)

        # gender
        gender_val = _first_attr(b, ['gender', 'sex', 'gender_display'], default='-')
        setattr(b, 'gender_display', gender_val or '-')

        # mobile / phone
        mobile_val = _first_attr(b, ['mobile', 'phone', 'phone_number', 'contact', 'mobile_no'], default='-')
        setattr(b, 'mobile_display', mobile_val or '-')

        # village / location
        village_val = _first_attr(b, ['village', 'village_name', 'address', 'habitation', 'location'], default='-')
        setattr(b, 'village_display', village_val or '-')

        # age (you already computed earlier; recompute here to be safe)
        dob = getattr(b, 'date_of_birth', None)
        age = None
        if dob:
            try:
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            except Exception:
                age = None
        setattr(b, 'age', age if age is not None else '-')

    # trainer_cert_map (if trainers referenced)
    trainer_cert_map = {}
    try:
        trainer_ids = [t.id for t in training_request.trainers.all()] if hasattr(training_request, 'trainers') else []
        if trainer_ids:
            certs = MasterTrainerCertificate.objects.filter(trainer_id__in=trainer_ids).order_by('trainer_id', '-issued_on', '-created_at')
            for c in certs:
                prev = trainer_cert_map.get(c.trainer_id)
                if not prev:
                    trainer_cert_map[c.trainer_id] = c.certificate_number
                else:
                    try:
                        trainer_cert_map[c.trainer_id] = c.certificate_number
                    except Exception:
                        trainer_cert_map[c.trainer_id] = c.certificate_number
    except Exception:
        trainer_cert_map = {}

    context = {
        'partner': partner,
        'training_request': training_request,
        'request': training_request,  # templates may expect 'request'
        'partner_centres': centre_qs,
        'submissions': submissions,
        'trainer_cert_map': trainer_cert_map,
        'beneficiaries': beneficiaries,
        'today': today,
    }

    # Reuse the training_partner/view_batch.html template: supply a shim batch object so the template works.
    class _PseudoBatch:
        def __init__(self, training_request):
            self.request = training_request
            self.training_plan = training_request.training_plan
            self.trainers = training_request.trainers if hasattr(training_request, 'trainers') else []
            self.beneficiaries = training_request.beneficiaries if hasattr(training_request, 'beneficiaries') else []
            self.partner = training_request.partner
            self.start_date = None
            self.end_date = None
            self.centre = None
            self.centre_proposed = None
            self.code = None
            self.id = f"TR-{training_request.id}"

    context['batch'] = _PseudoBatch(training_request)

    return render(request, 'training_partner/view_batch.html', context)

@login_required
def partner_view_requests(request):
    """
    Small list page showing TrainingRequests assigned to the logged-in Training Partner.
    Columns: Request ID, Training Plan, Applicable for, Created by, Status (last).
    """
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)
    if not partner:
        return HttpResponseForbidden("No partner profile")

    # Query training requests assigned to this partner
    qs = TrainingRequest.objects.filter(partner=partner).select_related('training_plan', 'created_by').order_by('-created_at')

    # Optional: basic search by training name or request id
    q = request.GET.get('q', '').strip()
    if q:
        # try simple search on training name, training_plan or id
        qs = qs.filter(
            Q(id__icontains=q) |
            Q(training_plan__training_name__icontains=q) |
            Q(training_plan__training_code__icontains=q)
        )

    # Pagination (small page)
    page = int(request.GET.get('page', 1) or 1)
    per_page = 25
    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(page)

    # prepare display rows with fallbacks
    rows = []
    for tr in page_obj:
        # Training plan display
        tp = getattr(tr, 'training_plan', None)
        tp_name = getattr(tp, 'training_name', None) or getattr(tp, 'name', None) or '—'
        # Applicable for: try common fields; fall back to level or '—'
        applicable = getattr(tr, 'applicable_for', None) or getattr(tr, 'applicable_to', None) or getattr(tr, 'level', None) or '—'
        # Created by
        creator = getattr(tr, 'created_by', None)
        creator_name = None
        if creator:
            creator_name = (getattr(creator, 'get_full_name', None) and creator.get_full_name()) or getattr(creator, 'username', None) or str(creator)
        else:
            creator_name = '—'
        # status
        status = getattr(tr, 'status', '—')
        # updated/created timestamp
        updated = getattr(tr, 'updated_at', None) or getattr(tr, 'modified_at', None) or getattr(tr, 'created_at', None)
        updated_display = updated.isoformat() if updated else '—'

        rows.append({
            'id': tr.id,
            'code': getattr(tr, 'code', None) or getattr(tr, 'request_code', None),
            'training_plan': tp_name,
            'applicable': applicable,
            'created_by': creator_name,
            'status': status,
            'updated': updated_display,
            'object': tr,
        })

    context = {
        'partner': partner,
        'page_obj': page_obj,
        'paginator': paginator,
        'rows': rows,
        'q': q,
    }
    return render(request, 'training_partner/partner_requests_list.html', context)

@login_required
@require_POST
def partner_create_batches(request, request_id=None):
    """
    Creates Batch rows from a TrainingRequest and selected centres.

    Improvements:
    - Accepts per-centre explicit 'beneficiaries' lists in payload (used when provided).
    - Falls back to the older "distribute remaining beneficiaries by capacity" when no per-centre list is provided.
    - Removes payload-assigned beneficiaries from the remaining pool to avoid duplicates.
    - After successful creation, sets TrainingRequest.status to 'PENDING' (Pending Approval) when available.
    """
    if getattr(request.user, "role", "").lower() != "training_partner":
        return JsonResponse({'ok': False, 'error': 'unauthorized'}, status=403)

    partner = _get_partner_for_user(request.user)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'invalid json: {e}'}, status=400)

    # prefer url param, then payload
    training_request_id = request_id or payload.get('training_request_id') or payload.get('request_id') or payload.get('request')
    if not training_request_id:
        return JsonResponse({'ok': False, 'error': 'training_request_id required'}, status=400)

    centres = payload.get('centres') or []
    default_start = payload.get('default_start') or None

    tr = get_object_or_404(TrainingRequest, id=training_request_id)

    # Only the assigned partner (or if unassigned any partner) can create batches for this request
    if tr.partner and (partner is None or tr.partner_id != partner.id):
        return JsonResponse({'ok': False, 'error': 'TrainingRequest assigned to different partner'}, status=403)

    # Collect beneficiary ids from TrainingRequest (through BeneficiaryBatchRegistration)
    try:
        ben_qs = tr.beneficiaries.all().order_by('id')
    except Exception:
        ben_qs = []
    ben_ids = list(ben_qs.values_list('id', flat=True)) if hasattr(ben_qs, 'values_list') else list(ben_qs)
    total_ben = len(ben_ids)
    if total_ben == 0:
        return JsonResponse({'ok': False, 'error': 'No beneficiaries attached to this TrainingRequest'}, status=400)

    # If no centres selected -> error
    if not centres:
        return JsonResponse({'ok': False, 'error': 'No centres provided'}, status=400)

    # Validate centres: ensure they belong to partner, and capture any explicit beneficiaries lists
    selected_centres = []
    for c in centres:
        cid = c.get('centre_id') or c.get('id')
        if not cid:
            return JsonResponse({'ok': False, 'error': 'centre_id missing in centres list'}, status=400)
        try:
            centre_obj = TrainingPartnerCentre.objects.get(id=cid)
        except TrainingPartnerCentre.DoesNotExist:
            return JsonResponse({'ok': False, 'error': f'Centre {cid} not found'}, status=404)
        # Ensure centre belongs to this partner (safety)
        if partner and getattr(centre_obj, 'partner_id', None) != partner.id:
            return JsonResponse({'ok': False, 'error': f'Centre {cid} not registered to you'}, status=403)
        cap = c.get('capacity') or getattr(centre_obj, 'training_hall_capacity', None) or 0
        start = c.get('start') or default_start

        # normalize any explicit beneficiaries list (client side may send 'beneficiaries' key)
        payload_bens = c.get('beneficiaries') or c.get('assigned') or c.get('assigned_ids') or None
        if payload_bens and isinstance(payload_bens, list):
            try:
                payload_bens = [int(x) for x in payload_bens]
            except Exception:
                payload_bens = None

        selected_centres.append({
            'centre': centre_obj,
            'capacity': int(cap or 0),
            'start': start,
            'payload_beneficiaries': payload_bens
        })

    # Now allocate beneficiaries using explicit payload lists when provided,
    # otherwise fall back to slicing from the remaining pool by capacity.
    allocations = []
    remaining = ben_ids[:]  # make a copy
    days = getattr(tr.training_plan, 'no_of_days', None) or 1
    try:
        days = int(days)
    except Exception:
        days = 1

    for sc in selected_centres:
        if not remaining and not sc.get('payload_beneficiaries'):
            # nothing left to assign and no explicit payload list provided -> skip
            continue

        cap = sc['capacity'] or 0

        # If caller provided explicit beneficiaries for this centre, use those (but ensure they exist in remaining)
        assigned = []
        if sc.get('payload_beneficiaries'):
            # only take IDs that belong to the original training request and still remain unassigned
            assigned_candidate = [int(x) for x in sc['payload_beneficiaries'] if int(x) in remaining]
            # If capacity is set and candidate exceeds capacity, trim to capacity
            if cap and len(assigned_candidate) > cap:
                assigned_candidate = assigned_candidate[:cap]
            assigned = assigned_candidate
            # remove assigned from remaining
            remaining = [r for r in remaining if r not in assigned]
        else:
            # no explicit payload list: assign next `cap` from remaining
            if cap <= 0:
                assigned = []
            else:
                assigned = remaining[:cap]
                remaining = remaining[cap:]

        # compute start date if provided
        start_date = None
        end_date = None
        if sc['start']:
            try:
                start_date = timezone.datetime.fromisoformat(sc['start']).date()
            except Exception:
                try:
                    start_date = timezone.datetime.strptime(sc['start'], '%Y-%m-%d').date()
                except Exception:
                    start_date = None
        if start_date:
            end_date = start_date + timedelta(days=days)

        # Only create allocation if we have at least one assigned beneficiary
        allocations.append({
            'centre': sc['centre'],
            'assigned': assigned,
            'start': start_date,
            'end': end_date
        })

    # After processing all centres, if there are still unassigned beneficiaries -> capacity insufficient
    if remaining:
        return JsonResponse({
            'ok': False,
            'error': 'Selected centres capacity insufficient for all beneficiaries (or some beneficiaries were not included in payload assignments).',
            'remaining_count': len(remaining),
            'remaining_ids_sample': remaining[:20]
        }, status=400)

    created = []
    try:
        with transaction.atomic():
            for alloc in allocations:
                centre_obj = alloc['centre']
                assigned_bens = alloc['assigned'] or []
                # skip empty allocations (do not create zero-participant batch)
                if not assigned_bens:
                    continue

                start_date = alloc['start']
                end_date = alloc['end']

                batch = Batch.objects.create(
                    request=tr,
                    centre=centre_obj,
                    start_date=start_date,
                    end_date=end_date
                )

                # set default status if the field exists and has choices
                try:
                    status_field = Batch._meta.get_field('status')
                    choices = [c[0] for c in status_field.choices]
                    if 'PENDING' in choices:
                        batch.status = 'PENDING'
                    elif 'PROPOSED' in choices:
                        batch.status = 'PROPOSED'
                    batch.save()
                except Exception:
                    # ignore if status field missing or odd
                    batch.save()

                # attach beneficiaries via BatchBeneficiary
                if assigned_bens:
                    assigned_bens = [int(x) for x in assigned_bens]
                    now = timezone.now()
                    bb_objects = []
                    for ben_id in assigned_bens:
                        if not BatchBeneficiary.objects.filter(batch=batch, beneficiary_id=ben_id).exists():
                            bb_objects.append(BatchBeneficiary(batch=batch, beneficiary_id=ben_id, registered_on=now))
                    if bb_objects:
                        BatchBeneficiary.objects.bulk_create(bb_objects)

                    # optional: annotate existing TrainingRequest registrations
                    try:
                        BeneficiaryBatchRegistration.objects.filter(training=tr, beneficiary_id__in=assigned_bens).update(
                            remarks=F('remarks') + ' | Assigned to batch ' + (batch.code if batch.code else str(batch.id))
                        )
                    except Exception:
                        pass

                # set code if needed
                if not getattr(batch, 'code', None):
                    import uuid
                    batch.code = 'B-' + str(uuid.uuid4())[:8]
                    batch.save()

                created.append({'batch_id': batch.id, 'batch_code': batch.code, 'centre_id': centre_obj.id, 'assigned_count': len(assigned_bens)})

            # mark training_request.partner as this partner (if not already)
            if not tr.partner and partner:
                tr.partner = partner

            # --- NEW: explicitly set request status to PENDING (Pending Approval) after batching ---
            try:
                status_choices = [c[0] for c in tr._meta.get_field('status').choices]
                if 'PENDING' in status_choices:
                    tr.status = 'PENDING'
                elif 'PROPOSED' in status_choices:
                    # backward fallback if your project uses PROPOSED instead
                    tr.status = 'PROPOSED'
                else:
                    # fallback to first available choice or PENDING
                    tr.status = status_choices[0] if status_choices else 'PENDING'
            except Exception:
                tr.status = 'PENDING'

            tr.save()

    except Exception as e:
        logger.exception("partner_create_batches: failed creating batches: %s", e)
        return JsonResponse({'ok': False, 'error': 'server error creating batches'}, status=500)

    # --- Notification recipients logic (unchanged) ---
    try:
        recipients = []
        level = getattr(tr, 'level', '')
        level_upper = level.upper() if level else ''

        if level_upper == 'BLOCK':
            creator = getattr(tr, 'created_by', None)
            if creator:
                try:
                    assignments = BmmuBlockAssignment.objects.filter(user=creator).select_related('block__district')
                    for a in assignments:
                        district = getattr(a.block, 'district', None)
                        if district:
                            dmmu_users = User.objects.filter(role__iexact='dmmu', profile__district=district)
                            for u in dmmu_users:
                                if getattr(u, 'email', None):
                                    recipients.append(u.email)
                except Exception:
                    try:
                        district = getattr(creator, 'district', None)
                        if district:
                            dmmu_users = User.objects.filter(role__iexact='dmmu', profile__district=district)
                            for u in dmmu_users:
                                if getattr(u, 'email', None):
                                    recipients.append(u.email)
                    except Exception:
                        pass

        elif level_upper in ('DISTRICT', 'STATE'):
            tp = getattr(tr, 'training_plan', None)
            if tp and getattr(tp, 'theme_expert', None):
                expert = tp.theme_expert
                if getattr(expert, 'email', None):
                    recipients.append(expert.email)
    except Exception:
        logger.exception("partner_create_batches: notification recipients lookup failed, continuing without notification")

    # Send a simple email if any recipients found
    try:
        if recipients:
            subject = f"New batch(es) created from TrainingRequest {tr.id} - {tr.training_plan.training_name}"
            body = f"Partner {partner.name if partner else request.user.username} created {len(created)} batch(es) for TrainingRequest {tr.id} ({tr.training_plan.training_name}).\n\nBatches:\n"
            for c in created:
                body += f"- Batch {c.get('batch_code')} (id:{c.get('batch_id')}), centre_id: {c.get('centre_id')}, assigned_count: {c.get('assigned_count')}\n"
            send_mail(subject, strip_tags(body), None, list(set(recipients)))
    except Exception:
        logger.exception("partner_create_batches: email send failed")

    return JsonResponse({'ok': True, 'created': created, 'count': len(created)})


@login_required
def partner_ongoing_trainings(request):
    """
    Partner-facing list of batches. Uses BatchBeneficiary for per-batch participants.
    Keeps your auto-status update logic intact.
    """
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)
    if not partner:
        return HttpResponseForbidden("No partner profile")

    # timezone / today
    try:
        india_tz = ZoneInfo("Asia/Kolkata")
    except Exception:
        india_tz = None
    today = datetime.now(tz=india_tz).date() if india_tz else timezone.localdate()

    status_param = (request.GET.get('status') or 'all').strip().lower()

    # base queryset for the partner: batches belonging to partner via request or centre
    batches_qs = Batch.objects.filter(Q(request__partner=partner) | Q(centre__partner=partner))

    # --- AUTO-UPDATE statuses based on dates (keeps your existing logic) ---
    try:
        try:
            status_choices = [c[0] for c in Batch._meta.get_field('status').choices]
        except Exception:
            status_choices = []

        def find_choice_token(name):
            for tok in status_choices:
                if str(tok).upper() == str(name).upper():
                    return tok
            return None

        ongoing_token = find_choice_token('ONGOING') or find_choice_token('Ongoing') or 'ONGOING'
        completed_token = find_choice_token('COMPLETED') or find_choice_token('Completed') or 'COMPLETED'
        scheduled_token = find_choice_token('SCHEDULED') or find_choice_token('Scheduled') or 'SCHEDULED'

        candidates = batches_qs.filter(~Q(status__iexact=completed_token))

        for b in candidates:
            try:
                raw_start = getattr(b, 'start_date', None)
                raw_end = getattr(b, 'end_date', None)

                start_date = raw_start.date() if isinstance(raw_start, datetime) else raw_start if isinstance(raw_start, date) else None
                end_date = raw_end.date() if isinstance(raw_end, datetime) else raw_end if isinstance(raw_end, date) else None

                current_status = (getattr(b, 'status', '') or '').strip()

                if start_date and start_date == today:
                    if not current_status or current_status.upper() != str(ongoing_token).upper():
                        b.status = ongoing_token
                        b.save(update_fields=['status'])
                        logger.info("partner_ongoing_trainings: auto-set batch %s -> %s (start_date == today %s)", getattr(b, 'id', None), ongoing_token, today)
            except Exception:
                logger.exception("partner_ongoing_trainings: failed to auto-update status for batch %s", getattr(b, 'id', 'unknown'))
    except Exception:
        logger.exception("partner_ongoing_trainings: auto-update status step failed, continuing without updates")

    # status filter
    if status_param != 'all':
        batches_qs = batches_qs.filter(status__iexact=status_param)

    # annotate participant counts using BatchBeneficiary relation
    batches_qs = batches_qs.select_related('request__training_plan', 'centre')\
                           .annotate(participants_count=Count('batch_beneficiaries', distinct=True))\
                           .prefetch_related('trainers')\
                           .order_by('start_date')

    batches = list(batches_qs)

    # helper to compute age
    def compute_age(dob):
        if not dob:
            return None
        try:
            today_date = date.today()
            return today_date.year - dob.year - ((today_date.month, today_date.day) < (dob.month, dob.day))
        except Exception:
            return None

    # attach trainers_list and batch-specific beneficiaries_list for each batch
    for b in batches:
        try:
            trainers_list = list(b.trainers.all())
        except Exception:
            trainers_list = []

        # **CRITICAL FIX**: fetch beneficiaries FROM BatchBeneficiary (per-batch), NOT from request
        try:
            bb_qs = b.batch_beneficiaries.select_related('beneficiary').all()
            beneficiaries_list = []
            for bb in bb_qs:
                ben = bb.beneficiary
                # attach small helpers as used elsewhere
                ben.age = compute_age(getattr(ben, 'date_of_birth', None))
                # mobile / display_name may exist already; set safe fallbacks
                ben.display_name = getattr(ben, 'member_name', None) or getattr(ben, 'full_name', None) or str(ben)
                ben.mobile_display = getattr(ben, 'mobile_number', None) or getattr(ben, 'mobile_no', None) or getattr(ben, 'mobile', '')
                beneficiaries_list.append(ben)
        except Exception:
            # fallback to empty list (do not use request beneficiaries)
            beneficiaries_list = []

        setattr(b, 'trainers_list', trainers_list)
        setattr(b, 'beneficiaries_list', beneficiaries_list)
        # ensure template-friendly attribute for count (if template expects different name)
        setattr(b, 'participants_count', getattr(b, 'participants_count', len(beneficiaries_list)))

    status_options = ['all', 'ONGOING', 'COMPLETED', 'SCHEDULED', 'CANCELLED']
    context = {
        'partner': partner,
        'batches': batches,
        'today': today,
        'status': status_param,
        'status_options': status_options,
    }
    return render(request, 'training_partner/ongoing_list.html', context)


@login_required
def attendance_per_batch(request, batch_id):
    """
    Split rendering: day-1 eKYC template vs normal attendance template.

    Behavior:
      - GET: renders either attendance_per_batch_ekyc.html or attendance_per_batch.html
      - POST:
         * AJAX action=record_fingerprint -> update/create BatchEkycVerification (RECORDED)
         * AJAX action=verify_ekyc     -> update/create BatchEkycVerification (VERIFIED) and return all_verified flag
         * Otherwise -> attendance CSV/checkboxes handling (unchanged)
    """
    batch = get_object_or_404(
        Batch.objects.select_related('request__training_plan', 'centre').prefetch_related('trainers'),
        id=batch_id
    )

    # timezone / today
    try:
        india_tz = ZoneInfo("Asia/Kolkata")
    except Exception:
        india_tz = None
    today = datetime.now(tz=india_tz).date() if india_tz else timezone.localdate()

    # helper: attach training_plan for templates
    training_plan = getattr(batch.request, 'training_plan', None) if getattr(batch, 'request', None) else None
    setattr(batch, 'training_plan', training_plan)

    # centre display names (safety)
    if getattr(batch, 'centre', None):
        centre_display = getattr(batch.centre, 'venue_name', None) or getattr(batch.centre, 'centre_coord_name', None) or str(batch.centre)
        try:
            setattr(batch.centre, 'name', centre_display)
        except Exception:
            setattr(batch, 'centre_name', centre_display)

    # Trainers list
    try:
        trainers_qs = list(batch.trainers.all())
    except Exception:
        trainers_qs = []

    # Beneficiaries from per-batch relation
    try:
        bb_qs = batch.batch_beneficiaries.select_related('beneficiary').all()
        beneficiaries_qs = [bb.beneficiary for bb in bb_qs]
    except Exception:
        beneficiaries_qs = []

    trainers_display = []
    for t in trainers_qs:
        display_name = getattr(t, 'name', None) or getattr(t, 'full_name', None) or str(t)
        trainers_display.append({'id': t.id, 'name': display_name, 'obj': t})

    beneficiaries_display = []
    for b in beneficiaries_qs:
        display_name = getattr(b, 'member_name', None) or getattr(b, 'name', None) or getattr(b, 'full_name', None) or str(b)
        beneficiaries_display.append({'id': b.id, 'name': display_name, 'obj': b})

    # safe get existing ekyc
    def safe_get_ekyc(batch_obj, participant_id, role):
        try:
            return BatchEkycVerification.objects.filter(
                batch=batch_obj,
                participant_id=participant_id,
                participant_role=role
            ).first()
        except OperationalError as e:
            logger.warning("OperationalError reading BatchEkycVerification: %s", e)
            return None
        except Exception as e:
            logger.exception("Unexpected error reading BatchEkycVerification: %s", e)
            return None

    participants = []
    for t in trainers_display:
        participants.append({
            'id': t['id'],
            'name': t['name'],
            'role': 'trainer',
            'ekyc': safe_get_ekyc(batch, t['id'], 'trainer')
        })
    for b in beneficiaries_display:
        participants.append({
            'id': b['id'],
            'name': b['name'],
            'role': 'beneficiary',
            'ekyc': safe_get_ekyc(batch, b['id'], 'beneficiary')
        })

    # check table accessibility
    ek_table_accessible = True
    try:
        BatchEkycVerification.objects.exists()
    except OperationalError:
        ek_table_accessible = False
        if not request.session.get('ekyc_table_warning_shown'):
            messages.warning(request, "E-KYC DB table missing or not accessible — e-KYC functionality is unavailable until migrations are applied.")
            request.session['ekyc_table_warning_shown'] = True

    # ---------- POST: handle AJAX actions & attendance ----------
    if request.method == 'POST':
        action = request.POST.get('action')
        if action in ('record_fingerprint', 'verify_ekyc'):
            # return JSON (AJAX) for these actions
            logger.debug("attendance_per_batch: AJAX action=%s batch=%s user=%s", action, batch_id, request.user)
            if not ek_table_accessible:
                return JsonResponse({'success': False, 'error': 'E-KYC table not available.'}, status=500)

            try:
                participant_id = int(request.POST.get('participant_id', 0))
            except (TypeError, ValueError):
                return JsonResponse({'success': False, 'error': 'Invalid participant id.'}, status=400)
            participant_role = request.POST.get('participant_role', '')

            try:
                with transaction.atomic():
                    if action == 'record_fingerprint':
                        ekyc_obj, created = BatchEkycVerification.objects.update_or_create(
                            batch=batch,
                            participant_id=participant_id,
                            participant_role=participant_role,
                            defaults={'ekyc_status': 'RECORDED'}
                        )
                        logger.info("Recorded fingerprint: batch=%s pid=%s role=%s id=%s", batch_id, participant_id, participant_role, ekyc_obj.id)
                        return JsonResponse({
                            'success': True,
                            'status': 'RECORDED',
                            'status_display': 'Recorded',
                            'ekyc_id': ekyc_obj.id
                        })
                    else:  # verify_ekyc
                        ekyc_obj, created = BatchEkycVerification.objects.update_or_create(
                            batch=batch,
                            participant_id=participant_id,
                            participant_role=participant_role,
                            defaults={'ekyc_status': 'VERIFIED'}
                        )
                        logger.info("Verified ekyc: batch=%s pid=%s role=%s id=%s", batch_id, participant_id, participant_role, ekyc_obj.id)

                        # compute whether all participants are verified now
                        all_verified = True
                        for p in participants:
                            try:
                                verified = BatchEkycVerification.objects.filter(
                                    batch=batch,
                                    participant_id=p['id'],
                                    participant_role=p['role'],
                                    ekyc_status='VERIFIED'
                                ).exists()
                            except Exception as e:
                                logger.exception("Error checking verify for participant %s: %s", p, e)
                                verified = False
                            if not verified:
                                all_verified = False
                                break

                        return JsonResponse({
                            'success': True,
                            'status': 'VERIFIED',
                            'status_display': 'Verified',
                            'ekyc_id': ekyc_obj.id,
                            'all_verified': all_verified
                        })
            except Exception as e:
                logger.exception("Error processing action %s: %s", action, e)
                return JsonResponse({'success': False, 'error': str(e)}, status=500)

        # attendance submission (CSV / checkboxes) - same as before
        elif 'csv_file' in request.FILES or any(k.startswith('trainer_') or k.startswith('beneficiary_') for k in request.POST):
            attendance_obj, created = BatchAttendance.objects.get_or_create(batch=batch, date=today)
            csv_file = request.FILES.get('csv_file')
            if csv_file:
                attendance_obj.csv_upload = csv_file
                attendance_obj.save()

            participant_list = []
            for t in trainers_display:
                present = request.POST.get(f"trainer_{t['id']}") == 'on'
                participant_list.append({
                    'participant_id': t['id'],
                    'participant_name': t['name'],
                    'participant_role': 'trainer',
                    'present': present
                })
            for b in beneficiaries_display:
                present = request.POST.get(f"beneficiary_{b['id']}") == 'on'
                participant_list.append({
                    'participant_id': b['id'],
                    'participant_name': b['name'],
                    'participant_role': 'beneficiary',
                    'present': present
                })

            for p in participant_list:
                ParticipantAttendance.objects.update_or_create(
                    attendance=attendance_obj,
                    participant_id=p['participant_id'],
                    participant_role=p['participant_role'],
                    defaults={
                        'participant_name': p['participant_name'],
                        'present': p['present']
                    }
                )

            messages.success(request, f"Attendance recorded for {today}.")
            return redirect('attendance_per_batch', batch_id=batch.id)

        else:
            messages.error(request, "Unrecognized form submission.")
            return redirect('attendance_per_batch', batch_id=batch.id)

    # ---------- GET: selected-date attendance ----------
    selected_date = request.GET.get('date')
    attendance_records = None
    attendance_obj = None
    if selected_date:
        try:
            selected_date_obj = timezone.datetime.strptime(selected_date, '%Y-%m-%d').date()
            attendance_obj = BatchAttendance.objects.filter(batch=batch, date=selected_date_obj).first()
            if attendance_obj:
                attendance_records = attendance_obj.participant_records.all()
        except ValueError:
            messages.error(request, "Invalid date format.")
            selected_date = None

    # determine ekYC / attendance visibility
    is_first_day = (batch.start_date == today)

    # if any participant not VERIFIED => missing_ekyc True
    missing_ekyc = False
    try:
        for p in participants:
            st = None
            try:
                if p.get('ekyc'):
                    st = getattr(p['ekyc'], 'ekyc_status', None)
            except Exception:
                st = None
            if st != 'VERIFIED':
                missing_ekyc = True
                break
    except Exception:
        missing_ekyc = True

    attendance_exists_today = BatchAttendance.objects.filter(batch=batch, date=today).exists()
    show_ekyc = is_first_day and missing_ekyc
    show_attendance = (getattr(batch, 'status', '').lower() == 'ongoing') and (not is_first_day or (is_first_day and not missing_ekyc)) and (not attendance_exists_today)

    attendance_list = None
    if not show_ekyc and not show_attendance and not selected_date:
        attendance_list = BatchAttendance.objects.filter(batch=batch).order_by('-date')

    # choose template: split day-1 eKYC into its own template
    def render_template_for_batch():
        if show_ekyc:
            template_name = 'training_partner/attendance_per_batch_ekyc.html'
        else:
            template_name = 'training_partner/attendance_per_batch.html'
        return template_name

    context = {
        'batch': batch,
        'today': today,
        'participants': participants,
        'trainers': trainers_display,
        'beneficiaries': beneficiaries_display,
        'show_ekyc': show_ekyc,
        'show_attendance': show_attendance,
        'attendance_records': attendance_records,
        'selected_date': selected_date,
        'attendance_list': attendance_list,
        'attendance_obj': attendance_obj,
    }

    chosen_template = render_template_for_batch()
    return render(request, chosen_template, context)

@login_required
def partner_upload_attendance(request, batch_id):
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)
    batch = get_object_or_404(Batch, id=batch_id)

    if partner is None or batch.partner_id != partner.id:
        return HttpResponseForbidden("Not your batch")

    if request.method == 'POST' and request.FILES.get('attendance_csv'):
        f = request.FILES['attendance_csv']
        target_dir = os.path.join(settings.MEDIA_ROOT, f"attendance/partner_{partner.id}/batch_{batch.id}")
        os.makedirs(target_dir, exist_ok=True)
        dest_path = os.path.join(target_dir, f.name)
        with open(dest_path, 'wb+') as out:
            for chunk in f.chunks():
                out.write(chunk)
        messages.success(request, "Attendance CSV uploaded.")
        return redirect('partner_view_batch', batch_id=batch.id)

    messages.error(request, "Please upload a CSV file.")
    return redirect('partner_view_batch', batch_id=batch.id)


@login_required
def partner_upload_media(request, batch_id):
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)
    batch = get_object_or_404(Batch, id=batch_id)

    if partner is None or batch.partner_id != partner.id:
        return HttpResponseForbidden("Not your batch")

    if request.method == 'POST' and request.FILES.getlist('media_files'):
        files = request.FILES.getlist('media_files')
        target = os.path.join(settings.MEDIA_ROOT, f"partner_media/partner_{partner.id}/batch_{batch.id}")
        os.makedirs(target, exist_ok=True)
        for f in files:
            dest = os.path.join(target, f.name)
            with open(dest, 'wb+') as out:
                for chunk in f.chunks():
                    out.write(chunk)
        messages.success(request, "Media uploaded.")
        return redirect('partner_view_batch', batch_id=batch.id)

    messages.error(request, "Please select files to upload.")
    return redirect('partner_view_batch', batch_id=batch.id)


@login_required
def partner_generate_invoice(request, batch_id):
    partner = _get_partner_for_user(request.user)
    batch = get_object_or_404(Batch, id=batch_id)
    if partner is None or batch.partner_id != partner.id:
        return HttpResponseForbidden("Not your batch")
    messages.info(request, "Invoice generation is not implemented yet.")
    return redirect('partner_view_batch', batch_id=batch_id)


@login_required
def create_training_plan(request):
    if getattr(request.user, 'role', '').lower() != 'bmmu':
        return HttpResponseForbidden("Not authorized")

    if request.method == 'POST':
        form = TrainingPlanForm(request.POST, request.FILES or None)
        if form.is_valid():
            tp = form.save(commit=False)
            tp.created_by = request.user if hasattr(tp, 'created_by') else tp.created_by
            tp.save()
            messages.success(request, "Training plan proposed.")
            # redirect to training program management wrapper
            return redirect('dashboard')
    else:
        form = TrainingPlanForm()

    return render(request, 'bmmu/create_training_plan.html', {'form': form})


@login_required
def nominate_batch(request):
    if getattr(request.user, 'role', '').lower() != 'bmmu':
        return HttpResponseForbidden("Not authorized")

    if request.method == 'POST':
        form = BatchNominateForm(request.POST)
        if form.is_valid():
            batch = form.save(commit=False)
            try:
                choices = [c[0] for c in Batch._meta.get_field('status').choices]
                if 'nominated' in choices:
                    batch.status = 'nominated'
                elif 'proposed' in choices:
                    batch.status = 'proposed'
                else:
                    batch.status = getattr(batch, 'status', 'planned')
            except Exception:
                pass

            theme = getattr(batch.training_plan, 'theme', None)
            block = getattr(batch, 'block', None)
            partner = None
            if theme and block:
                try:
                    assignment = TrainingPartnerAssignment.objects.filter(theme=theme, block=block).select_related('partner').first()
                    if assignment:
                        partner = assignment.partner
                except Exception:
                    partner = None

            if partner:
                batch.partner = partner

            batch.created_by = request.user if hasattr(batch, 'created_by') else batch.created_by
            batch.save()
            messages.success(request, "Batch nominated and sent to partner (if assigned).")
            return redirect('dashboard')
    else:
        form = BatchNominateForm()
    return render(request, 'bmmu/nominate_batch.html', {'form': form})

@login_required
def smmu_dashboard(request):
    """
    SMMU dashboard:
     - Presents Mandal -> DistrictCategory -> District selectors
     - Displays beneficiaries for selected district (table hidden until a district is chosen)
     - Provides filter lists and pagination
     - Returns fragment HTML for AJAX or full wrapper for non-AJAX (keeps behaviour unchanged)
    """
    if getattr(request.user, "role", "").lower() != "smmu":
        return HttpResponseForbidden("🚫 Not authorized for this dashboard.")

    # Charts (kept same as before)
    chart1 = [random.randint(0, 100) for _ in range(10)]
    chart2 = [random.randint(0, 100) for _ in range(10)]
    chart_labels = [f"Metric {i+1}" for i in range(10)]

    # Selectors values
    mandals = list(Mandal.objects.all().order_by("name"))
    mandal_id = request.GET.get("mandal_id")  # optional

    # district category selection is tied to District objects
    selected_mandal = None
    if mandal_id:
        try:
            selected_mandal = Mandal.objects.get(pk=int(mandal_id))
        except Exception:
            selected_mandal = None

    # District list (optionally filtered by mandal)
    districts_qs = District.objects.all().order_by("district_name_en")
    if selected_mandal:
        districts_qs = districts_qs.filter(mandal=selected_mandal)
    districts = list(districts_qs)

    category_id = request.GET.get("category_id")
    # district category options — if a mandal is selected we can still show categories across districts in that mandal
    district_categories_qs = DistrictCategory.objects.values("category_name").distinct().order_by("category_name")
    if selected_mandal:
        # categories attached to districts in this mandal
        district_ids_for_mandal = districts_qs.values_list("district_id", flat=True)
        district_categories_qs = district_categories_qs.filter(district__district_id__in=district_ids_for_mandal)
    district_categories = [c["category_name"] for c in district_categories_qs]

    # selected district (this triggers table display)
    selected_district_id = request.GET.get("district_id")
    selected_district = None
    if selected_district_id:
        try:
            # District model uses district_id as primary key in your models
            selected_district = District.objects.get(district_id=int(selected_district_id))
        except Exception:
            selected_district = None

    # Build beneficiaries queryset: only when a district is selected we show results
    beneficiaries_qs = Beneficiary.objects.none()
    show_table = False
    if selected_district:
        show_table = True
        beneficiaries_qs = Beneficiary.objects.filter(district=selected_district).select_related("district", "block")

    # Apply search / filter / sort behaviour
    # For safety and to avoid touching the global _apply_search_filter_sort function, apply minimal logic:
    # - search on block, shg_name, gram_panchayat, village (icontains)
    # - filters passed as filter_<field>=comma_separated_values for fields in ALLOWED_FILTERS
    from django.db.models import Q

    # Global search
    q = request.GET.get("search", "").strip()
    if q and show_table:
        qobj = Q()
        qobj |= Q(block__block_name_en__icontains=q)  # block foreign key string
        qobj |= Q(shg_name__icontains=q)
        qobj |= Q(gram_panchayat__icontains=q)
        qobj |= Q(village__icontains=q)
        beneficiaries_qs = beneficiaries_qs.filter(qobj)

    # Filters allowed (these names are model fields or block FK)
    ALLOWED_FILTERS = {
        "block", "gram_panchayat", "village", "shg_name",
        "social_category", "designation_in_shg_vo_clf", "gender"
    }

    for key, val in request.GET.items():
        if not key.startswith("filter_") or not val:
            continue
        fld = key.replace("filter_", "")
        if fld not in ALLOWED_FILTERS:
            continue
        vals = [v.strip() for v in val.split(",") if v.strip()]
        if not vals:
            continue
        if fld == "block":
            # blocks come from Block.block_name_en; match by name
            beneficiaries_qs = beneficiaries_qs.filter(block__block_name_en__in=vals)
        else:
            # plain fields on Beneficiary
            beneficiaries_qs = beneficiaries_qs.filter(**{f"{fld}__in": vals})

    # Sorting
    sort_by = request.GET.get("sort_by", "")
    order = request.GET.get("order", "asc")
    allowed_sort_fields = {
        "block", "gram_panchayat", "village", "shg_name", "member_name",
        "social_category", "designation_in_shg_vo_clf", "gender", "date_of_birth"
    }
    if sort_by in allowed_sort_fields:
        sort_field = sort_by
        # for block sorting, use block__block_name_en
        if sort_by == "block":
            sort_field = "block__block_name_en"
        if order == "desc":
            beneficiaries_qs = beneficiaries_qs.order_by(f"-{sort_field}")
        else:
            beneficiaries_qs = beneficiaries_qs.order_by(sort_field)
    else:
        beneficiaries_qs = beneficiaries_qs.order_by("id")

    # Pagination
    paginator = None
    page_obj = []
    if show_table:
        paginator = Paginator(beneficiaries_qs, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)
    else:
        paginator = None
        page_obj = []

    # Build groupable_values (for filters) limited to this district (if show_table) or empty lists otherwise
    groupable_values = {}
    # Blocks: use Block model for block names in the selected district
    if selected_district:
        blocks_for_district = list(Block.objects.filter(district=selected_district).order_by("block_name_en").values_list("block_name_en", flat=True).distinct())
        # mark aspirational blocks (we will flag in template)
        aspirational_blocks = set(Block.objects.filter(district=selected_district, is_aspirational=True).values_list("block_name_en", flat=True))
    else:
        blocks_for_district = []
        aspirational_blocks = set()

    # other groupable values from beneficiaries (distinct)
    if selected_district:
        gp_vals = list(beneficiaries_qs.order_by("gram_panchayat").values_list("gram_panchayat", flat=True).distinct())
        village_vals = list(beneficiaries_qs.order_by("village").values_list("village", flat=True).distinct())
        shg_vals = list(beneficiaries_qs.order_by("shg_name").values_list("shg_name", flat=True).distinct())
        social_vals = list(beneficiaries_qs.order_by("social_category").values_list("social_category", flat=True).distinct())
        desig_vals = list(beneficiaries_qs.order_by("designation_in_shg_vo_clf").values_list("designation_in_shg_vo_clf", flat=True).distinct())
        gender_vals = list(beneficiaries_qs.order_by("gender").values_list("gender", flat=True).distinct())
    else:
        gp_vals = village_vals = shg_vals = social_vals = desig_vals = gender_vals = []

    # normalize values lists (remove None/empty)
    def _clean(vals):
        return [v for v in vals if v is not None and str(v).strip() != ""]

    groupable_values["block"] = _clean(blocks_for_district)
    groupable_values["gram_panchayat"] = _clean(gp_vals)
    groupable_values["village"] = _clean(village_vals)
    groupable_values["shg_name"] = _clean(shg_vals)
    groupable_values["social_category"] = _clean(social_vals)
    groupable_values["designation_in_shg_vo_clf"] = _clean(desig_vals)
    groupable_values["gender"] = _clean(gender_vals)

    # Context for template
    context = {
        "chart1": chart1,
        "chart2": chart2,
        "chart_labels": chart_labels,
        "chart1_json": json.dumps(chart1),
        "chart2_json": json.dumps(chart2),
        "chart_labels_json": json.dumps(chart_labels),
        "mandals": mandals,
        "districts": districts,
        "district_categories": district_categories,
        "selected_mandal": getattr(selected_mandal, "id", None) if selected_mandal else None,
        "selected_category": int(category_id) if category_id and category_id.isdigit() else None,
        "selected_district": getattr(selected_district, "district_id", None) if selected_district else None,
        "page_obj": page_obj,
        "paginator": paginator,
        "show_table": show_table,
        "groupable_values": groupable_values,
        "groupable_values_json": json.dumps(groupable_values, default=str),
        "aspirational_blocks": list(aspirational_blocks),
        "search_query": request.GET.get("search", ""),
        "sort_by": sort_by,
        "order": order,
    }

    # If AJAX: return fragment HTML as before
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = render_to_string("smmu/smmu_dashboard.html", context, request=request)
        return HttpResponse(html)

    # Non-AJAX: embed fragment inside wrapper (existing behaviour)
    default_content = render_to_string("smmu/smmu_dashboard.html", context, request=request)
    return render(request, "dashboard.html", {"user": request.user, "default_content": default_content})

def smmu_fragment_context(request, paginate=True):
    """
    Build context for SMMU fragment.
     - mandals
     - district_categories
     - beneficiaries for chosen district (only if district provided)
     - training plans where current user is theme_expert, along with their batches
    """
    # 1. Mandals and district categories for the selects
    mandals = list(Mandal.objects.all().order_by('name').values('id', 'name'))
    district_categories = list(DistrictCategory.objects.all().order_by('category_name').values('id', 'category_name'))

    # 2. If district provided, prepare beneficiaries queryset; otherwise empty
    district_id = request.GET.get('district_id') or request.GET.get('district')
    beneficiaries_qs = Beneficiary.objects.none()
    if district_id:
        try:
            did = int(district_id)
            beneficiaries_qs = Beneficiary.objects.filter(district_id=did).select_related('district', 'block')
        except Exception:
            beneficiaries_qs = Beneficiary.objects.none()

    # 3. Optionally apply existing search/filter/sort logic if available
    if _apply_search_filter_sort and beneficiaries_qs is not None:
        try:
            beneficiaries_qs = _apply_search_filter_sort(beneficiaries_qs, request.GET)
        except Exception:
            # if anything fails, fall back to unfiltered qs
            pass

    # 4. Pagination
    if paginate:
        paginator = Paginator(beneficiaries_qs, 20)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
    else:
        paginator = None
        page_obj = beneficiaries_qs

    # 5. Training Plans & Batches: show plans where the logged-in user is the theme_expert.
    #    Attach batches per plan for easy rendering.
    plans_qs = TrainingPlan.objects.filter(theme_expert=request.user).order_by('-created_at')
    plan_ids = list(plans_qs.values_list('id', flat=True))
    batches_map = {}
    if plan_ids:
        batches = Batch.objects.filter(training_plan_id__in=plan_ids).order_by('-start_date')
        for b in batches:
            batches_map.setdefault(b.training_plan_id, []).append({
                'id': b.id,
                'code': b.code or f"Batch-{b.id}",
                'title': getattr(b.training_plan, 'training_name', '') if getattr(b, 'training_plan', None) else '',
                'start_date': b.start_date,
                'end_date': b.end_date,
                'status': b.status,
                'centre_proposed': b.centre_proposed,
                'created_at': b.created_at,
            })

    plans_list = []
    for p in plans_qs:
        plans_list.append({
            'id': p.id,
            'training_name': p.training_name,
            'theme': p.theme,
            'approval_status': p.approval_status,
            'related_batches': batches_map.get(p.id, []),
        })

    context = {
        'mandals': mandals,
        'district_categories': district_categories,
        'page_obj': page_obj,
        'paginator': paginator,
        'beneficiaries_count': beneficiaries_qs.count() if hasattr(beneficiaries_qs, 'count') else 0,
        'training_plans': plans_list,
    }
    return context


def api_districts_for_mandal(request):
    """
    Simple JSON endpoint: ?mandal_id=<id> -> { districts: [{id,name,category_id}, ...] }
    """
    mandal_id = request.GET.get('mandal_id')
    if not mandal_id:
        return JsonResponse({'error': 'mandal_id required'}, status=400)
    try:
        mid = int(mandal_id)
    except Exception:
        return JsonResponse({'error': 'invalid mandal_id'}, status=400)

    qs = District.objects.filter(mandal_id=mid).order_by('name').values('id', 'name', 'district_category_id')
    return JsonResponse({'districts': list(qs)})

@login_required
def smmu_training_requests(request):
    if getattr(request.user, 'role', '').lower() != 'smmu':
        return HttpResponseForbidden("Not authorized")

    # Collect canonical status tokens available in Batch.STATUS_CHOICES
    valid_statuses = {c[0] for c in Batch._meta.get_field('status').choices}

    # Common statuses we want to show initially (intersection with actual choices)
    wanted = {'PENDING', 'PROPOSED', 'DRAFT'}
    statuses_to_show = list(valid_statuses.intersection(wanted))

    # Core filter: batches for plans where current user is theme_expert
    qs = Batch.objects.filter(
        training_plan__theme_expert=request.user
    )
    if statuses_to_show:
        qs = qs.filter(status__in=statuses_to_show)

    # Order newest first
    qs = qs.select_related('training_plan', 'partner').order_by('-created_at')

    # Render fragment
    fragment = render_to_string('smmu/training_requests.html', {'requests': qs}, request=request)
    return render(request, 'dashboard.html', {'user': request.user, 'default_content': fragment})


@login_required
def smmu_request_detail(request, batch_id):
    if getattr(request.user, 'role', '').lower() != 'smmu':
        return HttpResponseForbidden("Not authorized")

    batch = get_object_or_404(
        Batch.objects.select_related('training_plan', 'partner')
        .prefetch_related('trainers', 'beneficiaries'),
        id=batch_id,
        training_plan__theme_expert=request.user
    )

    trainer_cert_map = {}
    trainer_ids = [t.id for t in batch.trainers.all()]
    if trainer_ids:
        certs = MasterTrainerCertificate.objects.filter(trainer_id__in=trainer_ids).order_by('trainer_id', '-issued_on', '-created_at')
        for c in certs:
            prev = trainer_cert_map.get(c.trainer_id)
            if not prev:
                trainer_cert_map[c.trainer_id] = {'certificate_number': c.certificate_number, 'issued_on': c.issued_on, 'created_at': c.created_at}
            else:
                prev_issued = prev.get('issued_on')
                cur_issued = c.issued_on
                if (cur_issued and (not prev_issued or cur_issued > prev_issued)) or (not prev_issued and not cur_issued and c.created_at > prev.get('created_at')):
                    trainer_cert_map[c.trainer_id] = {'certificate_number': c.certificate_number, 'issued_on': c.issued_on, 'created_at': c.created_at}
    trainer_cert_map = {k: (v['certificate_number'] if v and v.get('certificate_number') else None) for k, v in trainer_cert_map.items()}

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip().lower()

        # Build case-insensitive map of statuses
        status_choices = {c[0].lower(): c[0] for c in Batch._meta.get_field('status').choices}

        def set_status_if_available(token_lower):
            token_lower = token_lower.lower()
            if token_lower in status_choices:
                batch.status = status_choices[token_lower]
                return True
            return False

        if action == 'approve':
            # Copy proposed centre if confirmed not set
            if getattr(batch, 'centre_proposed', None) and not getattr(batch, 'centre', None):
                batch.centre = batch.centre_proposed

            # Prefer ONGOING after approval
            set_success = False
            if set_status_if_available('ONGOING'):
                set_success = True
            else:
                for fallback in ('PENDING', 'APPROVED', 'PROPOSED', 'DRAFT'):
                    if set_status_if_available(fallback):
                        set_success = True
                        break

            batch.save()
            if set_success:
                messages.success(request, "Batch approved and status updated.")
            else:
                messages.success(request, "Batch approved (status token not mapped cleanly).")

        elif action == 'reject':
            if set_status_if_available('REJECTED'):
                batch.save()
                messages.info(request, "Batch rejected.")
            else:
                messages.info(request, "Batch rejection recorded (status token not mapped).")

        return redirect('smmu_training_requests')

    # GET: render
    partner = getattr(batch, 'partner', None)

    # Robustly fetch submissions for partner — try the model directly, then fallback to reverse manager
    submissions = []
    if partner:
        try:
            submissions = TrainingPartnerSubmission.objects.filter(partner=partner).order_by('-uploaded_on')[:12]
        except Exception:
            try:
                submissions = partner.trainingsubmission_set.all().order_by('-uploaded_on')[:12]
            except Exception:
                submissions = []

    beneficiaries = list(batch.beneficiaries.all())
    today = date.today()
    for b in beneficiaries:
        dob = getattr(b, 'date_of_birth', None)
        age = None
        if dob:
            try:
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            except Exception:
                age = None
        setattr(b, 'age', age)

    fragment_html = render_to_string('smmu/request_detail.html', {
        'batch': batch,
        'partner': partner,
        'submissions': submissions,
        'beneficiaries': beneficiaries,
        'today': today,
        'trainer_cert_map': trainer_cert_map,        

    }, request=request)

    return render(request, 'dashboard.html', {'user': request.user, 'default_content': fragment_html})


FY_RE = re.compile(r'^\d{4}-\d{2}$')


@login_required
def smmu_create_partner_target(request):
    """
    GET: render the create_training_partner_targets.html form (SMMU only)
    POST: create/update a TrainingPartnerTargets record based on posted data.
    This view does NOT rely on TrainingPlanPartner (which you said doesn't exist).
    """
    # Role guard
    if getattr(request.user, 'role', '').lower() != 'smmu':
        return HttpResponseForbidden("Not authorized")

    # ---------- GET: render form ----------
    if request.method == 'GET':
        partners = TrainingPartner.objects.all().order_by('name')
        # Modules (training plans) that this SMMU is theme_expert for
        modules = TrainingPlan.objects.filter(theme_expert=request.user).order_by('-created_at')
        districts = District.objects.order_by('district_name_en')

        # There are no assignment records (TrainingPlanPartner) in this project.
        # We keep plans_with_meta but set assign=None for each plan so template shows "Not assigned".
        plans_with_meta = [{'obj': p, 'assign': None} for p in modules]

        context = {
            'partners': partners,
            'modules': modules,
            'districts': districts,
            'plans_with_meta': plans_with_meta,
        }
        return render(request, 'smmu/create_training_partner_targets.html', context)

    # ---------- POST: create / update target ----------
    if request.method != 'POST':
        return HttpResponseBadRequest("Only GET and POST are supported at this endpoint.")

    # Read POSTed fields
    partner_id = request.POST.get('partner_id')
    district_id = request.POST.get('district_id')
    training_plan_id = request.POST.get('training_plan_id')
    target_type = (request.POST.get('target_type') or '').upper()
    target_count = request.POST.get('target_count')
    notes = request.POST.get('notes', '')
    financial_year = (request.POST.get('financial_year') or '').strip()
    post_theme = request.POST.get('theme')

    # Basic presence checks
    if not partner_id or not target_type or target_count is None or financial_year == '':
        return JsonResponse({'success': False, 'error': 'Missing required fields: partner_id, target_type, target_count, financial_year are required.'}, status=400)

    # Validate FY format
    if not FY_RE.match(financial_year):
        return JsonResponse({'success': False, 'error': "financial_year must be like '2023-24'."}, status=400)

    # Fetch partner
    try:
        partner = TrainingPartner.objects.get(pk=int(partner_id))
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid partner.'}, status=400)

    # Optional: fetch district and training plan if provided
    district = None
    training_plan = None
    if district_id:
        try:
            district = District.objects.get(pk=int(district_id))
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid district.'}, status=400)

    if training_plan_id:
        try:
            training_plan = TrainingPlan.objects.get(pk=int(training_plan_id))
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid training plan/module.'}, status=400)

    # Validate numeric target_count
    try:
        tc = int(target_count)
        if tc < 0:
            raise ValueError()
    except Exception:
        return JsonResponse({'success': False, 'error': 'target_count must be a non-negative integer.'}, status=400)

    # Validate target_type
    if target_type not in ('MODULE', 'DISTRICT', 'THEME'):
        return JsonResponse({'success': False, 'error': f'Invalid target_type: {target_type}'}, status=400)

    # Business-rule enforcement
    if target_type == 'MODULE':
        if not training_plan:
            return JsonResponse({'success': False, 'error': 'training_plan_id is required for MODULE targets.'}, status=400)
        if not district:
            return JsonResponse({'success': False, 'error': 'district_id is required for MODULE targets.'}, status=400)
    elif target_type == 'DISTRICT':
        if not district:
            return JsonResponse({'success': False, 'error': 'district_id is required for DISTRICT targets.'}, status=400)
    elif target_type == 'THEME':
        # infer theme (priority: posted theme -> training_plan.theme -> SMMU's theme via TrainingPlan)
        inferred_theme = None
        if post_theme:
            inferred_theme = post_theme.strip()
        elif training_plan and getattr(training_plan, 'theme', None):
            inferred_theme = training_plan.theme
        else:
            inferred = TrainingPlan.objects.filter(theme_expert=request.user).values_list('theme', flat=True).distinct().first()
            if inferred:
                inferred_theme = inferred
        if not inferred_theme:
            return JsonResponse({'success': False, 'error': 'Unable to determine theme for THEME target. Provide "theme" or select a module with a theme, or ensure the logged-in SMMU is a theme_expert.'}, status=400)

    # Build lookup kwargs for update_or_create to avoid duplicates
    lookup = {
        'partner': partner,
        'target_type': target_type,
        'financial_year': financial_year
    }
    defaults = {
        'allocated_by': request.user,
        'target_count': tc,
        'notes': notes,
    }

    if target_type == 'MODULE':
        lookup.update({'training_plan': training_plan, 'district': district})
    elif target_type == 'DISTRICT':
        lookup.update({'district': district})
    else:  # THEME
        lookup.update({'theme': inferred_theme})

    # Create or update within a transaction
    try:
        with transaction.atomic():
            obj, created = TrainingPartnerTargets.objects.update_or_create(defaults=defaults, **lookup)
            # run model validation (model.clean) and save
            obj.full_clean()
            obj.save()
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    partner_name = getattr(obj, "partner", None)
    partner_name = partner_name.name if partner_name else None

    return JsonResponse({
        "success": True,
        "created": bool(created),
        "target_id": obj.id,
        "partner_name": partner_name,
        "message": f"Target created for {partner_name}." if created else "Target updated."
    })

@login_required
def dmmu_dashboard(request):
    if getattr(request.user, "role", "").lower() != "dmmu":
        return HttpResponseForbidden("🚫 Not authorized for this dashboard.")

    # Charts (same as SMMU)
    chart1 = [random.randint(0, 100) for _ in range(10)]
    chart2 = [random.randint(0, 100) for _ in range(10)]
    chart_labels = [f"Metric {i+1}" for i in range(10)]

    # Assigned district
    assigned_district = None
    try:
        from .models import DmmuDistrictAssignment
        assignment = DmmuDistrictAssignment.objects.filter(user=request.user).select_related('district').first()
        if assignment:
            assigned_district = assignment.district
    except Exception:
        assigned_district = None

    # Blocks dropdown (for UI)
    blocks = list(Block.objects.filter(district=assigned_district).order_by("block_name_en")) if assigned_district else []

    # aspirational blocks set
    aspirational_blocks = set()
    if assigned_district:
        aspirational_blocks = set(Block.objects.filter(district=assigned_district, is_aspirational=True).values_list("block_name_en", flat=True))

    # Selected block and aspirational block params from GET
    selected_block_name = request.GET.get("block_name") or None
    asp_block_name = request.GET.get("asp_block") or None

    selected_block_obj = None
    if selected_block_name and assigned_district:
        selected_block_obj = Block.objects.filter(district=assigned_district, block_name_en__iexact=selected_block_name).first()

    # Build base queryset restricted to assigned district
    beneficiaries_qs = Beneficiary.objects.none()
    show_table = False
    if assigned_district:
        beneficiaries_qs = Beneficiary.objects.filter(district=assigned_district).select_related("district", "block")
        show_table = True

    # Apply block filters (selected block OR aspirational block if provided)
    # Priority: explicit block_name (selBlock) overrides aspirational selection.
    if show_table and selected_block_obj:
        beneficiaries_qs = beneficiaries_qs.filter(block__block_name_en__iexact=selected_block_obj.block_name_en)
    elif show_table and asp_block_name:
        # Filter by aspirational block name (only those blocks which are aspirational)
        beneficiaries_qs = beneficiaries_qs.filter(block__block_name_en__iexact=asp_block_name, block__is_aspirational=True)

    # Search
    from django.db.models import Q
    q = request.GET.get("search", "").strip()
    if q and show_table:
        qobj = Q()
        qobj |= Q(block__block_name_en__icontains=q)
        qobj |= Q(shg_name__icontains=q)
        qobj |= Q(gram_panchayat__icontains=q)
        qobj |= Q(village__icontains=q)
        beneficiaries_qs = beneficiaries_qs.filter(qobj)

    # Column filters
    ALLOWED_FILTERS = {
        "block", "gram_panchayat", "village", "shg_name",
        "social_category", "designation_in_shg_vo_clf", "gender"
    }
    for key, val in request.GET.items():
        if not key.startswith("filter_") or not val:
            continue
        fld = key.replace("filter_", "")
        if fld not in ALLOWED_FILTERS:
            continue
        vals = [v.strip() for v in val.split(",") if v.strip()]
        if not vals:
            continue
        if fld == "block":
            beneficiaries_qs = beneficiaries_qs.filter(block__block_name_en__in=vals)
        else:
            beneficiaries_qs = beneficiaries_qs.filter(**{f"{fld}__in": vals})

    # Sorting
    sort_by = request.GET.get("sort_by", "")
    order = request.GET.get("order", "asc")
    allowed_sort_fields = {
        "block", "gram_panchayat", "village", "shg_name", "member_name",
        "social_category", "designation_in_shg_vo_clf", "gender", "date_of_birth"
    }
    if sort_by in allowed_sort_fields:
        sort_field = sort_by
        if sort_by == "block":
            sort_field = "block__block_name_en"
        beneficiaries_qs = beneficiaries_qs.order_by(f"-{sort_field}" if order == "desc" else sort_field)
    else:
        beneficiaries_qs = beneficiaries_qs.order_by("id")

    # === Pagination: explicit total_rows & total_pages (no artificial cap) ===
    per_page = 20  # change if needed
    total_rows = beneficiaries_qs.count() if show_table else 0
    import math
    total_pages = math.ceil(total_rows / per_page) if total_rows else 1

    # clamp requested page
    page_param = request.GET.get("page", "1")
    try:
        requested_page = int(page_param)
    except Exception:
        requested_page = 1
    if requested_page < 1:
        requested_page = 1
    if requested_page > total_pages:
        requested_page = total_pages

    # build paginator and get page
    paginator = Paginator(beneficiaries_qs, per_page) if show_table else None
    page_obj = paginator.get_page(requested_page) if paginator else []

    # page window for template (show +-5 pages)
    window = 5
    page_window_start = max(1, requested_page - window)
    page_window_end = min(total_pages, requested_page + window)

    # groupable values scoped to the already-filtered beneficiaries_qs
    def _clean(vals):
        return [v for v in vals if v is not None and str(v).strip() != ""]

    if assigned_district:
        blocks_for_district = list(Block.objects.filter(district=assigned_district).order_by("block_name_en").values_list("block_name_en", flat=True).distinct())
        gp_vals = list(beneficiaries_qs.order_by("gram_panchayat").values_list("gram_panchayat", flat=True).distinct())
        village_vals = list(beneficiaries_qs.order_by("village").values_list("village", flat=True).distinct())
        shg_vals = list(beneficiaries_qs.order_by("shg_name").values_list("shg_name", flat=True).distinct())
        social_vals = list(beneficiaries_qs.order_by("social_category").values_list("social_category", flat=True).distinct())
        desig_vals = list(beneficiaries_qs.order_by("designation_in_shg_vo_clf").values_list("designation_in_shg_vo_clf", flat=True).distinct())
        gender_vals = list(beneficiaries_qs.order_by("gender").values_list("gender", flat=True).distinct())
    else:
        blocks_for_district = []
        gp_vals = village_vals = shg_vals = social_vals = desig_vals = gender_vals = []
        aspirational_blocks = set()

    groupable_values = {
        "block": _clean(blocks_for_district),
        "gram_panchayat": _clean(gp_vals),
        "village": _clean(village_vals),
        "shg_name": _clean(shg_vals),
        "social_category": _clean(social_vals),
        "designation_in_shg_vo_clf": _clean(desig_vals),
        "gender": _clean(gender_vals),
    }

    # training plans / batches (unchanged)
    plans_qs = TrainingPlan.objects.filter(theme_expert=request.user).order_by('-created_at')
    plan_ids = list(plans_qs.values_list('id', flat=True))
    batches_map = {}
    if plan_ids:
        batches = Batch.objects.filter(training_plan_id__in=plan_ids).order_by('-start_date')
        for b in batches:
            batches_map.setdefault(b.training_plan_id, []).append({
                'id': b.id,
                'code': b.code or f"Batch-{b.id}",
                'title': getattr(b.training_plan, 'training_name', '') if getattr(b, 'training_plan', None) else '',
                'start_date': b.start_date,
                'end_date': b.end_date,
                'status': b.status,
                'centre_proposed': b.centre_proposed,
                'created_at': b.created_at,
            })

    plans_list = []
    for p in plans_qs:
        plans_list.append({
            'id': p.id,
            'training_name': p.training_name,
            'theme': p.theme,
            'approval_status': getattr(p, 'approval_status', None),
            'related_batches': batches_map.get(p.id, []),
        })

    assigned_district_short = getattr(assigned_district, "district_name_en", None) if assigned_district else None
    selected_block_for_ctx = selected_block_obj.block_name_en if selected_block_obj else None

    context = {
        "chart1": chart1,
        "chart2": chart2,
        "chart_labels": chart_labels,
        "chart1_json": json.dumps(chart1),
        "chart2_json": json.dumps(chart2),
        "chart_labels_json": json.dumps(chart_labels),
        "blocks": blocks,
        "assigned_district": assigned_district_short,
        "aspirational_blocks": list(aspirational_blocks),
        "selected_block": selected_block_for_ctx,
        "page_obj": page_obj,
        "paginator": paginator,
        "show_table": show_table,
        "groupable_values": groupable_values,
        "groupable_values_json": json.dumps(groupable_values, default=str),
        "training_plans": plans_list,
        "beneficiaries_count": total_rows,
        "search_query": request.GET.get("search", ""),
        "sort_by": sort_by,
        "order": order,
        "total_pages": total_pages,
        "current_page": requested_page,
        "per_page": per_page,
        "page_window_start": page_window_start,
        "page_window_end": page_window_end,
        "asp_block": asp_block_name,
        "show_prev_ellipsis": page_window_start > 2,
        "show_prev_first_page_link": page_window_start > 1,
        "show_next_ellipsis": page_window_end < (total_pages - 1),
        "show_next_last_page_link": page_window_end < total_pages,        
    }

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = render_to_string("dmmu/dmmu_dashboard.html", context, request=request)
        return HttpResponse(html)

    default_content = render_to_string("dmmu/dmmu_dashboard.html", context, request=request)
    return render(request, "dashboard.html", {"user": request.user, "default_content": default_content})

@login_required
def dmmu_training_requests(request):
    if getattr(request.user, 'role', '').lower() != 'dmmu':
        return HttpResponseForbidden("Not authorized")

    assigned_district = None
    try:
        assignment = DmmuDistrictAssignment.objects.filter(user=request.user).select_related('district').first()
        if assignment:
            assigned_district = assignment.district
    except Exception:
        assigned_district = None

    qs = TrainingRequest.objects.none()

    try:
        if assigned_district:
            # Find BMMU users under this district
            try:
                block_assigns = BmmuBlockAssignment.objects.filter(
                    block__district=assigned_district
                ).values_list('user_id', flat=True)
                user_ids = list(block_assigns)
                qs_block = (
                    TrainingRequest.objects.filter(level__iexact='BLOCK', created_by_id__in=user_ids)
                    if user_ids else TrainingRequest.objects.none()
                )
            except Exception:
                qs_block = TrainingRequest.objects.none()

            # Requests directly tied to this district
            try:
                qs_other = TrainingRequest.objects.filter(district=assigned_district)
            except Exception:
                qs_other = TrainingRequest.objects.none()
        else:
            qs_block = TrainingRequest.objects.none()
            qs_other = TrainingRequest.objects.none()

        qs = (qs_block | qs_other).distinct().order_by('-created_at')

        # Read and normalize status filter
        requested_status = (request.GET.get('status') or '').strip().upper()

        # Allowed statuses from model
        VALID_STATUSES = [c[0].upper() for c in getattr(TrainingRequest, 'STATUS_CHOICES', [])]

        # Apply filter if provided
        if requested_status:
            if requested_status in VALID_STATUSES:
                qs = qs.filter(status__iexact=requested_status)
            else:
                # Invalid filter → empty queryset
                qs = TrainingRequest.objects.none()
        else:
            # Only apply fallback if no filter AND no data
            if not qs.exists():
                qs = TrainingRequest.objects.filter(level__iexact='BLOCK').order_by('-created_at')[:200]

    except Exception as e:
        logger.exception("dmmu_training_requests: unexpected error building queryset: %s", e)
        qs = TrainingRequest.objects.none()

    # Prepare dropdown options (add "All" on top)
    status_choices = [('', 'All')] + list(getattr(TrainingRequest, 'STATUS_CHOICES', []))

    fragment = render_to_string(
        'dmmu/training_requests.html',
        {
            'requests': qs,
            'status_choices': status_choices,
            'selected_status': requested_status,
        },
        request=request,
    )

    return render(
        request,
        'dashboard.html',
        {
            'user': request.user,
            'default_content': fragment,
        },
    )

@login_required
def dmmu_request_detail(request, request_id):
    """
    DMMU view for a TrainingRequest detail page. Shows:
      - training_request info
      - all batches created from it
      - per-batch centres, rooms, submissions, participants
      - ability to pick master-trainers per batch (designation depends on request.level)
      - approve all batches & set training_request.status -> ONGOING and batch.status -> ONGOING
    """
    if getattr(request.user, 'role', '').lower() != 'dmmu':
        return HttpResponseForbidden("Not authorized")

    # safe fetch training request
    tr = get_object_or_404(
        TrainingRequest.objects.select_related('training_plan', 'partner'),
        id=request_id
    )

    # Check DMMU permission for BLOCK-level requests (best-effort)
    assigned_district = None
    try:
        assignment = DmmuDistrictAssignment.objects.filter(user=request.user).select_related('district').first()
        if assignment:
            assigned_district = assignment.district
    except Exception:
        assigned_district = None

    if tr.level and (tr.level or '').upper() == 'BLOCK' and assigned_district:
        try:
            creator = getattr(tr, 'created_by', None)
            allowed = False
            if creator:
                try:
                    creator_assigns = BmmuBlockAssignment.objects.filter(user=creator).select_related('block__district')
                    for a in creator_assigns:
                        if getattr(a.block, 'district', None) == assigned_district:
                            allowed = True
                            break
                except Exception:
                    try:
                        if getattr(tr, 'district', None) == assigned_district:
                            allowed = True
                    except Exception:
                        allowed = False
            if not allowed:
                return HttpResponseForbidden("Not authorized to view this request")
        except Exception:
            pass

    # POST: handle trainer assignment and approve-all
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip().lower()

        # assign trainers to batches (multi-checkbox allowed)
        for b in Batch.objects.filter(request=tr):
            key = f"trainer_for_batch_{b.id}"
            posted_ids = request.POST.getlist(key) or []

            try:
                # Delete previous participations for this batch (safe)
                try:
                    TrainerBatchParticipation.objects.filter(batch=b).delete()
                except Exception:
                    # fallback: if batch exposes m2m trainers, clear it
                    try:
                        if hasattr(b, 'trainers'):
                            b.trainers.clear()
                    except Exception:
                        pass

                # Create new TrainerBatchParticipation rows for each posted id
                for tid in [x for x in posted_ids if x]:
                    try:
                        tid_int = int(tid)
                    except Exception:
                        continue

                    trainer_obj = None
                    # prefer MasterTrainer model
                    try:
                        trainer_obj = MasterTrainer.objects.filter(id=tid_int).first()
                    except Exception:
                        trainer_obj = None

                    if not trainer_obj:
                        # fallback: check User, then try to match to MasterTrainer via user FK if your MasterTrainer links to user
                        try:
                            trainer_user = User.objects.filter(id=tid_int).first()
                            if trainer_user:
                                # try to find MasterTrainer for this user
                                try:
                                    trainer_obj = MasterTrainer.objects.filter(user=trainer_user).first()
                                except Exception:
                                    trainer_obj = None
                                # if still None, we may add user to m2m (if available)
                                if not trainer_obj and hasattr(b, 'trainers'):
                                    try:
                                        b.trainers.add(trainer_user)
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                    if trainer_obj:
                        try:
                            TrainerBatchParticipation.objects.create(batch=b, trainer=trainer_obj, participated=False)
                        except Exception:
                            # fallback to m2m add if available
                            try:
                                if hasattr(b, 'trainers'):
                                    b.trainers.add(trainer_obj)
                            except Exception:
                                logger.exception("dmmu_request_detail: failed to add trainer (fallback) %s to batch %s", tid_int, b.id)
            except Exception:
                logger.exception("dmmu_request_detail: failed processing posted trainers for batch %s", b.id)

        # Approve all => set request.status and all batches.status
        try:
            india_tz = ZoneInfo("Asia/Kolkata")
        except Exception:
            india_tz = None
        today = datetime.now(tz=india_tz).date() if india_tz else timezone.localdate()
        if action == 'approve_all':
            try:
                if hasattr(tr, 'status'):
                    tr.status = 'ONGOING'
                    tr.save()
            except Exception:
                logger.exception("dmmu_request_detail: failed to update training request status")

            try:
                batches = Batch.objects.filter(request=tr)
                for b in batches:
                    try:
                        # Determine status based on start date
                        batch_date = b.start_date  # Replace with actual field if different
                        if batch_date == today:
                            desired_status = 'ONGOING'
                        else:
                            desired_status = 'SCHEDULED'

                        # Choose appropriate token from choices if defined
                        try:
                            choices = [c[0] for c in Batch._meta.get_field('status').choices]
                            if desired_status in choices:
                                b.status = desired_status
                            else:
                                # fallback if desired status isn't a valid choice
                                b.status = choices[0] if choices else 'ONGOING'
                        except Exception:
                            b.status = desired_status
                        b.save()
                    except Exception:
                        logger.exception("dmmu_request_detail: batch %s status update failed", b.id)

                messages.success(request, "All batches approved and training marked accordingly.")
            except Exception:
                logger.exception("dmmu_request_detail: failed to set batch statuses")

            return redirect('dmmu_training_requests')

        # if action was only trainer assignment
        if action in ('assign_trainers', ''):
            messages.success(request, "Trainer assignments saved.")
            return redirect('dmmu_request_detail', request_id=tr.id)

    # GET: prepare display data

    # Retrieve batches for this request
    batches_qs = Batch.objects.filter(request=tr).select_related('centre').order_by('start_date', 'id')

    batch_details = []
    for b in batches_qs:
        centre = getattr(b, 'centre', None)

        # rooms and submissions
        rooms = []
        submissions = []
        try:
            if centre and hasattr(centre, 'rooms'):
                rooms = list(centre.rooms.all())
        except Exception:
            rooms = []
        try:
            if centre and hasattr(centre, 'submissions'):
                submissions = list(centre.submissions.all())
        except Exception:
            submissions = []

        # beneficiaries assigned for this batch: prefer BatchBeneficiary join model
        beneficiaries = []
        try:
            if hasattr(b, 'batch_beneficiaries'):
                beneficiaries = [bb.beneficiary for bb in b.batch_beneficiaries.select_related('beneficiary').all()]
            elif hasattr(b, 'beneficiaries'):
                beneficiaries = list(b.beneficiaries.all())
        except Exception:
            beneficiaries = []

        # assigned trainer ids for pre-check in template
        assigned_trainer_ids = []
        try:
            assigned_trainer_ids = list(TrainerBatchParticipation.objects.filter(batch=b).values_list('trainer_id', flat=True))
        except Exception:
            try:
                if hasattr(b, 'trainers'):
                    assigned_trainer_ids = list(b.trainers.values_list('id', flat=True))
            except Exception:
                assigned_trainer_ids = []

        # enriched centre_info dict for template
        centre_info = {}
        if centre:
            try:
                centre_info = {
                    'serial_number': getattr(centre, 'serial_number', None),
                    'district': getattr(centre, 'district', None),
                    'coord_name': getattr(centre, 'centre_coord_name', None),
                    'coord_mobile': getattr(centre, 'centre_coord_mob_number', None),
                    'venue_name': getattr(centre, 'venue_name', None),
                    'venue_address': getattr(centre, 'venue_address', None),
                    'training_hall_count': getattr(centre, 'training_hall_count', None),
                    'training_hall_capacity': getattr(centre, 'training_hall_capacity', None),
                    'security_arrangements': getattr(centre, 'security_arrangements', None),
                    'toilets_bathrooms': getattr(centre, 'toilets_bathrooms', None),
                    'power_water_facility': getattr(centre, 'power_water_facility', None),
                    'medical_kit': getattr(centre, 'medical_kit', None),
                    'centre_type': getattr(centre, 'centre_type', None),
                    'open_space': getattr(centre, 'open_space', None),
                    'field_visit_facility': getattr(centre, 'field_visit_facility', None),
                    'transport_facility': getattr(centre, 'transport_facility', None),
                    'dining_facility': getattr(centre, 'dining_facility', None),
                    'other_details': getattr(centre, 'other_details', None),
                    'created_at': getattr(centre, 'created_at', None),
                }
            except Exception:
                centre_info = {}

        batch_details.append({
            'batch': b,
            'centre': centre,
            'centre_info': centre_info,
            'rooms': rooms,
            'submissions': submissions,
            'beneficiaries': beneficiaries,
            'assigned_trainer_ids': assigned_trainer_ids,
        })

    # Participants attached to the TrainingRequest
    participants = []
    try:
        participants = list(tr.beneficiaries.all())
    except Exception:
        participants = []

    # compute participant helpers (display_name, display_mobile, display_location, age)
    
    try:
        india_tz = ZoneInfo("Asia/Kolkata")
    except Exception:
        india_tz = None
    today = datetime.now(tz=india_tz).date() if india_tz else timezone.localdate()
    
    for p in participants:
        dob = getattr(p, 'date_of_birth', None)
        age = None
        if dob:
            try:
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            except Exception:
                age = None
        setattr(p, 'age', age)

        display_name = getattr(p, 'member_name', None) or getattr(p, 'full_name', None) or getattr(p, 'member_code', None) or str(p)
        setattr(p, 'display_name', display_name)

        mobile = getattr(p, 'mobile_number', None) or getattr(p, 'mobile_no', None) or getattr(p, 'mobile', None) or ''
        setattr(p, 'display_mobile', mobile)

        loc_parts = []
        try:
            v = getattr(p, 'village', None)
            if v:
                loc_parts.append(str(v))
            b = getattr(p, 'block', None)
            if b:
                try:
                    loc_parts.append(getattr(b, 'block_name_en', str(b)))
                except Exception:
                    loc_parts.append(str(b))
        except Exception:
            pass
        setattr(p, 'display_location', ", ".join([x for x in loc_parts if x]))

    # Determine designation token mapping for master trainers
    trainer_role_token = 'DRP'
    try:
        lvl = (tr.level or '').upper()
        if lvl == 'BLOCK':
            trainer_role_token = 'BRP'
        elif lvl == 'DISTRICT':
            trainer_role_token = 'DRP'
        elif lvl == 'STATE':
            trainer_role_token = 'SRP'
    except Exception:
        trainer_role_token = 'DRP'

    # Fetch master trainers (prefer MasterTrainer model)
    master_trainers = []
    try:
        master_trainers = MasterTrainer.objects.all()
    except Exception:
        try:
            master_trainers = list(User.objects.filter(designation__iexact=trainer_role_token).order_by('success_rate'))
        except Exception:
            master_trainers = []

    # Build trainer_cert_map
    trainer_cert_map = {}
    try:
        trainer_ids = [getattr(mt, 'id') for mt in master_trainers if getattr(mt, 'id', None)]
        if trainer_ids:
            certs = MasterTrainerCertificate.objects.filter(trainer_id__in=trainer_ids).order_by('trainer_id', '-issued_on', '-created_at')
            for c in certs:
                if c.trainer_id not in trainer_cert_map:
                    trainer_cert_map[c.trainer_id] = c.certificate_number
    except Exception:
        trainer_cert_map = {}   
       
    if (getattr(tr, 'status', '') or '').upper() == 'COMPLETED':
        # render a closure screen listing batches (clickable rows)
        fragment_html = render_to_string('dmmu/request_closure.html', {
            'training_request': tr,
            'batches': batch_details,
        }, request=request)
    else:
        fragment_html = render_to_string('dmmu/request_detail.html', {
            'training_request': tr,
            'batches': batch_details,
            'participants': participants,
            'master_trainers': master_trainers,
            'trainer_cert_map': trainer_cert_map,
            'today': today,          
        }, request=request)

    return render(request, 'dashboard.html', {'user': request.user, 'default_content': fragment_html})

@login_required
@require_http_methods(["GET"])
def dmmu_batch_detail_ajax(request, batch_id):
    """
    AJAX view: return an HTML fragment (modal body) containing
    batch details, participants, centre summary, dates list and attendance outlines.

    Defensive + trainer fallback to BatchEkycVerification if TrainerBatchParticipation missing.
    """
    if getattr(request.user, 'role', '').lower() != 'dmmu':
        return HttpResponseForbidden("Not authorized")

    try:
        b = Batch.objects.select_related('request__training_plan', 'centre')\
            .prefetch_related(
                'batch_beneficiaries__beneficiary',
                'trainerparticipations__trainer',
                'attendances__participant_records'
            ).get(id=batch_id)
    except Batch.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Batch not found'}, status=404)
    except Exception as e:
        logger.exception("dmmu_batch_detail_ajax: DB error fetching batch %s: %s", batch_id, e)
        return JsonResponse({'ok': False, 'error': 'Server error fetching batch'}, status=500)

    try:
        # beneficiaries
        try:
            beneficiaries = [bb.beneficiary for bb in b.batch_beneficiaries.select_related('beneficiary').all()]
        except Exception:
            beneficiaries = []

        # trainers: prefer TrainerBatchParticipation -> trainer FK
        trainers = []
        try:
            trainers = [tp.trainer for tp in b.trainerparticipations.select_related('trainer').all()]
        except Exception:
            trainers = []

        # fallback: look for trainers recorded as eKYC participant_role='Trainer'
        if not trainers:
            try:
                ek_trainer_ids = list(BatchEkycVerification.objects.filter(batch=b, participant_role__iexact='trainer')
                                       .values_list('participant_id', flat=True))
                # filter unique and fetch MasterTrainer by id; fallback to User
                ek_trainer_ids = list(dict.fromkeys([int(x) for x in ek_trainer_ids if x is not None]))
                if ek_trainer_ids:
                    # try MasterTrainer model
                    try:
                        trainers = list(MasterTrainer.objects.filter(id__in=ek_trainer_ids))
                    except Exception:
                        trainers = []
                    # If still empty, try to look up User objects (some setups use user IDs)
                    if not trainers:
                        try:
                            users = list(User.objects.filter(id__in=ek_trainer_ids))
                            # convert User -> minimal objects with desirable attrs if necessary
                            trainers = []
                            for u in users:
                                # create a lightweight wrapper-like object if MasterTrainer not present
                                # but template expects 'full_name' and 'mobile_no' etc.
                                u.full_name = getattr(u, 'get_full_name', lambda: getattr(u, 'username', str(u)))()
                                u.mobile_no = getattr(u, 'mobile_number', None) or getattr(u, 'mobile', None) or getattr(u, 'phone', None)
                                trainers.append(u)
                        except Exception:
                            trainers = trainers or []
            except Exception:
                trainers = trainers or []

        # attendance dates
        attendance_dates = []
        try:
            attendance_dates = list(b.attendances.order_by('date').values_list('date', flat=True))
        except Exception:
            attendance_dates = []

        # centre_info
        centre_info = {}
        try:
            c = b.centre
            if c:
                centre_info = {
                    'venue_name': getattr(c, 'venue_name', None),
                    'venue_address': getattr(c, 'venue_address', None),
                    'serial_number': getattr(c, 'serial_number', None),
                    'coord_name': getattr(c, 'centre_coord_name', None),
                    'coord_mobile': getattr(c, 'centre_coord_mob_number', None),
                }
        except Exception:
            centre_info = {}

        html = render_to_string('dmmu/partials/batch_detail_modal.html', {
            'batch': b,
            'beneficiaries': beneficiaries,
            'trainers': trainers,
            'attendance_dates': attendance_dates,
            'centre_info': centre_info,
            'request_obj': getattr(b, 'request', None),
        }, request=request)

        return JsonResponse({'ok': True, 'html': html})
    except Exception as e:
        logger.exception("dmmu_batch_detail_ajax: render error for batch %s: %s", batch_id, e)
        return JsonResponse({'ok': False, 'error': 'Server error rendering batch details'}, status=500)

    
@login_required
@require_http_methods(["GET"])
def dmmu_batch_attendance_date(request, batch_id, date_str):
    """
    date_str expected 'YYYY-MM-DD' but accept several common variants.
    Returns JSON { ok: True, html: "..." } or { ok: False, error: "..." }.
    """
    if getattr(request.user, 'role', '').lower() != 'dmmu':
        return HttpResponseForbidden("Not authorized")

    # defensive: decode URL-encoded parts and strip whitespace
    try:
        raw = unquote(str(date_str or '')).strip()
    except Exception:
        raw = (date_str or '').strip()

    the_date = None

    # Try common formats in order
    parse_attempts = [
        "%Y-%m-%d",            # 2025-10-04
        "%Y-%m-%dT%H:%M:%S",   # 2025-10-04T00:00:00
        "%d-%m-%Y",            # 04-10-2025
        "%d/%m/%Y",            # 04/10/2025
        "%b %d, %Y",           # Oct 04, 2025
        "%b. %d, %Y",          # Oct. 4, 2025
        "%B %d, %Y",           # October 4, 2025
    ]

    for fmt in parse_attempts:
        try:
            the_date = datetime.datetime.strptime(raw, fmt).date()
            break
        except Exception:
            continue

    if the_date is None:
        # Try isoformat parse (handles many ISO variants), or fallback to dateutil if available
        try:
            # try to handle trailing milliseconds or timezone (basic)
            if 'T' in raw and raw.endswith('Z'):
                # normalize Z timezone
                raw_norm = raw.replace('Z', '+00:00')
            else:
                raw_norm = raw

            try:
                # Python 3.7+: fromisoformat can parse many ISO strings (without Z)
                the_date = datetime.date.fromisoformat(raw_norm.split('T')[0])
            except Exception:
                # fallback to parsing whole timestamp if present
                try:
                    dt = datetime.datetime.fromisoformat(raw_norm)
                    the_date = dt.date()
                except Exception:
                    the_date = None
        except Exception:
            the_date = None

    if the_date is None:
        # final fallback: try python-dateutil if installed
        try:
            from dateutil import parser as _du_parser
            try:
                dt = _du_parser.parse(raw)
                the_date = dt.date()
            except Exception:
                the_date = None
        except Exception:
            the_date = None

    if the_date is None:
        logger.info("dmmu_batch_attendance_date: invalid date string received: %r (batch=%s) from %s", raw, batch_id, request.path)
        return JsonResponse({'ok': False, 'error': f'Invalid date format: {raw!s}'}, status=400)

    try:
        att = BatchAttendance.objects.select_related('batch').prefetch_related('participant_records').get(batch_id=batch_id, date=the_date)
    except BatchAttendance.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'No attendance found'}, status=404)
    except Exception as e:
        logger.exception("dmmu_batch_attendance_date: DB error fetching attendance for batch %s date %s: %s", batch_id, the_date, e)
        return JsonResponse({'ok': False, 'error': 'Server error fetching attendance'}, status=500)

    try:
        html = render_to_string('dmmu/partials/attendance_list.html', {'attendance': att}, request=request)
        return JsonResponse({'ok': True, 'html': html})
    except Exception as e:
        logger.exception("dmmu_batch_attendance_date: render error for batch %s date %s: %s", batch_id, the_date, e)
        return JsonResponse({'ok': False, 'error': 'Server error rendering attendance'}, status=500)