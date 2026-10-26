from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Owner(models.Model):
    """Propietario o conductor que agenda la cita. No tiene cuenta en la plataforma."""

    class DocumentType(models.TextChoices):
        CC = 'CC', 'Cédula de ciudadanía'
        CE = 'CE', 'Cédula de extranjería'
        PA = 'PA', 'Pasaporte'
        NIT = 'NIT', 'NIT'

    document_type = models.CharField('tipo de documento', max_length=3, choices=DocumentType.choices)
    document_number = models.CharField('número de documento', max_length=20)
    first_name = models.CharField('nombres', max_length=100)
    last_name = models.CharField('apellidos', max_length=100)
    email = models.EmailField('correo electrónico')
    phone = models.CharField('teléfono', max_length=20)
    accepts_data_processing = models.BooleanField('acepta el tratamiento de datos', default=False)
    data_processing_accepted_at = models.DateTimeField('fecha de aceptación de datos', null=True, blank=True)
    created_at = models.DateTimeField('creado', auto_now_add=True)
    updated_at = models.DateTimeField('actualizado', auto_now=True)

    class Meta:
        verbose_name = 'propietario'
        verbose_name_plural = 'propietarios'
        ordering = ['last_name', 'first_name']
        constraints = [
            models.UniqueConstraint(
                fields=['document_type', 'document_number'],
                name='unique_owner_document',
            ),
            # Si aceptó el tratamiento de datos (Ley 1581), debe quedar la fecha de aceptación.
            models.CheckConstraint(
                condition=Q(accepts_data_processing=False) | Q(data_processing_accepted_at__isnull=False),
                name='owner_consent_has_date',
            ),
        ]

    def __str__(self):
        return f'{self.full_name} ({self.document_type} {self.document_number})'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    @staticmethod
    def normalize_document_number(value):
        return ''.join((value or '').split()).upper()

    def sync_consent_date(self):
        """Guarda la fecha al aceptar el tratamiento de datos y la quita si se retira."""
        if self.accepts_data_processing and not self.data_processing_accepted_at:
            self.data_processing_accepted_at = timezone.now()
        elif not self.accepts_data_processing:
            self.data_processing_accepted_at = None

    def clean_fields(self, exclude=None):
        self.document_number = self.normalize_document_number(self.document_number)
        self.sync_consent_date()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        number = self.document_number
        if not number:
            return
        if self.document_type == self.DocumentType.PA:
            if not number.isalnum():
                raise ValidationError({'document_number': 'El pasaporte solo puede tener letras y números.'})
        elif not number.isdigit():
            raise ValidationError({'document_number': 'El número de documento solo puede tener dígitos.'})

    def save(self, *args, **kwargs):
        self.document_number = self.normalize_document_number(self.document_number)
        self.sync_consent_date()
        super().save(*args, **kwargs)
