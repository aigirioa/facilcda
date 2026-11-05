import datetime

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from configuration.models import CdaConfiguration
from customers.models import Owner
from facilcda.dates import local_now
from vehicles.models import Vehicle
from vehicles.validators import normalize_plate

from .models import Appointment, TimeSlot


class BookingError(Exception):
    """No se pudo agendar; el mensaje se muestra al usuario."""


class SlotUnavailableError(BookingError):
    pass


class PlateHasActiveAppointmentError(BookingError):
    pass


class AppointmentNotChangeableError(Exception):
    """La cita ya no se puede reprogramar ni cancelar; el mensaje se muestra al usuario."""


SLOT_UNAVAILABLE_MESSAGE = 'El horario elegido ya no está disponible. Por favor elige otro.'
SLOT_FULL_MESSAGE = 'El horario elegido se llenó mientras completabas tus datos. Por favor elige otro.'
SAME_SLOT_MESSAGE = 'Tu cita ya está en ese horario. Elige otro.'
PLATE_HAS_ACTIVE_APPOINTMENT_MESSAGE = (
    'La placa {plate} ya tiene una cita activa. Consulta tu cita o cancélala antes de agendar otra.'
)
NOT_CHANGEABLE_MESSAGE = (
    'Esta cita ya no se puede reprogramar ni cancelar: solo se puede con una cita agendada '
    'y antes de la hora de inicio.'
)


def build_slot_times(start_time, end_time, interval_minutes):
    """Horas (inicio, fin) de cada franja entre start_time y end_time. Una franja incompleta al final no se crea."""
    day = datetime.date.min
    current = datetime.datetime.combine(day, start_time)
    limit = datetime.datetime.combine(day, end_time)
    step = datetime.timedelta(minutes=interval_minutes)
    times = []
    while current + step <= limit:
        times.append((current.time(), (current + step).time()))
        current += step
    return times


def create_time_slots(start_date, end_date, start_time, end_time, interval_minutes, capacity, weekdays):
    """Crea en lote las franjas del rango de fechas en los días de la semana indicados (0 = lunes).

    No duplica las franjas que ya existen con la misma fecha y hora de inicio.
    Devuelve (creadas, omitidas).
    """
    slot_times = build_slot_times(start_time, end_time, interval_minutes)
    weekdays = {int(day) for day in weekdays}
    candidates = []
    day = start_date
    while day <= end_date:
        if day.weekday() in weekdays:
            candidates.extend((day, start, end) for start, end in slot_times)
        day += datetime.timedelta(days=1)

    with transaction.atomic():
        existing = set(
            TimeSlot.objects
            .filter(date__range=(start_date, end_date))
            .values_list('date', 'start_time')
        )
        new_slots = [
            TimeSlot(date=date, start_time=start, end_time=end, capacity=capacity)
            for date, start, end in candidates
            if (date, start) not in existing
        ]
        # ignore_conflicts cubre el caso de dos administradores creando el mismo lote a la vez.
        TimeSlot.objects.bulk_create(new_slots, ignore_conflicts=True)

    created = len(new_slots)
    return created, len(candidates) - created


def available_time_slots():
    """Franjas que el público puede elegir: activas, con cupo libre, sin fechas ni horas pasadas
    (hora de Bogotá) y hasta max_booking_days días adelante. Ordenadas por fecha y hora.
    """
    now = local_now()
    today = now.date()
    last_day = today + datetime.timedelta(days=CdaConfiguration.get().max_booking_days)
    return (
        TimeSlot.objects
        .filter(is_active=True, date__range=(today, last_day))
        .exclude(date=today, start_time__lte=now.time())
        .annotate(active_count=Count(
            'appointments', filter=Q(appointments__status__in=Appointment.ACTIVE_STATUSES),
        ))
        .filter(active_count__lt=F('capacity'))
        .annotate(free_count=F('capacity') - F('active_count'))
        .order_by('date', 'start_time')
    )


def _lock_available_slot(slot_id):
    """Bloquea la franja con select_for_update y verifica que el público la pueda elegir.

    Se llama dentro de una transacción. El bloqueo evita que dos personas tomen el mismo turno.
    """
    slot = TimeSlot.objects.select_for_update().filter(pk=slot_id).first()
    if slot is None or not available_time_slots().filter(pk=slot.pk).exists():
        if slot is not None and slot.is_active and slot.available_spots == 0:
            raise SlotUnavailableError(SLOT_FULL_MESSAGE)
        raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE)
    return slot


def _first_free_turn(slot):
    taken_turns = set(slot.appointments.active().values_list('turn', flat=True))
    return next((number for number in range(1, slot.capacity + 1) if number not in taken_turns), None)


def book_appointment(slot_id, owner_data, vehicle_data):
    """Agenda una cita en la franja con el primer turno libre.

    Reutiliza y actualiza el propietario (por tipo y número de documento) y el vehículo (por placa).
    La franja se bloquea con select_for_update para que dos personas no tomen el mismo turno;
    las restricciones de la base de datos son el respaldo final. Si algo falla, no se guarda nada.
    """
    plate = normalize_plate(vehicle_data['plate'])
    with transaction.atomic():
        slot = _lock_available_slot(slot_id)

        owner, _ = Owner.objects.update_or_create(
            document_type=owner_data['document_type'],
            document_number=Owner.normalize_document_number(owner_data['document_number']),
            defaults={
                'first_name': owner_data['first_name'],
                'last_name': owner_data['last_name'],
                'email': owner_data['email'],
                'phone': owner_data['phone'],
                'accepts_data_processing': True,
                'data_processing_accepted_at': timezone.now(),
            },
        )
        vehicle, _ = Vehicle.objects.update_or_create(
            plate=plate,
            defaults={
                'vehicle_type': vehicle_data['vehicle_type'],
                'brand': vehicle_data['brand'],
                'line': vehicle_data.get('line', ''),
                'model_year': vehicle_data['model_year'],
                'owner': owner,
            },
        )
        if vehicle.appointments.active().exists():
            raise PlateHasActiveAppointmentError(PLATE_HAS_ACTIVE_APPOINTMENT_MESSAGE.format(plate=plate))

        turn = _first_free_turn(slot)
        if turn is None:
            raise SlotUnavailableError(SLOT_FULL_MESSAGE)

        try:
            with transaction.atomic():
                return Appointment.objects.create(vehicle=vehicle, owner=owner, slot=slot, turn=turn)
        except IntegrityError:
            # Otra solicitud ganó la carrera: la base de datos rechazó el turno o la placa repetida.
            if vehicle.appointments.active().exists():
                raise PlateHasActiveAppointmentError(PLATE_HAS_ACTIVE_APPOINTMENT_MESSAGE.format(plate=plate))
            raise SlotUnavailableError(SLOT_FULL_MESSAGE)


def _lock_changeable_appointment(appointment_id):
    """Bloquea la cita y verifica que todavía se pueda reprogramar o cancelar (ver Appointment.can_be_changed)."""
    appointment = Appointment.objects.select_for_update().filter(pk=appointment_id).first()
    if appointment is None or not appointment.can_be_changed:
        raise AppointmentNotChangeableError(NOT_CHANGEABLE_MESSAGE)
    return appointment


def reschedule_appointment(appointment_id, slot_id):
    """Pasa la cita a otra franja disponible, con el primer turno libre. El turno anterior queda libre.

    La cita conserva su código. Si algo falla, la cita queda como estaba.
    """
    with transaction.atomic():
        appointment = _lock_changeable_appointment(appointment_id)
        if appointment.slot_id == slot_id:
            raise SlotUnavailableError(SAME_SLOT_MESSAGE)
        slot = _lock_available_slot(slot_id)
        turn = _first_free_turn(slot)
        if turn is None:
            raise SlotUnavailableError(SLOT_FULL_MESSAGE)

        appointment.slot = slot
        appointment.turn = turn
        try:
            with transaction.atomic():
                appointment.save(update_fields=['slot', 'turn', 'updated_at'])
        except IntegrityError:
            # Otra solicitud tomó el turno al mismo tiempo; la base de datos lo rechazó.
            raise SlotUnavailableError(SLOT_FULL_MESSAGE)
    return appointment


def cancel_appointment(appointment_id):
    """Cancela la cita. Su turno queda libre porque solo las citas activas ocupan turno."""
    with transaction.atomic():
        appointment = _lock_changeable_appointment(appointment_id)
        appointment.status = Appointment.Status.CANCELLED
        appointment.cancelled_at = timezone.now()
        appointment.save(update_fields=['status', 'cancelled_at', 'updated_at'])
    return appointment


def find_appointment(plate, document_number):
    """Cita de la placa agendada con ese número de documento: la activa o, si no hay, la más reciente.

    Devuelve None si no coinciden, sin distinguir si falló la placa o el documento.
    """
    appointments = Appointment.objects.filter(
        vehicle__plate=normalize_plate(plate),
        owner__document_number=Owner.normalize_document_number(document_number),
    )
    return (
        appointments.active().first()
        or appointments.order_by('-slot__date', '-slot__start_time', '-created_at').first()
    )
