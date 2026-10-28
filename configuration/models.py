from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


DEFAULT_DATA_PROCESSING_TEXT = (
    'De acuerdo con la Ley 1581 de 2012 y sus decretos reglamentarios, autorizo al Centro de '
    'Diagnóstico Automotor para recolectar, almacenar y usar mis datos personales (nombre, '
    'documento, correo, teléfono y placa del vehículo) con el único fin de agendar y gestionar '
    'la revisión técnico-mecánica y de emisiones contaminantes, e informarme su avance y '
    'resultado. Como titular puedo conocer, actualizar, rectificar y solicitar la supresión de '
    'mis datos, y revocar esta autorización, comunicándome con el CDA.'
)


class CdaConfiguration(models.Model):
    """Datos del CDA y parámetros del sistema. Solo existe un registro (id = 1)."""

    SINGLETON_ID = 1

    cda_name = models.CharField('nombre del CDA', max_length=150, default='Centro de Diagnóstico Automotor')
    address = models.CharField('dirección', max_length=200, blank=True)
    phone = models.CharField('teléfono', max_length=30, blank=True)
    opening_hours = models.CharField(
        'horario de atención', max_length=200, blank=True,
        help_text='Texto libre, por ejemplo "Lunes a sábado 7:00 a 17:00".',
    )
    slot_duration_minutes = models.PositiveSmallIntegerField(
        'duración de la franja (minutos)', default=30, validators=[MinValueValidator(1)],
    )
    slot_capacity = models.PositiveSmallIntegerField(
        'cupo por franja', default=2, validators=[MinValueValidator(1)],
        help_text='Número de líneas de inspección.',
    )
    max_booking_days = models.PositiveSmallIntegerField(
        'días máximos de agendamiento', default=30, validators=[MinValueValidator(1)],
        help_text='Hasta cuántos días adelante se puede agendar.',
    )
    polling_interval_seconds = models.PositiveSmallIntegerField(
        'intervalo de consulta del estado (segundos)', default=15, validators=[MinValueValidator(5)],
        help_text='Cada cuánto la página "Mi cita" consulta el avance de la revisión.',
    )
    data_processing_text = models.TextField('texto de tratamiento de datos', default=DEFAULT_DATA_PROCESSING_TEXT)
    updated_at = models.DateTimeField('actualizado', auto_now=True)

    class Meta:
        verbose_name = 'configuración del CDA'
        verbose_name_plural = 'configuración del CDA'
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name='cda_configuration_single_row'),
            models.CheckConstraint(condition=Q(slot_duration_minutes__gte=1), name='cda_configuration_slot_duration_min_1'),
            models.CheckConstraint(condition=Q(slot_capacity__gte=1), name='cda_configuration_slot_capacity_min_1'),
            models.CheckConstraint(condition=Q(max_booking_days__gte=1), name='cda_configuration_max_booking_days_min_1'),
            models.CheckConstraint(condition=Q(polling_interval_seconds__gte=5), name='cda_configuration_polling_min_5'),
        ]

    def __str__(self):
        return self.cda_name

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_ID
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        """Devuelve el único registro de configuración y lo crea con los valores por defecto si no existe."""
        configuration, _ = cls.objects.get_or_create(pk=cls.SINGLETON_ID)
        return configuration


class InspectionStage(models.Model):
    """Catálogo de etapas de la revisión. El orden define la secuencia y no se puede retroceder."""

    name = models.CharField('nombre', max_length=80)
    order = models.PositiveSmallIntegerField('orden', unique=True, validators=[MinValueValidator(1)])
    description = models.CharField('descripción', max_length=200, help_text='Texto que ve el usuario.')
    is_active = models.BooleanField('activa', default=True)

    class Meta:
        verbose_name = 'etapa de revisión'
        verbose_name_plural = 'etapas de revisión'
        ordering = ['order']
        constraints = [
            models.CheckConstraint(condition=Q(order__gte=1), name='inspection_stage_order_min_1'),
        ]

    def __str__(self):
        return f'{self.order}. {self.name}'
