import datetime

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from configuration.models import CdaConfiguration
from facilcda.dates import local_today
from users.mixins import CdaAdminRequiredMixin

from .forms import BookingForm, TimeSlotBatchForm
from .models import Appointment, TimeSlot
from .services import (
    SLOT_UNAVAILABLE_MESSAGE,
    BookingError,
    SlotUnavailableError,
    available_time_slots,
    book_appointment,
    create_time_slots,
)


# Cita recién agendada que puede ver la sesión en la página de confirmación.
CONFIRMATION_SESSION_KEY = 'confirmed_appointment'
CONFIRMATION_MAX_AGE = datetime.timedelta(minutes=30)


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

        self.request.session[CONFIRMATION_SESSION_KEY] = {
            'appointment_id': appointment.pk,
            'booked_at': timezone.now().timestamp(),
        }
        return redirect('appointments:booking_confirmation')


class BookingConfirmationView(TemplateView):
    """Vista pública: confirmación de la cita recién agendada.

    La URL no lleva el id ni el código de la cita: se toma de la sesión de quien agendó, así nadie
    ve una cita ajena cambiando la dirección. El acceso vence a los CONFIRMATION_MAX_AGE.
    """

    template_name = 'appointments/booking_confirmation.html'

    def get(self, request, *args, **kwargs):
        self.appointment = self.get_appointment()
        if self.appointment is None:
            return redirect('home')
        return super().get(request, *args, **kwargs)

    def get_appointment(self):
        data = self.request.session.get(CONFIRMATION_SESSION_KEY)
        if not data:
            return None
        if timezone.now().timestamp() - data['booked_at'] > CONFIRMATION_MAX_AGE.total_seconds():
            del self.request.session[CONFIRMATION_SESSION_KEY]
            return None
        return (
            Appointment.objects
            .select_related('slot', 'vehicle', 'owner')
            .filter(pk=data['appointment_id'])
            .first()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['appointment'] = self.appointment
        context['configuration'] = CdaConfiguration.get()
        return context


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
