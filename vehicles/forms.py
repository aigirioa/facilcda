from django import forms

from .models import Vehicle
from .validators import normalize_plate, validate_plate


class PlateField(forms.CharField):
    """Acepta la placa con espacios, guiones o en minúsculas y la normaliza antes de validarla."""

    default_validators = [validate_plate]

    def __init__(self, **kwargs):
        kwargs.pop('max_length', None)
        super().__init__(**kwargs)

    def widget_attrs(self, widget):
        attrs = super().widget_attrs(widget)
        attrs.update({'maxlength': '8', 'autocapitalize': 'characters', 'placeholder': 'ABC123'})
        return attrs

    def to_python(self, value):
        return normalize_plate(super().to_python(value))


class VehicleAdminForm(forms.ModelForm):
    plate = PlateField(label='Placa', help_text='Carro ABC123 o moto ABC12D. Se guarda en mayúsculas y sin espacios.')

    class Meta:
        model = Vehicle
        fields = '__all__'
