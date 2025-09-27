# utils.py
from django.http import HttpResponse
from openpyxl import Workbook
from datetime import date

def export_blueprint(resource_class, filename):
    """
    Create and return an Excel file with model headers.
    Auto-fill created_at with today's date if present.
    """
    resource = resource_class()
    try:
        headers = resource.get_export_headers()
    except Exception:
        # fallback: try get_export_fields or resource.get_export_fields
        headers = [f.column_name for f in resource.get_export_fields()]

    wb = Workbook()
    ws = wb.active
    ws.title = "Blueprint"

    # Write headers
    ws.append(headers)

    # Write sample row with created_at pre-filled if present
    today = date.today().strftime("%Y-%m-%d")
    row = [(today if h == "created_at" else "") for h in headers]
    ws.append(row)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response
