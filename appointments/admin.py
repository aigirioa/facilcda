from django.contrib import admin

from configuration.models import CdaConfiguration

from .models import Appointment, TimeSlot


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ['date', 'start_time', 'end_time', 'capacity', 'is_active']
    list_filter = ['is_active', 'date']
    date_hierarchy = 'date'

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault('capacity', CdaConfiguration.get().slot_capacity)
        return initial


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ['code', 'vehicle', 'owner', 'slot', 'turn', 'status']
    list_filter = ['status', 'slot__date']
    search_fields = ['code', 'vehicle__plate', 'owner__document_number']
    list_select_related = ['vehicle', 'owner', 'slot']
    autocomplete_fields = ['vehicle', 'owner']
    readonly_fields = ['code', 'created_at', 'updated_at']
