import re

from django.core.exceptions import ValidationError
from django.utils import timezone


# Carro: ABC123. Moto: ABC12D.
CAR_PLATE_REGEX = re.compile(r'^[A-Z]{3}[0-9]{3}$')
MOTORCYCLE_PLATE_REGEX = re.compile(r'^[A-Z]{3}[0-9]{2}[A-Z]$')

MIN_MODEL_YEAR = 1950


def normalize_plate(value):
    """Deja la placa en mayúsculas y sin espacios ni guiones: 'abc-123' -> 'ABC123'."""
    return re.sub(r'[\s-]', '', value or '').upper()


def validate_plate(value):
    if not (CAR_PLATE_REGEX.match(value) or MOTORCYCLE_PLATE_REGEX.match(value)):
        raise ValidationError(
            'La placa no es válida. Usa el formato ABC123 (carro) o ABC12D (moto).',
            code='invalid_plate',
        )


def validate_model_year(value):
    max_year = timezone.now().year + 1
    if not MIN_MODEL_YEAR <= value <= max_year:
        raise ValidationError(
            f'El modelo debe estar entre {MIN_MODEL_YEAR} y {max_year}.',
            code='invalid_model_year',
        )
