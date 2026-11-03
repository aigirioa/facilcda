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


SLOT_UNAVAILABLE_MESSAGE = 'El horario elegido ya no está disponible. Por favor elige otro.'
SLOT_FULL_MESSAGE = 'El horario elegido se llenó mientras completabas tus datos. Por favor elige otro.'
PLATE_HAS_ACTIVE_APPOINTMENT_MESSAGE = (
    'La placa {plate} ya tiene una cita activa. Consulta tu cita o cancélala antes de agendar otra.'
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


def book_appointment(slot_id, owner_data, vehicle_data):
    """Agenda una cita en la franja con el primer turno libre.

    Reutiliza y actualiza el propietario (por tipo y número de documento) y el vehículo (por placa).
    La franja se bloquea con select_for_update para que dos personas no tomen el mismo turno;
    las restricciones de la base de datos son el respaldo final. Si algo falla, no se guarda nada.
    """
    plate = normalize_plate(vehicle_data['plate'])
    with transaction.atomic():
        slot = TimeSlot.objects.select_for_update().filter(pk=slot_id).first()
        if slot is None or not available_time_slots().filter(pk=slot.pk).exists():
            if slot is not None and slot.is_active and slot.available_spots == 0:
                raise SlotUnavailableError(SLOT_FULL_MESSAGE)
            raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE)

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

        taken_turns = set(slot.appointments.active().values_list('turn', flat=True))
        turn = next((number for number in range(1, slot.capacity + 1) if number not in taken_turns), None)
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
