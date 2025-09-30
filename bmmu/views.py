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
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.db import transaction
from django.conf import settings
from django import forms

from .models import *

from .resources import UserResource, BeneficiaryResource, TrainingPlanResource, MasterTrainerResource
from .utils import export_blueprint
from .forms import TrainingPlanForm, BatchNominateForm, TrainingPartnerProfileForm, PublicMasterTrainerProfileForm, TrainingPartnerSubmissionForm, SignupForm, MasterTrainerCertificateForm

from django.db.models import Q, F

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.db.models import Prefetch
from datetime import date
from django.db.models import OuterRef, Subquery

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
            batch_status_choices = [c[0] for c in Batch._meta.get_field('status').choices]
            statuses_of_interest = [s for s in ('ONGOING', 'PENDING') if s in batch_status_choices]
            if statuses_of_interest:
                batch_qs = Batch.objects.filter(status__in=statuses_of_interest).select_related('training_plan', 'partner')[:200]
            else:
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
@csrf_exempt
def tms_create_batch(request):
    """
    Endpoint to create a Batch from the client-side TMS modal.
    Accepts application/json POST (body). Minimal validation and safe creation.
    Returns JSON {ok: True/False, batch_id:, message:}
    """
    if request.method != 'POST':
        return HttpResponseBadRequest('Invalid method')

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')

    # required fields (moduleId is required so we can map to TrainingPlan)
    required = ['theme', 'moduleId', 'trainers', 'beneficiaries', 'partner']
    # allow partner empty string when not chosen
    if not all(k in payload for k in required):
        return HttpResponseBadRequest('Missing fields')

    module_id = payload.get('moduleId')
    try:
        # moduleId maps to TrainingPlan.id (we used that mapping earlier)
        tp = TrainingPlan.objects.get(id=module_id)
    except Exception:
        return JsonResponse({'ok': False, 'message': 'Invalid module id'}, status=400)

    # Parse optional dates if provided (ISO string). Keep robust: don't error on parse issues.
    start_date = None
    end_date = None
    try:
        from datetime import datetime
        s = payload.get('start') or None
        e = payload.get('end') or None
        if s:
            try:
                start_date = datetime.fromisoformat(s).date()
            except Exception:
                start_date = None
        if e:
            try:
                end_date = datetime.fromisoformat(e).date()
            except Exception:
                end_date = None
    except Exception:
        start_date = None
        end_date = None

    # partner may be empty string or id
    partner_val = payload.get('partner') or None
    partner_obj = None
    if partner_val:
        try:
            partner_obj = TrainingPartner.objects.filter(id=partner_val).first()
        except Exception:
            partner_obj = None

    # safe create within transaction
    try:
        with transaction.atomic():
            batch = Batch.objects.create(
                training_plan=tp,
                start_date=start_date,
                end_date=end_date,
                partner=partner_obj,
                created_by=request.user if hasattr(request.user, 'id') else None,
                status='PENDING' if 'PENDING' in [c[0] for c in Batch._meta.get_field('status').choices] else getattr(Batch, 'status', 'DRAFT')
            )
            # attach trainers if provided (list of ids)
            trainers = payload.get('trainers') or []
            if trainers:
                try:
                    trainers_qs = MasterTrainer.objects.filter(id__in=trainers)
                    batch.trainers.set(trainers_qs)
                except Exception:
                    pass

            # attach beneficiaries ids
            beneficiaries = payload.get('beneficiaries') or []
            if beneficiaries:
                try:
                    ben_qs = Beneficiary.objects.filter(id__in=beneficiaries)
                    batch.beneficiaries.set(ben_qs)
                except Exception:
                    pass

            # assign code if needed
            if not getattr(batch, 'code', None):
                import uuid
                batch.code = 'B-' + str(uuid.uuid4())[:8]
                batch.save()

    except Exception as e:
        logger.exception("tms_create_batch: failed to create batch: %s", e)
        return JsonResponse({'ok': False, 'message': 'Server error creating batch'}, status=500)

    return JsonResponse({'ok': True, 'batch_id': batch.code or batch.id, 'message': 'Batch created successfully'})

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
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)
    if not partner:
        assignments = Batch.objects.none()
        approved = Batch.objects.none()
        running = Batch.objects.none()
        ongoing = Batch.objects.none()
    else:
        # Determine canonical status tokens present in model
        status_choices = [c[0] for c in Batch._meta.get_field('status').choices]

        # Show "assignments" (requests that still require partner action).
        # Exclude batches that have already been 'proposed' by partner or are already 'ongoing'/'completed'/'rejected'.
        exclude_statuses = []
        for s in ('PROPOSED', 'ONGOING', 'COMPLETED', 'REJECTED'):
            if s in status_choices:
                exclude_statuses.append(s)
        # also accept lowercase 'proposed' token if defined (robust)
        if 'proposed' in [x.lower() for x in status_choices] and 'PROPOSED' not in exclude_statuses:
            # find the canonical token whose lowercase is 'proposed'
            for s in status_choices:
                if s.lower() == 'proposed':
                    exclude_statuses.append(s)
                    break

        if exclude_statuses:
            assignments_qs = Batch.objects.filter(partner=partner).exclude(status__in=exclude_statuses).order_by('-created_at')
        else:
            assignments_qs = Batch.objects.filter(partner=partner).order_by('-created_at')

        # approved (for reference)
        approved_token = None
        for t in ('APPROVED', 'approved', 'Approved'):
            if t in status_choices:
                approved_token = t; break
        if approved_token:
            approved_qs = Batch.objects.filter(partner=partner, status=approved_token).order_by('-start_date')[:50]
        else:
            approved_qs = Batch.objects.none()

        # Ongoing batches (for Quick Actions modal)
        ongoing_tokens = [t for t in status_choices if t.upper() == 'ONGOING' or t.lower() == 'ongoing']
        if ongoing_tokens:
            ongoing_qs = Batch.objects.filter(partner=partner, status__in=ongoing_tokens).select_related('training_plan', 'partner').order_by('start_date')
        else:
            ongoing_qs = Batch.objects.none()

        # running/perhaps used elsewhere (keep backward compatible)
        running_tokens = [t for t in status_choices if t.upper() == 'ONGOING' or t.lower() == 'running']
        if running_tokens:
            running_qs = Batch.objects.filter(partner=partner, status__in=running_tokens).order_by('-start_date')[:50]
        else:
            running_qs = Batch.objects.none()

        assignments = assignments_qs
        approved = approved_qs
        running = running_qs
        ongoing = ongoing_qs

    context = {
        'partner': partner,
        'assignments': assignments,
        'approved': approved,
        'running': running,
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
    Centre Registration: list existing TrainingPartnerSubmission rows for the partner
    and allow uploading new submission (category, file, notes).
    """
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)
    if not partner:
        # create minimal partner skeleton so they can fill profile later
        partner = TrainingPartner.objects.create(user=request.user, name=request.user.get_full_name() or request.user.username)
        request.user.refresh_from_db()

    # list existing submissions for this partner (latest first)
    submissions_qs = TrainingPartnerSubmission.objects.filter(partner=partner).order_by('-uploaded_on')[:200]

    # handle POST upload
    if request.method == 'POST':
        form = TrainingPartnerSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            sub = form.save(commit=False)
            sub.partner = partner
            sub.uploaded_by = request.user
            sub.save()
            messages.success(request, "Submission uploaded.")
            return redirect('training_partner_centre_registration')
        else:
            messages.error(request, "Fix errors below.")
    else:
        form = TrainingPartnerSubmissionForm()

    context = {
        'partner': partner,
        'submissions': submissions_qs,
        'form': form,
    }
    return render(request, 'training_partner/centre_registration.html', context)

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
def partner_view_batch(request, batch_id):
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)
    batch = get_object_or_404(Batch, id=batch_id)

    if partner is None or batch.partner_id != partner.id:
        return HttpResponseForbidden("Not your batch")

    submissions = []
    if partner:
        try:
            submissions = TrainingPartnerSubmission.objects.filter(partner=partner).order_by('-uploaded_on')[:8]
        except Exception:
            # fallback if TrainingPartnerSubmission import/path is different OR related_name used
            try:
                # try using the reverse manager if it exists
                submissions = partner.trainingsubmission_set.all().order_by('-uploaded_on')[:8]
            except Exception:
                submissions = []
    
    # Build a mapping trainer_id -> latest certificate_number
    trainer_cert_map = {}
    # best-effort: pick latest by issued_on then created_at
    cert_qs = MasterTrainerCertificate.objects.filter(trainer=OuterRef('pk')).order_by('-issued_on', '-created_at')
    # We use Subquery to get certificate_number for each trainer if you prefer direct ORM; otherwise fallback to explicit loop:
    trainer_ids = [t.id for t in batch.trainers.all()]
    if trainer_ids:
        certs = MasterTrainerCertificate.objects.filter(trainer_id__in=trainer_ids).order_by('trainer_id', '-issued_on', '-created_at')
        # iterate and keep first seen (which will be latest due to ordering per trainer_id group not guaranteed — so we do a dict and compare dates)
        for c in certs:
            # only keep certificate if not already set OR this one is newer
            prev = trainer_cert_map.get(c.trainer_id)
            if not prev:
                trainer_cert_map[c.trainer_id] = {'certificate_number': c.certificate_number, 'issued_on': c.issued_on, 'created_at': c.created_at}
            else:
                # compare issued_on (None-safe)
                prev_issued = prev.get('issued_on')
                cur_issued = c.issued_on
                if (cur_issued and (not prev_issued or cur_issued > prev_issued)) or (not prev_issued and not cur_issued and c.created_at > prev.get('created_at')):
                    trainer_cert_map[c.trainer_id] = {'certificate_number': c.certificate_number, 'issued_on': c.issued_on, 'created_at': c.created_at}

    # Simplify trainer_cert_map to map id -> certificate_number string (or None)
    trainer_cert_map = {k: (v['certificate_number'] if v and v.get('certificate_number') else None) for k, v in trainer_cert_map.items()}

    # Compute age for beneficiaries and attach .age attribute (int or None)
    beneficiaries = list(batch.beneficiaries.all())  # evaluate once so attributes persist
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

    context = {
        'partner': partner,
        'batch': batch,
        'submissions': submissions,
        'trainer_cert_map': trainer_cert_map,
        'beneficiaries': beneficiaries,
        'today': today,
    }
    return render(request, 'training_partner/view_batch.html', context)

@login_required
def training_partner_attendance(request):
    if getattr(request.user, "role", "").lower() != "training_partner":
        return HttpResponseForbidden("Not authorized")

    partner = _get_partner_for_user(request.user)
    if not partner:
        return HttpResponseForbidden("No partner profile")

    # try to discover canonical 'ongoing' token(s) from Batch.status choices
    status_field = None
    try:
        status_field = Batch._meta.get_field('status')
        choices = [c[0] for c in getattr(status_field, 'choices', [])]
    except Exception:
        choices = []

    ongoing_tokens = [t for t in choices if t and (t.lower() == 'ongoing' or t.upper() == 'ONGOING')]
    if not ongoing_tokens:
        # fallback: try 'running' or 'RUNNING'
        ongoing_tokens = [t for t in choices if t and (t.lower() == 'running' or t.upper() == 'RUNNING')]

    today = timezone.localdate()

    if ongoing_tokens:
        # add prefetch_related so trainers/beneficiaries are available without extra queries
        batches_qs = Batch.objects.filter(partner=partner, status__in=ongoing_tokens) \
            .select_related('training_plan') \
            .prefetch_related('trainers', 'beneficiaries') \
            .order_by('start_date')
    else:
        # fallback to any batch with start_date <= today <= end_date where partner matches
        batches_qs = Batch.objects.filter(partner=partner, start_date__lte=today, end_date__gte=today) \
            .select_related('training_plan') \
            .prefetch_related('trainers', 'beneficiaries') \
            .order_by('start_date')

    # Evaluate queryset and attach trainer/beneficiary lists (so attributes we set persist)
    batches = list(batches_qs)

    # compute age helper
    def compute_age(dob):
        if not dob:
            return None
        try:
            today_date = date.today()
            return today_date.year - dob.year - ((today_date.month, today_date.day) < (dob.month, dob.day))
        except Exception:
            return None

    for b in batches:
        # evaluated lists (so same instances used in templates/modal)
        trainers_list = list(b.trainers.all())
        beneficiaries_list = list(b.beneficiaries.all())

        # attach age on beneficiary instances
        for ben in beneficiaries_list:
            dob = getattr(ben, 'date_of_birth', None)
            ben.age = compute_age(dob)

        # attach to batch for template usage (avoid polluting public API, use underscore-prefixed attrs)
        setattr(b, 'trainers_list', trainers_list)
        setattr(b, 'beneficiaries_list', beneficiaries_list)

    context = {
        'partner': partner,
        'batches': batches,
        'today': today,
    }
    return render(request, 'training_partner/attendance_management.html', context)

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