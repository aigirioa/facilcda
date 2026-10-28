from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .constants import CDA_ADMIN_GROUP
from .models import CdaConfiguration, InspectionStage


class CdaAdminGroupTests(TestCase):

    def test_group_is_created_by_migration(self):
        self.assertTrue(Group.objects.filter(name=CDA_ADMIN_GROUP).exists())

    def test_user_can_join_group(self):
        user = User.objects.create_user(username='operador', password='clave-segura-123')
        user.groups.add(Group.objects.get(name=CDA_ADMIN_GROUP))

        self.assertTrue(user.groups.filter(name=CDA_ADMIN_GROUP).exists())


class CdaConfigurationTests(TestCase):

    def test_get_creates_the_record_the_first_time(self):
        self.assertFalse(CdaConfiguration.objects.exists())

        configuration = CdaConfiguration.get()

        self.assertEqual(configuration.pk, CdaConfiguration.SINGLETON_ID)
        self.assertEqual(CdaConfiguration.objects.count(), 1)

    def test_get_returns_the_same_record_after(self):
        first = CdaConfiguration.get()
        first.cda_name = 'CDA Medellín Centro'
        first.save()

        second = CdaConfiguration.get()

        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.cda_name, 'CDA Medellín Centro')
        self.assertEqual(CdaConfiguration.objects.count(), 1)

    def test_default_values(self):
        configuration = CdaConfiguration.get()

        self.assertEqual(configuration.slot_duration_minutes, 30)
        self.assertEqual(configuration.slot_capacity, 2)
        self.assertEqual(configuration.max_booking_days, 30)
        self.assertEqual(configuration.polling_interval_seconds, 15)
        self.assertIn('Ley 1581 de 2012', configuration.data_processing_text)

    def test_saving_a_new_instance_does_not_create_a_second_record(self):
        CdaConfiguration.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CdaConfiguration.objects.create(cda_name='Otro CDA')

        self.assertEqual(CdaConfiguration.objects.count(), 1)

    def test_database_rejects_a_second_record(self):
        CdaConfiguration.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CdaConfiguration.objects.bulk_create([CdaConfiguration(id=2)])

    def test_database_rejects_invalid_numbers(self):
        for field, value in [
            ('slot_duration_minutes', 0),
            ('slot_capacity', 0),
            ('max_booking_days', 0),
            ('polling_interval_seconds', 4),
        ]:
            with self.subTest(field=field), self.assertRaises(IntegrityError), transaction.atomic():
                CdaConfiguration.objects.create(**{field: value})

    def test_full_clean_rejects_too_short_polling_interval(self):
        configuration = CdaConfiguration(polling_interval_seconds=2)
        with self.assertRaises(ValidationError) as ctx:
            configuration.full_clean()
        self.assertIn('polling_interval_seconds', ctx.exception.message_dict)


class InspectionStageTests(TestCase):

    def test_migration_loads_the_three_stages_in_order(self):
        stages = list(InspectionStage.objects.values_list('order', 'name', 'is_active'))

        self.assertEqual(stages, [
            (1, 'Vehículo recibido', True),
            (2, 'En inspección', True),
            (3, 'Inspección finalizada', True),
        ])

    def test_stages_have_description_for_the_user(self):
        self.assertFalse(InspectionStage.objects.filter(description='').exists())

    def test_order_is_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            InspectionStage.objects.create(name='Repetida', order=1, description='Otra etapa con orden 1.')

    def test_order_must_be_at_least_one(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            InspectionStage.objects.create(name='Cero', order=0, description='Orden inválido.')


class CdaConfigurationAdminTests(TestCase):

    def setUp(self):
        self.admin_user = User.objects.create_superuser(username='admin', password='clave-segura-123')
        self.client.force_login(self.admin_user)

    def test_changelist_opens_the_single_record(self):
        response = self.client.get(reverse('admin:configuration_cdaconfiguration_changelist'))

        self.assertRedirects(
            response,
            reverse('admin:configuration_cdaconfiguration_change', args=[CdaConfiguration.SINGLETON_ID]),
        )

    def test_cannot_add_when_record_exists(self):
        CdaConfiguration.get()

        response = self.client.get(reverse('admin:configuration_cdaconfiguration_add'))

        self.assertEqual(response.status_code, 403)

    def test_cannot_delete_the_record(self):
        CdaConfiguration.get()

        response = self.client.get(
            reverse('admin:configuration_cdaconfiguration_delete', args=[CdaConfiguration.SINGLETON_ID]),
        )

        self.assertEqual(response.status_code, 403)

    def test_change_form_saves_the_values(self):
        CdaConfiguration.get()
        data = {
            'cda_name': 'CDA Medellín Centro',
            'address': 'Calle 10 # 20-30, Medellín',
            'phone': '6041234567',
            'opening_hours': 'Lunes a sábado 7:00 a 17:00',
            'slot_duration_minutes': 20,
            'slot_capacity': 3,
            'max_booking_days': 15,
            'polling_interval_seconds': 10,
            'data_processing_text': 'Autorizo el tratamiento de mis datos.',
        }

        response = self.client.post(
            reverse('admin:configuration_cdaconfiguration_change', args=[CdaConfiguration.SINGLETON_ID]), data,
        )

        self.assertEqual(response.status_code, 302)
        configuration = CdaConfiguration.get()
        self.assertEqual(configuration.address, 'Calle 10 # 20-30, Medellín')
        self.assertEqual(configuration.slot_capacity, 3)

    def test_stage_list_shows_the_stages(self):
        response = self.client.get(reverse('admin:configuration_inspectionstage_changelist'))

        self.assertContains(response, 'Vehículo recibido')
        self.assertContains(response, 'Inspección finalizada')
