# signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Batch, TrainingPartnerBatch, TrainingPartnerCentre, TrainingPartner

@receiver(post_save, sender=Batch)
def ensure_training_partner_batch(sender, instance: Batch, created, **kwargs):
    """
    Ensure TrainingPartnerBatch record exists/updated when a Batch becomes COMPLETED or REJECTED.
    Conditions:
      - Batch.centre must reference a TrainingPartner via one of common attribute names:
          centre.partner OR centre.training_partner OR centre.owner
        adjust if your model uses a different field name.
      - Only create/update when batch.status in ('COMPLETED','REJECTED')
      - If status is other (e.g., PENDING, ONGOING), we do not create (but we could update existing if desired)
    """
    try:
        status = getattr(instance, 'status', None)
        if status not in ('COMPLETED', 'REJECTED'):
            # Optionally: If a TrainingPartnerBatch exists and status changed away from COMPLETED/REJECTED,
            # we could delete or mark it. For now, do nothing.
            return

        centre = getattr(instance, 'centre', None)
        if not centre:
            return

        # Attempt to find partner from centre
        partner = None
        # Common attribute names - try them in order
        for attr in ('partner', 'training_partner', 'owner'):
            if hasattr(centre, attr):
                partner = getattr(centre, attr)
                break

        if not partner:
            # maybe TrainingPartnerCentre has FK named 'training_partner_id' or similar
            if hasattr(centre, 'training_partner_id') and getattr(centre, 'training_partner_id'):
                try:
                    partner = TrainingPartner.objects.get(pk=getattr(centre, 'training_partner_id'))
                except Exception:
                    partner = None

        if not partner:
            # cannot find partner — nothing to do
            return

        # Create or update TrainingPartnerBatch (unique_together partner+batch)
        obj, created = TrainingPartnerBatch.objects.update_or_create(
            partner=partner,
            batch=instance,
            defaults={
                'status': status,
                'assigned_on': timezone.now()
            }
        )
        # done
    except Exception as exc:
        # don't crash the request — log if you have logging configured
        import logging
        logging.getLogger(__name__).exception("Error updating TrainingPartnerBatch for Batch id %s: %s", getattr(instance, 'id', None), exc)
