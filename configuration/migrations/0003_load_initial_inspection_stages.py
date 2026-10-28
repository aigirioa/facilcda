from django.db import migrations


# Nombres por confirmar con un CDA real (ver sección 2.1 del plan).
INITIAL_STAGES = [
    (1, 'Vehículo recibido', 'Tu vehículo fue recibido en el CDA y está en espera de la inspección.'),
    (2, 'En inspección', 'Tu vehículo está en la línea de inspección técnico-mecánica y de emisiones.'),
    (3, 'Inspección finalizada', 'La inspección terminó. Pronto verás el resultado.'),
]


def load_stages(apps, schema_editor):
    InspectionStage = apps.get_model('configuration', 'InspectionStage')
    for order, name, description in INITIAL_STAGES:
        InspectionStage.objects.get_or_create(
            order=order,
            defaults={'name': name, 'description': description, 'is_active': True},
        )


def remove_stages(apps, schema_editor):
    InspectionStage = apps.get_model('configuration', 'InspectionStage')
    InspectionStage.objects.filter(order__in=[order for order, _, _ in INITIAL_STAGES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('configuration', '0002_cdaconfiguration_inspectionstage'),
    ]

    operations = [
        migrations.RunPython(load_stages, remove_stages),
    ]
