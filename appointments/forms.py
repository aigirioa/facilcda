import datetime

from django import forms
from django.core.validators import RegexValidator

from configuration.models import CdaConfiguration
from customers.models import Owner
from facilcda.dates import local_today
from vehicles.forms import PlateField
from vehicles.models import Vehicle
from vehicles.validators import validate_model_year

from .services import build_slot_times


WEEKDAY_CHOICES = [
    (0, 'Lunes'),
    (1, 'Martes'),
    (2, 'Miércoles'),
    (3, 'Jueves'),
    (4, 'Viernes'),
    (5, 'Sábado'),
    (6, 'Domingo'),
]

MAX_BATCH_DAYS = 92


class TimeSlotBatchForm(forms.Form):
    start_date = forms.DateField(label='Desde', widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    end_date = forms.DateField(label='Hasta', widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    start_time = forms.TimeField(
        label='Hora de inicio', initial=datetime.time(7, 0),
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}, format='%H:%M'),
    )
    end_time = forms.TimeField(
        label='Hora de fin', initial=datetime.time(17, 0),
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}, format='%H:%M'),
    )
    interval_minutes = forms.IntegerField(
        label='Duración de cada franja (minutos)', min_value=5, max_value=240,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    capacity = forms.IntegerField(
        label='Cupo por franja', min_value=1, max_value=50,
        help_text='Número de vehículos que se atienden a la vez (líneas de inspección).',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    weekdays = forms.TypedMultipleChoiceField(
        label='Días de la semana', choices=WEEKDAY_CHOICES, coerce=int,
        initial=[0, 1, 2, 3, 4, 5], widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configuration = CdaConfiguration.get()
        self.fields['interval_minutes'].initial = configuration.slot_duration_minutes
        self.fields['capacity'].initial = configuration.slot_capacity
        today = local_today()
        self.fields['start_date'].initial = today
        self.fields['end_date'].initial = today

    def clean_start_date(self):
        start_date = self.cleaned_data['start_date']
        if start_date < local_today():
            raise forms.ValidationError('No se pueden crear franjas en fechas pasadas.')
        return start_date

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        interval = cleaned_data.get('interval_minutes')

        if start_date and end_date:
            if end_date < start_date:
                self.add_error('end_date', 'La fecha final debe ser igual o posterior a la inicial.')
            elif (end_date - start_date).days + 1 > MAX_BATCH_DAYS:
                self.add_error('end_date', f'El rango no puede superar {MAX_BATCH_DAYS} días.')

        if start_time and end_time:
            if end_time <= start_time:
                self.add_error('end_time', 'La hora de fin debe ser mayor que la hora de inicio.')
            elif interval and not build_slot_times(start_time, end_time, interval):
                self.add_error('interval_minutes', 'La duración es mayor que el horario: no cabe ninguna franja.')

        return cleaned_data


OWNER_FIELDS = ['document_type', 'document_number', 'first_name', 'last_name', 'email', 'phone']
VEHICLE_FIELDS = ['plate', 'vehicle_type', 'brand', 'line', 'model_year']


class BookingForm(forms.Form):
    """Datos del propietario y del vehículo para agendar en una franja ya elegida."""

    document_type = forms.ChoiceField(label='Tipo de documento', choices=Owner.DocumentType.choices)
    document_number = forms.CharField(label='Número de documento', max_length=20)
    first_name = forms.CharField(label='Nombres', max_length=100)
    last_name = forms.CharField(label='Apellidos', max_length=100)
    email = forms.EmailField(label='Correo electrónico')
    phone = forms.CharField(
        label='Celular o teléfono', max_length=20,
        validators=[RegexValidator(r'^\+?[0-9 ]{7,20}$', 'Escribe solo números (mínimo 7).')],
    )
    plate = PlateField(label='Placa', help_text='Carro ABC123 o moto ABC12D.')
    vehicle_type = forms.ChoiceField(label='Tipo de vehículo', choices=Vehicle.VehicleType.choices)
    brand = forms.CharField(label='Marca', max_length=50)
    line = forms.CharField(label='Línea', max_length=50, required=False, help_text='Opcional.')
    model_year = forms.IntegerField(label='Modelo (año)', validators=[validate_model_year])
    accepts_data_processing = forms.BooleanField(
        label='Acepto el tratamiento de mis datos personales',
        error_messages={'required': 'Debes aceptar el tratamiento de datos para agendar la cita.'},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = 'form-check-input'
            elif isinstance(field.widget, forms.Select):
                css_class = 'form-select'
            else:
                css_class = 'form-control'
            field.widget.attrs.setdefault('class', css_class)
        self.fields['email'].widget.attrs['autocomplete'] = 'email'
        self.fields['phone'].widget.attrs.update({'inputmode': 'tel', 'autocomplete': 'tel'})
        self.fields['document_number'].widget.attrs['inputmode'] = 'text'
        self.fields['model_year'].widget.attrs['inputmode'] = 'numeric'

    def clean_document_number(self):
        return Owner.normalize_document_number(self.cleaned_data['document_number'])

    def clean(self):
        cleaned_data = super().clean()
        error = Owner.document_number_error(cleaned_data.get('document_type'), cleaned_data.get('document_number'))
        if error:
            self.add_error('document_number', error)
        return cleaned_data

    def owner_fields(self):
        return [self[name] for name in OWNER_FIELDS]

    def vehicle_fields(self):
        return [self[name] for name in VEHICLE_FIELDS]

    def owner_data(self):
        return {name: self.cleaned_data[name] for name in OWNER_FIELDS}

    def vehicle_data(self):
        return {name: self.cleaned_data[name] for name in VEHICLE_FIELDS}
