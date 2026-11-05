"""Límite de intentos fallidos de la consulta con placa y documento, por IP, con la caché de Django."""
import time

from django.conf import settings
from django.core.cache import cache


MAX_LOOKUP_FAILURES = 5
LOOKUP_WINDOW_SECONDS = 15 * 60


def client_ip(request):
    if settings.USE_X_FORWARDED_FOR:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded:
            # Agrega al final la IP que ve; las anteriores las puede escribir el cliente.
            return forwarded.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '')


def _failures_key(ip):
    return f'appointment-lookup-failures:{ip}'


def is_lookup_blocked(ip):
    data = cache.get(_failures_key(ip))
    return data is not None and data['count'] >= MAX_LOOKUP_FAILURES


def register_lookup_failure(ip):
    """Cuenta un intento fallido. La ventana de 15 minutos empieza con el primer fallo y no se alarga."""
    key = _failures_key(ip)
    now = time.time()
    data = cache.get(key) or {'count': 0, 'started_at': now}
    data['count'] += 1
    remaining = LOOKUP_WINDOW_SECONDS - (now - data['started_at'])
    cache.set(key, data, max(int(remaining), 1))
