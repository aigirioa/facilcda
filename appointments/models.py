import secrets

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from customers.models import Owner
from vehicles.models import Vehicle


# Sin caracteres que se confunden al leerlos: 0, O, 1, I.
APPOINTMENT_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
APPOINTMENT_CODE_LENGTH = 8


def generate_appointment_code():
    return ''.join(secrets.choice(APPOINTMENT_CODE_ALPHABET) for _ in range(APPOINTMENT_CODE_LENGTH))


class TimeSlot(models.Model):
    """Franja horaria con un cupo de turnos (uno por línea de inspección)."""

    date = models.DateField('fecha')
    start_time = models.TimeField('hora de inicio')
    end_time = models.TimeField('hora de fin')
    capacity = models.PositiveSmallIntegerField('cupo', default=2)
    is_active = models.BooleanField('activa', default=True)

    class Meta:
        verbose_name = 'franja horaria'
        verbose_name_plural = 'franjas horarias'
        ordering = ['date', 'start_time']
        constraints = [
            models.UniqueConstraint(fields=['date', 'start_time'], name='unique_slot_date_start_time'),
            models.CheckConstraint(condition=Q(end_time__gt=F('start_time')), name='slot_end_after_start'),
            models.CheckConstraint(condition=Q(capacity__gte=1), name='slot_capacity_min_1'),
        ]

    def __str__(self):
        return f'{self.date:%Y-%m-%d} {self.start_time:%H:%M}-{self.end_time:%H:%M}'

    def clean(self):
        super().clean()
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({'end_time': 'La hora de fin debe ser mayor que la hora de inicio.'})

    @property
    def occupied_spots(self):
        return self.appointments.active().count()

    @property
    def available_spots(self):
        return max(self.capacity - self.occupied_spots, 0)


class AppointmentQuerySet(models.QuerySet):

    def active(self):
        return self.filter(status__in=Appointment.ACTIVE_STATUSES)


class Appointment(models.Model):

    class Status(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Agendada'
        RECEIVED = 'RECEIVED', 'Recibida'
        IN_PROGRESS = 'IN_PROGRESS', 'En revisión'
        FINISHED = 'FINISHED', 'Finalizada'
        CANCELLED = 'CANCELLED', 'Cancelada'
        NO_SHOW = 'NO_SHOW', 'No asistió'

    ACTIVE_STATUSES = [Status.SCHEDULED, Status.RECEIVED, Status.IN_PROGRESS]

    code = models.CharField('código', max_length=APPOINTMENT_CODE_LENGTH, unique=True, editable=False)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name='appointments', verbose_name='vehículo')
    # Quién agendó; se guarda aparte por si el vehículo cambia de dueño.
    owner = models.ForeignKey(Owner, on_delete=models.PROTECT, related_name='appointments', verbose_name='propietario')
    slot = models.ForeignKey(TimeSlot, on_delete=models.PROTECT, related_name='appointments', verbose_name='franja')
    turn = models.PositiveSmallIntegerField('turno')
    status = models.CharField('estado', max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    created_at = models.DateTimeField('creado', auto_now_add=True)
    updated_at = models.DateTimeField('actualizado', auto_now=True)
    cancelled_at = models.DateTimeField('cancelada en', null=True, blank=True)

    objects = AppointmentQuerySet.as_manager()

    class Meta:
        verbose_name = 'cita'
        verbose_name_plural = 'citas'
        ordering = ['slot__date', 'slot__start_time', 'turn']
        constraints = [
            # Dos citas activas no pueden ocupar el mismo turno de una franja.
            models.UniqueConstraint(
                fields=['slot', 'turn'],
                condition=Q(status__in=['SCHEDULED', 'RECEIVED', 'IN_PROGRESS']),
                name='unique_active_turn_per_slot',
            ),
            # Una placa solo puede tener una cita activa.
            models.UniqueConstraint(
                fields=['vehicle'],
                condition=Q(status__in=['SCHEDULED', 'RECEIVED', 'IN_PROGRESS']),
                name='unique_active_appointment_per_vehicle',
            ),
            models.CheckConstraint(condition=Q(turn__gte=1), name='appointment_turn_min_1'),
        ]

    def __str__(self):
        return f'{self.code} - {self.vehicle}'

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    def clean(self):
        super().clean()
        if self.slot_id and self.turn and self.turn > self.slot.capacity:
            raise ValidationError({'turn': f'El turno no puede ser mayor que el cupo de la franja ({self.slot.capacity}).'})

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_appointment_code()
            while Appointment.objects.filter(code=self.code).exists():
                self.code = generate_appointment_code()
        super().save(*args, **kwargs)
