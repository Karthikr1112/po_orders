from django import template

register = template.Library()


@register.filter
def split(value, sep=","):
    """Split a string by sep and return a list."""
    if not value:
        return []
    return [v.strip() for v in str(value).split(sep) if v.strip()]
