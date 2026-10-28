import datetime
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from configuration.constants import CDA_ADMIN_GROUP
from configuration.models import CdaConfiguration
from customers.models import Owner
from facilcda.dates import local_today
from vehicles.models import Vehicle

from .models import Appointment, TimeSlot
from .services import build_slot_times, create_time_slots


PASSWORD = 'clave-segura-123'
MONDAY_TO_SATURDAY = [0, 1, 2, 3, 4, 5]


def next_monday():
    day = local_today() + datetime.timedelta(days=7)
    return day + datetime.timedelta(days=(7 - day.weekday()) % 7)


def make_cda_admin(username='operador'):
    user = User.objects.create_user(username=username, password=PASSWORD)
    user.groups.add(Group.objects.get(name=CDA_ADMIN_GROUP))
    return user


class BuildSlotTimesTests(TestCase):

    def test_splits_the_schedule_by_interval(self):
        times = build_slot_times(datetime.time(7, 0), datetime.time(8, 30), 30)

        self.assertEqual(times, [
            (datetime.time(7, 0), datetime.time(7, 30)),
            (datetime.time(7, 30), datetime.time(8, 0)),
            (datetime.time(8, 0), datetime.time(8, 30)),
        ])

    def test_incomplete_last_slot_is_not_created(self):
        times = build_slot_times(datetime.time(7, 0), datetime.time(8, 45), 30)

        self.assertEqual(len(times), 3)
        self.assertEqual(times[-1][1], datetime.time(8, 30))


class CreateTimeSlotsTests(TestCase):

    def setUp(self):
        self.monday = next_monday()

    def create(self, **kwargs):
        data = {
            'start_date': self.monday,
            'end_date': self.monday + datetime.timedelta(days=1),
            'start_time': datetime.time(7, 0),
            'end_time': datetime.time(9, 0),
            'interval_minutes': 30,
            'capacity': 2,
            'weekdays': MONDAY_TO_SATURDAY,
        }
        data.update(kwargs)
        return create_time_slots(**data)

    def test_creates_slots_for_each_day(self):
        created, skipped = self.create()

        self.assertEqual((created, skipped), (8, 0))
        self.assertEqual(TimeSlot.objects.filter(date=self.monday).count(), 4)
        self.assertFalse(TimeSlot.objects.exclude(capacity=2).exists())

    def test_does_not_duplicate_existing_slots(self):
        self.create()

        created, skipped = self.create()

        self.assertEqual((created, skipped), (0, 8))
        self.assertEqual(TimeSlot.objects.count(), 8)

    def test_partially_existing_batch_creates_only_the_missing_slots(self):
        TimeSlot.objects.create(date=self.monday, start_time=datetime.time(7, 0), end_time=datetime.time(7, 30))

        created, skipped = self.create()

        self.assertEqual((created, skipped), (7, 1))

    def test_only_selected_weekdays(self):
        created, _ = self.create(end_date=self.monday + datetime.timedelta(days=6), weekdays=[0, 2])

        self.assertEqual(created, 8)
        self.assertEqual(
            {slot.date.weekday() for slot in TimeSlot.objects.all()},
            {0, 2},
        )


class PanelAccessTests(TestCase):

    def urls(self):
        slot = TimeSlot.objects.create(
            date=next_monday(), start_time=datetime.time(7, 0), end_time=datetime.time(7, 30),
        )
        return [
            ('get', reverse('appointments:slot_list')),
            ('get', reverse('appointments:slot_batch_create')),
            ('post', reverse('appointments:slot_toggle_active', args=[slot.pk])),
        ]

    def test_anonymous_user_is_sent_to_login(self):
        for method, url in self.urls():
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertRedirects(response, f"{reverse('users:login')}?next={url}", fetch_redirect_response=False)

    def test_user_without_group_is_forbidden(self):
        self.client.force_login(User.objects.create_user(username='otro', password=PASSWORD))
        for method, url in self.urls():
            with self.subTest(url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403)

    def test_cda_admin_can_open_the_panel(self):
        self.client.force_login(make_cda_admin())

        self.assertEqual(self.client.get(reverse('appointments:slot_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('appointments:slot_batch_create')).status_code, 200)

    def test_superuser_can_open_the_panel(self):
        self.client.force_login(User.objects.create_superuser(username='admin', password=PASSWORD))

        self.assertEqual(self.client.get(reverse('appointments:slot_list')).status_code, 200)


class TimeSlotBatchCreateViewTests(TestCase):

    def setUp(self):
        self.client.force_login(make_cda_admin())
        self.url = reverse('appointments:slot_batch_create')
        self.monday = next_monday()

    def post_data(self, **kwargs):
        data = {
            'start_date': self.monday.isoformat(),
            'end_date': (self.monday + datetime.timedelta(days=1)).isoformat(),
            'start_time': '07:00',
            'end_time': '09:00',
            'interval_minutes': 30,
            'capacity': 3,
            'weekdays': MONDAY_TO_SATURDAY,
        }
        data.update(kwargs)
        return data

    def test_form_uses_configuration_defaults(self):
        configuration = CdaConfiguration.get()
        configuration.slot_duration_minutes = 20
        configuration.slot_capacity = 4
        configuration.save()

        form = self.client.get(self.url).context['form']

        self.assertEqual(form['interval_minutes'].initial, 20)
        self.assertEqual(form['capacity'].initial, 4)

    def test_creates_the_batch_and_redirects_to_the_first_day(self):
        response = self.client.post(self.url, self.post_data(), follow=True)

        self.assertRedirects(response, f"{reverse('appointments:slot_list')}?fecha={self.monday:%Y-%m-%d}")
        self.assertEqual(TimeSlot.objects.count(), 8)
        self.assertFalse(TimeSlot.objects.exclude(capacity=3).exists())
        self.assertContains(response, 'Se crearon 8 franjas.')

    def test_repeating_the_batch_does_not_duplicate(self):
        self.client.post(self.url, self.post_data())

        response = self.client.post(self.url, self.post_data(), follow=True)

        self.assertEqual(TimeSlot.objects.count(), 8)
        self.assertContains(response, 'No se creó ninguna franja nueva.')
        self.assertContains(response, 'Se omitieron 8 franjas porque ya existían.')

    def test_end_time_must_be_after_start_time(self):
        for end_time in ['07:00', '06:00']:
            with self.subTest(end_time=end_time):
                response = self.client.post(self.url, self.post_data(end_time=end_time))

                self.assertFormError(response.context['form'], 'end_time', 'La hora de fin debe ser mayor que la hora de inicio.')
        self.assertFalse(TimeSlot.objects.exists())

    def test_end_date_cannot_be_before_start_date(self):
        response = self.client.post(self.url, self.post_data(end_date=(self.monday - datetime.timedelta(days=1)).isoformat()))

        self.assertFormError(response.context['form'], 'end_date', 'La fecha final debe ser igual o posterior a la inicial.')

    def test_past_dates_are_rejected(self):
        yesterday = local_today() - datetime.timedelta(days=1)

        response = self.client.post(self.url, self.post_data(start_date=yesterday.isoformat()))

        self.assertFormError(response.context['form'], 'start_date', 'No se pueden crear franjas en fechas pasadas.')

    def test_range_is_limited(self):
        response = self.client.post(self.url, self.post_data(end_date=(self.monday + datetime.timedelta(days=92)).isoformat()))

        self.assertFormError(response.context['form'], 'end_date', 'El rango no puede superar 92 días.')

    def test_interval_longer_than_schedule_is_rejected(self):
        response = self.client.post(self.url, self.post_data(interval_minutes=180))

        self.assertFormError(response.context['form'], 'interval_minutes', 'La duración es mayor que el horario: no cabe ninguna franja.')

    def test_at_least_one_weekday_is_required(self):
        response = self.client.post(self.url, self.post_data(weekdays=[]))

        self.assertIn('weekdays', response.context['form'].errors)

    def test_today_uses_bogota_date(self):
        # 2026-11-03 02:00 UTC todavía es 2 de noviembre en Bogotá.
        bogota_today = datetime.date(2026, 11, 2)
        with mock.patch('appointments.forms.local_today', return_value=bogota_today):
            response = self.client.post(self.url, self.post_data(
                start_date=bogota_today.isoformat(), end_date=bogota_today.isoformat(), weekdays=list(range(7)),
            ))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(TimeSlot.objects.filter(date=bogota_today).exists())


class TimeSlotListViewTests(TestCase):

    def setUp(self):
        self.client.force_login(make_cda_admin())
        self.day = next_monday()
        self.slot = TimeSlot.objects.create(
            date=self.day, start_time=datetime.time(8, 0), end_time=datetime.time(8, 30), capacity=2,
        )
        TimeSlot.objects.create(date=self.day, start_time=datetime.time(7, 0), end_time=datetime.time(7, 30))
        TimeSlot.objects.create(
            date=self.day + datetime.timedelta(days=1), start_time=datetime.time(7, 0), end_time=datetime.time(7, 30),
        )

    def get(self, day):
        return self.client.get(reverse('appointments:slot_list'), {'fecha': day.isoformat()})

    def test_shows_only_the_slots_of_the_selected_date_in_order(self):
        response = self.get(self.day)

        self.assertEqual(
            [slot.start_time for slot in response.context['slots']],
            [datetime.time(7, 0), datetime.time(8, 0)],
        )

    def test_without_date_shows_today(self):
        response = self.client.get(reverse('appointments:slot_list'))

        self.assertEqual(response.context['selected_date'], local_today())

    def test_counts_only_active_appointments(self):
        owner = Owner.objects.create(
            document_type=Owner.DocumentType.CC, document_number='1020304050',
            first_name='Laura', last_name='Restrepo', email='laura@example.com', phone='3001234567',
        )
        first = Vehicle.objects.create(
            plate='ABC123', vehicle_type=Vehicle.VehicleType.LIGHT_PRIVATE, brand='Renault', model_year=2018, owner=owner,
        )
        second = Vehicle.objects.create(
            plate='XYZ987', vehicle_type=Vehicle.VehicleType.LIGHT_PRIVATE, brand='Mazda', model_year=2020, owner=owner,
        )
        Appointment.objects.create(vehicle=first, owner=owner, slot=self.slot, turn=1)
        Appointment.objects.create(vehicle=second, owner=owner, slot=self.slot, turn=2, status=Appointment.Status.CANCELLED)

        response = self.get(self.day)
        slot = next(slot for slot in response.context['slots'] if slot.pk == self.slot.pk)

        self.assertEqual(slot.active_count, 1)
        self.assertEqual(slot.free_count, 1)
        self.assertContains(response, '1 ocupado · 1 libre')


class TimeSlotToggleActiveViewTests(TestCase):

    def setUp(self):
        self.client.force_login(make_cda_admin())
        self.slot = TimeSlot.objects.create(
            date=next_monday(), start_time=datetime.time(8, 0), end_time=datetime.time(8, 30),
        )
        self.url = reverse('appointments:slot_toggle_active', args=[self.slot.pk])

    def test_deactivates_and_activates(self):
        response = self.client.post(self.url)

        self.assertRedirects(response, f"{reverse('appointments:slot_list')}?fecha={self.slot.date:%Y-%m-%d}")
        self.slot.refresh_from_db()
        self.assertFalse(self.slot.is_active)

        self.client.post(self.url)
        self.slot.refresh_from_db()
        self.assertTrue(self.slot.is_active)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.slot.refresh_from_db()
        self.assertTrue(self.slot.is_active)


class CdaAdminGroupPermissionsTests(TestCase):

    def test_group_can_manage_time_slots(self):
        user = make_cda_admin()

        self.assertTrue(user.has_perm('appointments.view_timeslot'))
        self.assertTrue(user.has_perm('appointments.add_timeslot'))
        self.assertTrue(user.has_perm('appointments.change_timeslot'))
        self.assertFalse(user.has_perm('appointments.delete_timeslot'))
