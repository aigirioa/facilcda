from django.urls import path

from .views import AvailableTimeSlotListView, TimeSlotBatchCreateView, TimeSlotListView, TimeSlotToggleActiveView

app_name = 'appointments'

urlpatterns = [
    path('horarios/', AvailableTimeSlotListView.as_view(), name='available_slots'),
    path('panel/franjas/', TimeSlotListView.as_view(), name='slot_list'),
    path('panel/franjas/crear/', TimeSlotBatchCreateView.as_view(), name='slot_batch_create'),
    path('panel/franjas/<int:pk>/estado/', TimeSlotToggleActiveView.as_view(), name='slot_toggle_active'),
]
