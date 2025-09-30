# bmmu/templatetags/custom_tags.py
import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter
def attr(obj, attr_name):
    """
    Safely get attribute or dict item and normalize None-like values to empty string.

    Returns:
      - empty string for Python None
      - empty string for string values that are "None", "null" (case-insensitive) or only whitespace
      - original value otherwise
    """
    try:
        if isinstance(obj, dict):
            val = obj.get(attr_name, "")
        else:
            val = getattr(obj, attr_name, "")

        # Coerce None -> ""
        if val is None:
            return ""

        # If it's a string, normalize and filter out literal "None"/"null"/empty
        if isinstance(val, str):
            s = val.strip()
            if s == "" or s.lower() in ("none", "null"):
                return ""
            return val  # return original string (not stripped) to preserve formatting

        # For numbers, dates, booleans, etc., just return as-is
        return val
    except Exception:
        return ""


@register.filter
def get_item(dictionary, key):
    if not dictionary:
        return []
    try:
        return dictionary.get(key, []) if isinstance(dictionary, dict) else []
    except Exception:
        return []

@register.filter(is_safe=True)
def to_json(obj):
    """
    Safely dump Python object to JSON for embedding in templates.
    Usage: {{ groupable_values|to_json|safe }}
    """
    try:
        return mark_safe(json.dumps(obj, default=str))
    except Exception:
        return mark_safe(json.dumps({}))

@register.filter
def get_item(dictionary, key):
    if not dictionary:
        return None
    return dictionary.get(key)
