from django.contrib.auth.management import create_permissions
from django.db import migrations


CDA_ADMIN_GROUP = 'Administrador CDA'
PERMISSIONS = ['view_timeslot', 'add_timeslot', 'change_timeslot']


def grant_permissions(apps, schema_editor):
    # En una base nueva los permisos se crean después de migrar; se crean aquí para poder asignarlos.
    app_config = apps.get_app_config('appointments')
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    group, _ = Group.objects.get_or_create(name=CDA_ADMIN_GROUP)
    group.permissions.add(*Permission.objects.filter(
        content_type__app_label='appointments', codename__in=PERMISSIONS,
    ))


def revoke_permissions(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    group = Group.objects.filter(name=CDA_ADMIN_GROUP).first()
    if group:
        group.permissions.remove(*Permission.objects.filter(
            content_type__app_label='appointments', codename__in=PERMISSIONS,
        ))


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0001_initial'),
        ('configuration', '0001_create_cda_admin_group'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(grant_permissions, revoke_permissions),
    ]
