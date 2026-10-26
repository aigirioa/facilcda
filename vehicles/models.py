from django.db import models
from django.db.models import Q

from customers.models import Owner

from .validators import MIN_MODEL_YEAR, normalize_plate, validate_model_year, validate_plate


class Vehicle(models.Model):

    class VehicleType(models.TextChoices):
        LIGHT_PRIVATE = 'LIGHT_PRIVATE', 'Liviano particular'
        LIGHT_PUBLIC = 'LIGHT_PUBLIC', 'Liviano público'
        MOTORCYCLE = 'MOTORCYCLE', 'Motocicleta'
        HEAVY = 'HEAVY', 'Pesado'

    plate = models.CharField('placa', max_length=6, unique=True, validators=[validate_plate])
    vehicle_type = models.CharField('tipo de vehículo', max_length=20, choices=VehicleType.choices)
    brand = models.CharField('marca', max_length=50)
    line = models.CharField('línea', max_length=50, blank=True)
    model_year = models.PositiveSmallIntegerField('modelo (año)', validators=[validate_model_year])
    owner = models.ForeignKey(Owner, on_delete=models.PROTECT, related_name='vehicles', verbose_name='propietario')
    created_at = models.DateTimeField('creado', auto_now_add=True)
    updated_at = models.DateTimeField('actualizado', auto_now=True)

    class Meta:
        verbose_name = 'vehículo'
        verbose_name_plural = 'vehículos'
        ordering = ['plate']
        constraints = [
            # Respaldo en la base de datos del formato de placa (carro ABC123 o moto ABC12D).
            models.CheckConstraint(
                condition=Q(plate__regex=r'^[A-Z]{3}[0-9]{2}[A-Z0-9]$'),
                name='vehicle_plate_format',
            ),
            models.CheckConstraint(
                condition=Q(model_year__gte=MIN_MODEL_YEAR),
                name='vehicle_model_year_min',
            ),
        ]

    def __str__(self):
        return self.plate

    def clean_fields(self, exclude=None):
        self.plate = normalize_plate(self.plate)
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        self.plate = normalize_plate(self.plate)
        super().save(*args, **kwargs)

    def history(self):
        """Citas del vehículo de la más reciente a la más antigua.

        Cuando existan Revision y Resultado (sprints 4 a 6) se agregan aquí con select_related.
        """
        return (
            self.appointments
            .select_related('slot', 'owner')
            .order_by('-slot__date', '-slot__start_time', '-created_at')
        )
