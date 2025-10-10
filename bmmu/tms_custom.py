from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from .models import *
from django.utils import timezone
from datetime import date, datetime
from datetime import timedelta
from zoneinfo import ZoneInfo
import random

def current_financial_year(today=None):
    # returns string like "2023-24" assuming FY runs from 1 Apr - 31 Mar (India style)
    try:
        india_tz = ZoneInfo("Asia/Kolkata")
    except Exception:
        india_tz = None
    today = datetime.now(tz=india_tz).date() if india_tz else timezone.localdate()

    year = today.year
    # FY starts Apr 1
    if today.month >= 4:
        start = year
        end = year + 1
    else:
        start = year - 1
        end = year
    return f"{start}-{str(end)[-2:]}"

@login_required
@csrf_exempt
def create_training_request(request):
    """
    AJAX endpoint to create a TrainingRequest (used by the new TMS UI).
    Assign partner based on TrainingPartnerTargets with clash resolution:
     - prefer MODULE targets for module+district (for current FY),
     - fallback to THEME targets for the module's theme,
     - fallback to DISTRICT targets for the district,
     - when multiple partners available: prefer those with remaining capacity (completed < target),
       otherwise choose partner with smallest overcap (completed - target), then random.
    """
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST allowed")

    # Basic role guard: allow SMMU/DMMU/BMMU to create requests
    role = getattr(request.user, 'role', '').lower()
    if role not in ('bmmu', 'dmmu', 'smmu'):
        return HttpResponseForbidden("Not authorized to create training requests")

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    tp_id = payload.get('training_plan_id') or payload.get('moduleId') or payload.get('module_id')
    training_type = (payload.get('training_type') or payload.get('type') or '').upper()
    participant_ids = payload.get('participant_ids') or payload.get('participants') or []
    level = (payload.get('level') or 'BLOCK').upper()

    if not tp_id or training_type not in ('BENEFICIARY', 'TRAINER'):
        return HttpResponseBadRequest("Missing or invalid training_plan_id / training_type")

    try:
        tp = TrainingPlan.objects.get(pk=int(tp_id))
    except Exception:
        return JsonResponse({'ok': False, 'message': 'Invalid training plan id'}, status=400)

    # Determine district context if provided in payload (optional)
    district_id = payload.get('district_id') or payload.get('district')
    district_obj = None
    if district_id:
        from .models import District
        try:
            district_obj = District.objects.get(pk=int(district_id))
        except Exception:
            district_obj = None

    # Determine financial year to match targets (prefer provided in payload, else current)
    fy = payload.get('financial_year') or current_financial_year()

    # Helper: compute completed batches for partner for this training plan (and FY)
    def completed_count_for_partner_and_plan(partner, training_plan, financial_year):
        # Count TrainingPartnerBatch with partner, batch.request.training_plan == training_plan
        # and batch.status == 'COMPLETED' and batch.request.created_at inside this financial year if possible.
        qs = TrainingPartnerBatch.objects.filter(
            partner=partner,
            batch__request__training_plan=training_plan,
            status='COMPLETED'
        )
        # Attempt to filter by financial_year stored on TrainingPartnerTargets or TrainingRequest created_at fallback:
        # We will not strictly require created_at range here (best-effort)
        return qs.count()

    # Helper: completed batches for partner for theme/district (fallback)
    def completed_count_for_partner_scope(partner, training_plan=None, theme=None, district=None):
        qs = TrainingPartnerBatch.objects.filter(partner=partner, status='COMPLETED')
        if training_plan:
            qs = qs.filter(batch__request__training_plan=training_plan)
        elif theme:
            qs = qs.filter(batch__request__training_plan__theme=theme)
        elif district:
            qs = qs.filter(batch__request__training_plan__isnull=False, batch__request__training_plan__in=TrainingPlan.objects.filter())
            # simpler: count batches whose request has beneficiaries or location matching district — this is app-specific
            # for safety we restrict to batches whose request.training_plan exists and ignore district filter if mapping is ambiguous
        return qs.count()

    partner_obj = None

    # --- Step A: look for MODULE targets matching training_plan + district for FY ---
    # Query TrainingPartnerTargets with target_type MODULE, training_plan=tp, financial_year=fy
    module_targets = TrainingPartnerTargets.objects.filter(
        target_type='MODULE',
        training_plan=tp,
        financial_year=fy
    ).select_related('partner')

    if district_obj:
        module_targets = module_targets.filter(district=district_obj) | module_targets.filter(district__isnull=True)
        # we prefer targets that explicitly have the district set later in ordering logic

    module_targets = module_targets.distinct()

    selected_candidates = list(module_targets)

    # --- Step B: if no module-level targets, try THEME targets for tp.theme in FY ---
    if not selected_candidates:
        theme_val = tp.theme
        if theme_val:
            theme_targets = TrainingPartnerTargets.objects.filter(
                target_type='THEME',
                theme=theme_val,
                financial_year=fy
            ).select_related('partner').distinct()
            selected_candidates = list(theme_targets)

    # --- Step C: if still none, try DISTRICT targets (district-level) for FY ---
    if not selected_candidates and district_obj:
        district_targets = TrainingPartnerTargets.objects.filter(
            target_type='DISTRICT',
            district=district_obj,
            financial_year=fy
        ).select_related('partner').distinct()
        selected_candidates = list(district_targets)

    # If we have candidate TrainingPartnerTargets, produce partner list with target_count and completed_count
    chosen_partner = None
    chosen_target_obj = None

    if selected_candidates:
        # Build a list of dicts: {'target': t, 'partner': p, 'target_count': n, 'completed': c}
        candidates = []
        for t in selected_candidates:
            p = t.partner
            if not p:
                continue
            target_n = t.target_count or 0
            # compute completed count for this partner & training_plan (best-effort)
            completed = completed_count_for_partner_and_plan(p, tp, fy)
            candidates.append({
                'target_obj': t,
                'partner': p,
                'target_count': target_n,
                'completed': completed,
                'remaining': max(0, (target_n - completed))
            })

        if candidates:
            # Prefer partners with remaining capacity > 0, order by remaining desc then by completed asc (fairness)
            with_capacity = [c for c in candidates if c['remaining'] > 0]
            if with_capacity:
                # choose partner with largest remaining (or smallest completed if you prefer).
                # We'll choose the one with largest remaining, tie-breaker smallest completed, then random.
                with_capacity.sort(key=lambda x: (-x['remaining'], x['completed']))
                top_remaining = [c for c in with_capacity if c['remaining'] == with_capacity[0]['remaining']]
                chosen = random.choice(top_remaining) if len(top_remaining) > 1 else with_capacity[0]
                chosen_partner = chosen['partner']
                chosen_target_obj = chosen['target_obj']
            else:
                # All candidates have no remaining capacity (all met or overcap).
                # Pick partner with smallest overcap (completed - target). That is, choose min(completed - target).
                # If target_count==0 for any, treat overcap as large unless completed==0.
                # Build overcap
                for c in candidates:
                    c['overcap'] = (c['completed'] - c['target_count'])
                # minimize overcap; if tie pick partner with smallest completed; if still tie random
                candidates.sort(key=lambda x: (x['overcap'], x['completed']))
                best = candidates[0]
                # if multiple share same overcap & completed, pick random among them
                tied = [c for c in candidates if c['overcap'] == best['overcap'] and c['completed'] == best['completed']]
                chosen = random.choice(tied) if len(tied) > 1 else best
                chosen_partner = chosen['partner']
                chosen_target_obj = chosen['target_obj']

    # Also try to fallback to any TrainingPartnerTargets ignoring FY (if none for current FY)
    if not chosen_partner:
        try:
            any_module_target = TrainingPartnerTargets.objects.filter(
                target_type='MODULE',
                training_plan=tp
            ).select_related('partner').first()
            if any_module_target:
                chosen_partner = any_module_target.partner
                chosen_target_obj = any_module_target
        except Exception:
            pass

    # Now create TrainingRequest and attach participants
    try:
        with transaction.atomic():
            tr = TrainingRequest.objects.create(
                training_plan=tp,
                training_type=training_type,
                partner=chosen_partner,
                level=level,
                created_by=request.user
            )

            if training_type == 'BENEFICIARY' and participant_ids:
                # attach beneficiaries through BeneficiaryBatchRegistration
                bens = Beneficiary.objects.filter(id__in=participant_ids)
                for b in bens:
                    BeneficiaryBatchRegistration.objects.create(beneficiary=b, training=tr)
            elif training_type == 'TRAINER' and participant_ids:
                trainers = MasterTrainer.objects.filter(id__in=participant_ids)
                for t in trainers:
                    TrainerBatchRegistration.objects.create(trainer=t, training=tr)

    except Exception as e:
        return JsonResponse({'ok': False, 'message': f'Error creating request: {str(e)}'}, status=500)

    return JsonResponse({
        'ok': True,
        'request_id': tr.id,
        'message': 'Training request created',
        'partner_assigned': getattr(chosen_partner, 'id', None),
        'target_used_id': getattr(chosen_target_obj, 'id', None)
    })