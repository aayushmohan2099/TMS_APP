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
import logging

logger = logging.getLogger(__name__)

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

# --- Helpers to compute ongoing participants (authoritative) ---
def _get_ongoing_beneficiary_ids():
    try:
        return set(BatchBeneficiary.objects.filter(batch__status='ONGOING').values_list('beneficiary_id', flat=True))
    except Exception:
        try:
            return set(Batch.objects.filter(status='ONGOING').values_list('batch_beneficiaries__beneficiary_id', flat=True))
        except Exception:
            return set()

def _get_ongoing_trainer_ids():
    try:
        return set(TrainerBatchParticipation.objects.filter(batch__status='ONGOING').values_list('trainer_id', flat=True))
    except Exception:
        try:
            return set(Batch.objects.filter(status='ONGOING').values_list('trainerparticipations__trainer_id', flat=True))
        except Exception:
            return set()

@login_required
@csrf_exempt
def create_training_request(request):
    """
    AJAX endpoint to create a TrainingRequest (used by the new TMS UI).
    - Performs validation: excludes participants already in ONGOING batches.
    - Enforces role-based constraints:
        BMMU: beneficiaries must be in user's block; BRPs must be empanelled in block's district.
        DMMU: beneficiaries/trainers must be in user's district.
        SMMU: global (no district/block enforced).
    - If validation passes, proceeds to partner selection according to Target assigned and creates TrainingRequest.
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
    # optional designation for trainers (BRP/DRP/SRP)
    designation = (payload.get('designation') or payload.get('trainer_designation') or '').upper()

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
        try:
            district_obj = District.objects.get(pk=int(district_id))
        except Exception:
            district_obj = None

    # Determine financial year to match targets (prefer provided in payload, else current)
    fy = payload.get('financial_year') or current_financial_year()

    # --- Role assignment detection (user block/district) ---
    user_block_id = None
    user_district_id = None
    try:
        if role == 'bmmu':
            bmmu_assign = getattr(request.user, 'bmmu_block_assignment', None)
            # if assignment object stores block as .block or .block_id
            if bmmu_assign:
                if getattr(bmmu_assign, 'block', None):
                    user_block_id = getattr(bmmu_assign.block, 'block_id', None) or getattr(bmmu_assign.block, 'id', None)
                    user_district_id = getattr(bmmu_assign.block, 'district_id', None) or getattr(bmmu_assign.block, 'district', None)
                else:
                    # maybe stored directly as value
                    user_block_id = getattr(bmmu_assign, 'block_id', None) or getattr(bmmu_assign, 'block', None)
        elif role == 'dmmu':
            dmmu_assign = getattr(request.user, 'dmmu_district_assignment', None)
            if dmmu_assign:
                if getattr(dmmu_assign, 'district', None):
                    user_district_id = getattr(dmmu_assign.district, 'district_id', None) or getattr(dmmu_assign.district, 'id', None)
                else:
                    user_district_id = getattr(dmmu_assign, 'district_id', None) or getattr(dmmu_assign, 'district', None)
    except Exception as e:
        logger.exception("Error reading user assignments: %s", e)

    # Authoritative ongoing participants
    ongoing_ben = _get_ongoing_beneficiary_ids()
    ongoing_tr = _get_ongoing_trainer_ids()

    # Validate participant existence & role constraints
    invalid = {'not_found': [], 'ongoing': [], 'role_mismatch': []}
    valid_ids = []

    # Normalize participant ids to ints and keep original order
    try:
        participant_ids = [int(x) for x in participant_ids]
    except Exception:
        return JsonResponse({'ok': False, 'message': 'Invalid participant ids'}, status=400)

    if training_type == 'BENEFICIARY':
        # bulk fetch
        bens = Beneficiary.objects.filter(id__in=participant_ids).select_related('block', 'district')
        found_map = {b.id: b for b in bens}
        for pid in participant_ids:
            b = found_map.get(pid)
            if not b:
                invalid['not_found'].append(pid)
                continue
            if pid in ongoing_ben:
                invalid['ongoing'].append(pid)
                continue
            # role-based constraints
            if role == 'bmmu' and user_block_id:
                b_block_id = None
                try:
                    b_block_id = getattr(getattr(b, 'block', None), 'block_id', None) or getattr(getattr(b, 'block', None), 'id', None) or getattr(b, 'block', None)
                except Exception:
                    b_block_id = getattr(b, 'block', None)
                if str(b_block_id) != str(user_block_id):
                    invalid['role_mismatch'].append({'id': pid, 'reason': 'beneficiary not in your block'})
                    continue
            elif role == 'dmmu' and user_district_id:
                b_district_id = None
                try:
                    b_district_id = getattr(getattr(b, 'district', None), 'district_id', None) or getattr(getattr(b, 'district', None), 'id', None) or getattr(b, 'district', None)
                except Exception:
                    b_district_id = getattr(b, 'district', None)
                if str(b_district_id) != str(user_district_id):
                    invalid['role_mismatch'].append({'id': pid, 'reason': 'beneficiary not in your district'})
                    continue
            # OK
            valid_ids.append(pid)

    else:  # TRAINER
        trainers = MasterTrainer.objects.filter(id__in=participant_ids)
        found_map = {t.id: t for t in trainers}
        for pid in participant_ids:
            t = found_map.get(pid)
            if not t:
                invalid['not_found'].append(pid)
                continue
            if pid in ongoing_tr:
                invalid['ongoing'].append(pid)
                continue
            # designation check if provided
            if designation:
                t_desig = (getattr(t, 'designation', '') or '').upper()
                if t_desig != designation:
                    invalid['role_mismatch'].append({'id': pid, 'reason': f'designation mismatch (expected {designation})'})
                    continue
            # role-based constraints for trainers
            if role == 'bmmu' and user_block_id:
                # find block -> district
                try:
                    block_obj = Block.objects.filter(block_id=user_block_id).first()
                    block_district_id = getattr(block_obj, 'district_id', None) or getattr(block_obj, 'district', None) if block_obj else None
                except Exception:
                    block_district_id = None
                trainer_district_val = getattr(t, 'empanel_district', None) or getattr(t, 'district', None)
                if block_district_id and str(trainer_district_val) != str(block_district_id):
                    invalid['role_mismatch'].append({'id': pid, 'reason': 'trainer not empanelled in block district'})
                    continue
            elif role == 'dmmu' and user_district_id:
                trainer_district_val = getattr(t, 'empanel_district', None) or getattr(t, 'district', None)
                if str(trainer_district_val) != str(user_district_id):
                    invalid['role_mismatch'].append({'id': pid, 'reason': 'trainer not in your district'})
                    continue
            # smmu: no restriction
            valid_ids.append(pid)

    # If any invalids, return details (400)
    if invalid['not_found'] or invalid['ongoing'] or invalid['role_mismatch']:
        return JsonResponse({
            'ok': False,
            'message': 'Validation failed for one or more participant ids',
            'invalid': invalid,
            'valid_ids': valid_ids
        }, status=400)

    # At this point validation passed. Proceed with partner selection (same algorithm as before)
    # Helper: compute completed batches for partner for this training plan (and FY)
    def completed_count_for_partner_and_plan(partner, training_plan, financial_year):
        qs = TrainingPartnerBatch.objects.filter(
            partner=partner,
            batch__request__training_plan=training_plan,
            status='COMPLETED'
        )
        return qs.count()

    def completed_count_for_partner_scope(partner, training_plan=None, theme=None, district=None):
        qs = TrainingPartnerBatch.objects.filter(partner=partner, status='COMPLETED')
        if training_plan:
            qs = qs.filter(batch__request__training_plan=training_plan)
        elif theme:
            qs = qs.filter(batch__request__training_plan__theme=theme)
        elif district:
            # best-effort: attempt to filter batches whose request has beneficiaries in district (app-specific; keep simple)
            try:
                qs = qs.filter(batch__request__training_plan__isnull=False)
            except Exception:
                pass
        return qs.count()

    partner_obj = None

    # --- Step A: look for MODULE targets matching training_plan + district for FY ---
    module_targets = TrainingPartnerTargets.objects.filter(
        target_type='MODULE',
        training_plan=tp,
        financial_year=fy
    ).select_related('partner')

    if district_obj:
        # prefer targets that explicitly set district; include null district as fallback
        # (Django OR requires use of Q)
        from django.db.models import Q
        module_targets = module_targets.filter(Q(district=district_obj) | Q(district__isnull=True))

    module_targets = module_targets.distinct()
    selected_candidates = list(module_targets)

    # --- THEME fallback ---
    if not selected_candidates:
        theme_val = tp.theme
        if theme_val:
            theme_targets = TrainingPartnerTargets.objects.filter(
                target_type='THEME',
                theme=theme_val,
                financial_year=fy
            ).select_related('partner').distinct()
            selected_candidates = list(theme_targets)

    # --- DISTRICT fallback ---
    if not selected_candidates and district_obj:
        district_targets = TrainingPartnerTargets.objects.filter(
            target_type='DISTRICT',
            district=district_obj,
            financial_year=fy
        ).select_related('partner').distinct()
        selected_candidates = list(district_targets)

    chosen_partner = None
    chosen_target_obj = None

    if selected_candidates:
        candidates = []
        for t in selected_candidates:
            p = t.partner
            if not p:
                continue
            target_n = t.target_count or 0
            completed = completed_count_for_partner_and_plan(p, tp, fy)
            candidates.append({
                'target_obj': t,
                'partner': p,
                'target_count': target_n,
                'completed': completed,
                'remaining': max(0, (target_n - completed))
            })

        if candidates:
            with_capacity = [c for c in candidates if c['remaining'] > 0]
            if with_capacity:
                with_capacity.sort(key=lambda x: (-x['remaining'], x['completed']))
                top_remaining = [c for c in with_capacity if c['remaining'] == with_capacity[0]['remaining']]
                chosen = random.choice(top_remaining) if len(top_remaining) > 1 else with_capacity[0]
                chosen_partner = chosen['partner']
                chosen_target_obj = chosen['target_obj']
            else:
                for c in candidates:
                    c['overcap'] = (c['completed'] - c['target_count'])
                candidates.sort(key=lambda x: (x['overcap'], x['completed']))
                best = candidates[0]
                tied = [c for c in candidates if c['overcap'] == best['overcap'] and c['completed'] == best['completed']]
                chosen = random.choice(tied) if len(tied) > 1 else best
                chosen_partner = chosen['partner']
                chosen_target_obj = chosen['target_obj']

    # fallback ignoring FY if needed
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

    # Now create TrainingRequest and attach only validated participants
    try:
        with transaction.atomic():
            tr = TrainingRequest.objects.create(
                training_plan=tp,
                training_type=training_type,
                partner=chosen_partner,
                level=level,
                created_by=request.user
            )

            if training_type == 'BENEFICIARY' and valid_ids:
                bens = Beneficiary.objects.filter(id__in=valid_ids)
                for b in bens:
                    # keep same registration model as before
                    BeneficiaryBatchRegistration.objects.create(beneficiary=b, training=tr)
            elif training_type == 'TRAINER' and valid_ids:
                trainers_objs = MasterTrainer.objects.filter(id__in=valid_ids)
                for t in trainers_objs:
                    TrainerBatchRegistration.objects.create(trainer=t, training=tr)

    except Exception as e:
        logger.exception("Error creating TrainingRequest: %s", e)
        return JsonResponse({'ok': False, 'message': f'Error creating request: {str(e)}'}, status=500)

    return JsonResponse({
        'ok': True,
        'request_id': tr.id,
        'message': 'Training request created',
        'partner_assigned': getattr(chosen_partner, 'id', None),
        'target_used_id': getattr(chosen_target_obj, 'id', None)
    })
