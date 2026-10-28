import datetime

from django import forms

from configuration.models import CdaConfiguration
from facilcda.dates import local_today

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
