import datetime

from django.db import transaction

from .models import TimeSlot


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
