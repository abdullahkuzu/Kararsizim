from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def time_ago(value):
    seconds = int((timezone.now() - value).total_seconds())
    if seconds < 60:
        return "az önce"
    if seconds < 3600:
        return f"{seconds // 60} dakika önce"
    if seconds < 86400:
        return f"{seconds // 3600} saat önce"
    if seconds < 30 * 86400:
        return f"{seconds // 86400} gün önce"
    return timezone.localtime(value).strftime("%d.%m.%Y")


@register.simple_tag(takes_context=True)
def absolute_url(context, path):
    return context["request"].build_absolute_uri(path)
