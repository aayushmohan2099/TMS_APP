import re
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from bmmu.models import District, DmmuDistrictAssignment

User = get_user_model()

def _normalize(name: str) -> str:
    """
    Normalize a name for comparison:
    - convert to uppercase
    - remove any non-alphanumeric characters (spaces, punctuation, underscores)
    """
    if not name:
        return ""
    return re.sub(r'[^0-9A-Z]', '', name.upper())

class Command(BaseCommand):
    help = "Auto-assign DMMU/DC users to Districts based on their username"

    def handle(self, *args, **options):
        # load districts and build normalized lookup
        districts = District.objects.all()
        norm_map = {}
        for d in districts:
            # Normalize the English district name. If there are other name fields
            # you want to support, include them here too.
            key = _normalize(d.district_name_en)
            if key:
                norm_map.setdefault(key, []).append(d)

        # consider users that appear to be DMMU/DC accounts by username prefix
        users = User.objects.filter(username__iregex=r'^(DMM|DC|DMMU|DMM_)')  # broad capture
        created_count = 0
        skipped_count = 0
        missing_district_count = 0

        for u in users:
            try:
                # Expect username pattern like DMM_<DISTRICT> or DC_<DISTRICT>
                # Split only on first underscore to preserve the rest
                if "_" not in u.username:
                    self.stdout.write(self.style.WARNING(f"Skipped {u.username}: missing '_' separator"))
                    skipped_count += 1
                    continue

                _, district_part = u.username.split("_", 1)
                if not district_part:
                    self.stdout.write(self.style.WARNING(f"Skipped {u.username}: empty district part"))
                    skipped_count += 1
                    continue

                # Normalize the extracted district part and try to find a district
                norm = _normalize(district_part)
                district = None

                # Direct normalized lookup
                candidates = norm_map.get(norm)
                if candidates:
                    # If multiple candidates (unlikely), choose the first — you can change logic if needed
                    district = candidates[0]
                else:
                    # Try more flexible matching:
                    # - iterate all district names and look for substring matches (normalized)
                    # This helps when username contains abbreviations or partial names.
                    for key, dlist in norm_map.items():
                        if norm in key or key in norm:
                            district = dlist[0]
                            break

                if not district:
                    self.stdout.write(self.style.WARNING(f"No district found for {u.username} (parsed '{district_part}')"))
                    missing_district_count += 1
                    continue

                assignment, created = DmmuDistrictAssignment.objects.get_or_create(user=u, district=district)
                if created:
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(f"Assigned {u.username} -> {district.district_name_en}"))
                else:
                    # optionally notify it already exists
                    self.stdout.write(f"Already assigned {u.username} -> {district.district_name_en}")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error for {u.username}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Done. {created_count} new assignments created, "
            f"{missing_district_count} users had no matching district, "
            f"{skipped_count} users were skipped."
        ))
