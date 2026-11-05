import datetime

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from configuration.models import CdaConfiguration
from facilcda.dates import local_today
from users.mixins import CdaAdminRequiredMixin

from .access import (
    CONFIRMATION_SESSION_KEY,
    MY_APPOINTMENT_SESSION_KEY,
    grant_access,
    granted_appointment_id,
    revoke_access,
)
from .forms import AppointmentLookupForm, BookingForm, TimeSlotBatchForm
from .models import Appointment, TimeSlot
from .services import (
    SLOT_UNAVAILABLE_MESSAGE,
    BookingError,
    SlotUnavailableError,
    available_time_slots,
    book_appointment,
    create_time_slots,
    find_appointment,
)
from .throttling import client_ip, is_lookup_blocked, register_lookup_failure


LOOKUP_FAILED_MESSAGE = 'No encontramos una cita con esos datos. Revisa la placa y el número de documento.'

# Color del estado de la cita en "Mi cita" (clases de Bootstrap).
STATUS_BADGES = {
    Appointment.Status.SCHEDULED: 'text-bg-primary',
    Appointment.Status.RECEIVED: 'text-bg-info',
    Appointment.Status.IN_PROGRESS: 'text-bg-warning',
    Appointment.Status.FINISHED: 'text-bg-success',
    Appointment.Status.CANCELLED: 'text-bg-secondary',
    Appointment.Status.NO_SHOW: 'text-bg-danger',
}


def slot_list_url(date):
    return f"{reverse('appointments:slot_list')}?fecha={date:%Y-%m-%d}"


class AvailableTimeSlotListView(ListView):
    """Vista pública: franjas disponibles para agendar, agrupadas por fecha en la plantilla."""

    template_name = 'appointments/available_slots.html'
    context_object_name = 'slots'

    def get_queryset(self):
        return available_time_slots()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['configuration'] = CdaConfiguration.get()
        return context


class BookingView(FormView):
    """Vista pública: datos del propietario y del vehículo para agendar en la franja elegida."""

    template_name = 'appointments/booking_form.html'
    form_class = BookingForm

    def dispatch(self, request, *args, **kwargs):
        self.slot = available_time_slots().filter(pk=kwargs['slot_id']).first()
        if self.slot is None:
            messages.warning(request, SLOT_UNAVAILABLE_MESSAGE)
            return redirect('appointments:available_slots')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['slot'] = self.slot
        context['configuration'] = CdaConfiguration.get()
        return context

    def form_valid(self, form):
        try:
            appointment = book_appointment(self.slot.pk, form.owner_data(), form.vehicle_data())
        except SlotUnavailableError as error:
            messages.warning(self.request, str(error))
            return redirect('appointments:available_slots')
        except BookingError as error:
            form.add_error(None, str(error))
            return self.form_invalid(form)

        grant_access(self.request.session, CONFIRMATION_SESSION_KEY, appointment)
        return redirect('appointments:booking_confirmation')


class SessionAppointmentView(TemplateView):
    """Muestra la cita guardada en la sesión (ver access.py); sin acceso vigente redirige.

    La URL no lleva el id ni el código de la cita, así nadie ve una cita ajena cambiando la dirección.
    """

    session_key = None
    no_access_url = 'home'

    def get(self, request, *args, **kwargs):
        appointment_id = granted_appointment_id(request.session, self.session_key)
        self.appointment = (
            Appointment.objects
            .select_related('slot', 'vehicle', 'owner')
            .filter(pk=appointment_id)
            .first()
        ) if appointment_id else None
        if self.appointment is None:
            return self.no_access()
        return super().get(request, *args, **kwargs)

    def no_access(self):
        return redirect(self.no_access_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['appointment'] = self.appointment
        context['configuration'] = CdaConfiguration.get()
        return context


class BookingConfirmationView(SessionAppointmentView):
    """Vista pública: confirmación de la cita recién agendada, solo para la sesión que agendó."""

    template_name = 'appointments/booking_confirmation.html'
    session_key = CONFIRMATION_SESSION_KEY


class AppointmentLookupView(FormView):
    """Vista pública: consulta de la cita con placa y número de documento (HU-05).

    Todos los fallos muestran el mismo mensaje y cuentan para el límite de intentos por IP.
    """

    template_name = 'appointments/lookup_form.html'
    form_class = AppointmentLookupForm

    def post(self, request, *args, **kwargs):
        if is_lookup_blocked(client_ip(request)):
            return self.render_to_response(self.get_context_data(form=self.get_form(), blocked=True))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        appointment = find_appointment(form.cleaned_data['plate'], form.cleaned_data['document_number'])
        if appointment is None:
            register_lookup_failure(client_ip(self.request))
            form.add_error(None, LOOKUP_FAILED_MESSAGE)
            return self.form_invalid(form)

        grant_access(self.request.session, MY_APPOINTMENT_SESSION_KEY, appointment)
        return redirect('appointments:my_appointment')


class MyAppointmentView(SessionAppointmentView):
    """Vista pública "Mi cita": la cita encontrada con placa y documento, por 30 minutos."""

    template_name = 'appointments/my_appointment.html'
    session_key = MY_APPOINTMENT_SESSION_KEY

    def no_access(self):
        messages.info(self.request, 'Consulta tu cita con la placa del vehículo y tu número de documento.')
        return redirect('appointments:lookup')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_badge'] = STATUS_BADGES[self.appointment.status]
        return context


class MyAppointmentExitView(View):
    """Cierra la consulta de "Mi cita" en este dispositivo."""

    http_method_names = ['post']

    def post(self, request):
        revoke_access(request.session, MY_APPOINTMENT_SESSION_KEY)
        messages.success(request, 'Cerraste la consulta de tu cita.')
        return redirect('home')


class TimeSlotListView(CdaAdminRequiredMixin, ListView):
    template_name = 'appointments/panel/slot_list.html'
    context_object_name = 'slots'

    def get_selected_date(self):
        return parse_date(self.request.GET.get('fecha') or '') or local_today()

    def get_queryset(self):
        self.selected_date = self.get_selected_date()
        return (
            TimeSlot.objects
            .filter(date=self.selected_date)
            .annotate(active_count=Count(
                'appointments', filter=Q(appointments__status__in=Appointment.ACTIVE_STATUSES),
            ))
            .order_by('start_time')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for slot in context['slots']:
            slot.free_count = max(slot.capacity - slot.active_count, 0)
        context['selected_date'] = self.selected_date
        context['previous_date'] = self.selected_date - datetime.timedelta(days=1)
        context['next_date'] = self.selected_date + datetime.timedelta(days=1)
        context['today'] = local_today()
        return context


class TimeSlotBatchCreateView(CdaAdminRequiredMixin, FormView):
    template_name = 'appointments/panel/slot_batch_form.html'
    form_class = TimeSlotBatchForm

    def form_valid(self, form):
        data = form.cleaned_data
        created, skipped = create_time_slots(
            start_date=data['start_date'],
            end_date=data['end_date'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            interval_minutes=data['interval_minutes'],
            capacity=data['capacity'],
            weekdays=data['weekdays'],
        )
        if created:
            messages.success(self.request, f'Se crearon {created} franjas.')
        else:
            messages.warning(self.request, 'No se creó ninguna franja nueva.')
        if skipped:
            messages.info(self.request, f'Se omitieron {skipped} franjas porque ya existían.')
        return redirect(slot_list_url(data['start_date']))


class TimeSlotToggleActiveView(CdaAdminRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        slot = get_object_or_404(TimeSlot, pk=pk)
        slot.is_active = not slot.is_active
        slot.save(update_fields=['is_active'])

        if slot.is_active:
            messages.success(request, f'La franja {slot.start_time:%H:%M} quedó activa.')
        else:
            messages.success(request, f'La franja {slot.start_time:%H:%M} quedó desactivada y no se ofrecerá para agendar.')
            if slot.occupied_spots:
                messages.warning(request, 'La franja tiene citas activas; esas citas se mantienen.')
        return redirect(slot_list_url(slot.date))
