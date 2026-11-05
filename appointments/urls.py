from django.urls import path

from .views import (
    AppointmentLookupView,
    AvailableTimeSlotListView,
    BookingConfirmationView,
    BookingView,
    MyAppointmentExitView,
    MyAppointmentView,
    TimeSlotBatchCreateView,
    TimeSlotListView,
    TimeSlotToggleActiveView,
)

app_name = 'appointments'

urlpatterns = [
    path('horarios/', AvailableTimeSlotListView.as_view(), name='available_slots'),
    path('agendar/<int:slot_id>/', BookingView.as_view(), name='book'),
    path('agendar/confirmacion/', BookingConfirmationView.as_view(), name='booking_confirmation'),
    path('consultar/', AppointmentLookupView.as_view(), name='lookup'),
    path('mi-cita/', MyAppointmentView.as_view(), name='my_appointment'),
    path('mi-cita/salir/', MyAppointmentExitView.as_view(), name='my_appointment_exit'),
    path('panel/franjas/', TimeSlotListView.as_view(), name='slot_list'),
    path('panel/franjas/crear/', TimeSlotBatchCreateView.as_view(), name='slot_batch_create'),
    path('panel/franjas/<int:pk>/estado/', TimeSlotToggleActiveView.as_view(), name='slot_toggle_active'),
]
