from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def local_now():
    """Fecha y hora actual en la zona del CDA (Bogotá), también fuera de una petición."""
    return timezone.now().astimezone(ZoneInfo(settings.DISPLAY_TIME_ZONE))


def local_today():
    return local_now().date()
