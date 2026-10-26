from django.contrib import admin

from .models import Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['plate', 'vehicle_type', 'brand', 'line', 'model_year', 'owner']
    list_filter = ['vehicle_type']
    search_fields = ['plate', 'brand', 'owner__document_number']
    list_select_related = ['owner']
    autocomplete_fields = ['owner']
    readonly_fields = ['created_at', 'updated_at']
