"""Acceso a una cita guardado en la sesión, para el usuario que no tiene cuenta."""
import datetime

from django.utils import timezone


# Cita recién agendada que puede ver la sesión en la página de confirmación.
CONFIRMATION_SESSION_KEY = 'confirmed_appointment'
# Cita encontrada con placa y documento que la sesión puede ver en "Mi cita".
MY_APPOINTMENT_SESSION_KEY = 'my_appointment'
ACCESS_MAX_AGE = datetime.timedelta(minutes=30)


def grant_access(session, key, appointment):
    session[key] = {'appointment_id': appointment.pk, 'granted_at': timezone.now().timestamp()}


def granted_appointment_id(session, key):
    """Id de la cita guardada en la sesión, o None si no hay o ya pasaron ACCESS_MAX_AGE."""
    data = session.get(key)
    if not data:
        return None
    if timezone.now().timestamp() - data['granted_at'] > ACCESS_MAX_AGE.total_seconds():
        del session[key]
        return None
    return data['appointment_id']


def revoke_access(session, key):
    session.pop(key, None)
