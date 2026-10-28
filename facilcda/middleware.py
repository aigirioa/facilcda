from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


class DisplayTimezoneMiddleware:
    """Muestra fechas y horas en la zona de Bogotá. En la base de datos se guardan en UTC."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.display_timezone = ZoneInfo(settings.DISPLAY_TIME_ZONE)

    def __call__(self, request):
        with timezone.override(self.display_timezone):
            return self.get_response(request)
