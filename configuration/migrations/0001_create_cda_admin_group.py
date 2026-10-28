from django.db import migrations


# Copiado aquí a propósito: las migraciones no deben depender del código actual de la app.
CDA_ADMIN_GROUP = 'Administrador CDA'


def create_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name=CDA_ADMIN_GROUP)


def delete_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name=CDA_ADMIN_GROUP).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_group, delete_group),
    ]
