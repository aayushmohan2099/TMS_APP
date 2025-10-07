from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from .models import TrainingPlan, TrainingRequest, TrainingPlanPartner, TrainingPlanPartner as TPP, TrainingPartner, Beneficiary, MasterTrainer, BeneficiaryBatchRegistration, TrainerBatchRegistration

@login_required
@csrf_exempt
def create_training_request(request):
    """
    AJAX endpoint to create a TrainingRequest (used by the new TMS UI).
    Expected JSON POST body:
    {
      "training_plan_id": <int>,
      "training_type": "BENEFICIARY" | "TRAINER",
      "participant_ids": [1,2,3],
      "level": "BLOCK" | "DISTRICT" | "STATE"   (optional, default 'BLOCK')
    }
    Behavior:
     - Creates TrainingRequest linked to the TrainingPlan
     - Assigns partner automatically using TrainingPlanPartner if present
     - Attaches participants to the request using BeneficiaryBatchRegistration or TrainerBatchRegistration
     - Returns JSON {ok: True, request_id: <id>, message: ...} or error
    """
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST allowed")

    # Basic role guard: allow SMMU/DMMU/BMMU to create requests (theme experts / local admins)
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

    # find partner assignment: prefer TrainingPlanPartner mapping
    partner_obj = None
    try:
        tpp = TrainingPlanPartner.objects.filter(training_plan=tp).select_related('partner').first()
        if tpp:
            partner_obj = tpp.partner
    except Exception:
        partner_obj = None

    # fallback: try TrainingPlanPartner under different name or TrainingPartnerAssignment
    try:
        if not partner_obj:
            # try a model named TrainingPartnerAssignment if exists
            from .models import TrainingPartnerAssignment
            assign = TrainingPartnerAssignment.objects.filter(theme=tp.theme).select_related('partner').first()
            if assign:
                partner_obj = assign.partner
    except Exception:
        # ignore if model not present
        pass

    # Now create TrainingRequest and attach participants
    try:
        with transaction.atomic():
            tr = TrainingRequest.objects.create(
                training_plan=tp,
                training_type=training_type,
                partner=partner_obj,
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

    return JsonResponse({'ok': True, 'request_id': tr.id, 'message': 'Training request created', 'partner_assigned': getattr(partner_obj, 'id', None)})
