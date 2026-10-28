from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import CdaConfiguration, InspectionStage


@admin.register(CdaConfiguration)
class CdaConfigurationAdmin(admin.ModelAdmin):
    fieldsets = [
        ('Datos del CDA', {'fields': ['cda_name', 'address', 'phone', 'opening_hours']}),
        ('Agendamiento', {'fields': ['slot_duration_minutes', 'slot_capacity', 'max_booking_days']}),
        ('Consulta del estado', {'fields': ['polling_interval_seconds']}),
        ('Tratamiento de datos (Ley 1581 de 2012)', {'fields': ['data_processing_text']}),
        (None, {'fields': ['updated_at']}),
    ]
    readonly_fields = ['updated_at']

    def has_add_permission(self, request):
        return not CdaConfiguration.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Solo hay un registro: se abre directamente su formulario.
        configuration = CdaConfiguration.get()
        return redirect(reverse('admin:configuration_cdaconfiguration_change', args=[configuration.pk]))


@admin.register(InspectionStage)
class InspectionStageAdmin(admin.ModelAdmin):
    list_display = ['order', 'name', 'description', 'is_active']
    list_display_links = ['name']
    list_filter = ['is_active']
