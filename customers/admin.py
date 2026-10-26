from django.contrib import admin

from .models import Owner


@admin.register(Owner)
class OwnerAdmin(admin.ModelAdmin):
    list_display = ['document_type', 'document_number', 'first_name', 'last_name', 'phone', 'accepts_data_processing']
    list_filter = ['document_type', 'accepts_data_processing']
    search_fields = ['document_number', 'first_name', 'last_name', 'email']
    readonly_fields = ['data_processing_accepted_at', 'created_at', 'updated_at']
