# bmmu/templatetags/custom_tags.py
import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter
def attr(obj, attr_name):
    try:
        if isinstance(obj, dict):
            return obj.get(attr_name, "")
        return getattr(obj, attr_name, "")
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
