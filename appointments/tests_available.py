import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse

from configuration.models import CdaConfiguration
from customers.models import Owner
from vehicles.models import Vehicle

from .models import Appointment, TimeSlot
from .services import available_time_slots


# Lunes 2 de noviembre de 2026, 10:00 en Bogotá (15:00 UTC).
NOW = datetime.datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo('America/Bogota'))
TODAY = NOW.date()


def make_slot(day_offset=1, hour=8, **kwargs):
    start = datetime.time(hour, 0)
    data = {
        'date': TODAY + datetime.timedelta(days=day_offset),
        'start_time': start,
        'end_time': datetime.time(hour, 30),
        'capacity': 2,
    }
    data.update(kwargs)
    return TimeSlot.objects.create(**data)


def book(slot, plate, turn, status=Appointment.Status.SCHEDULED):
    owner, _ = Owner.objects.get_or_create(
        document_type=Owner.DocumentType.CC, document_number='1020304050',
        defaults={'first_name': 'Laura', 'last_name': 'Restrepo', 'email': 'laura@example.com', 'phone': '3001234567'},
    )
    vehicle = Vehicle.objects.create(
        plate=plate, vehicle_type=Vehicle.VehicleType.LIGHT_PRIVATE, brand='Renault', model_year=2018, owner=owner,
    )
    return Appointment.objects.create(vehicle=vehicle, owner=owner, slot=slot, turn=turn, status=status)


@mock.patch('appointments.services.local_now', return_value=NOW)
class AvailableTimeSlotsTests(TestCase):

    def available(self):
        return list(available_time_slots())

    def test_includes_active_future_slot_with_free_spots(self, _now):
        slot = make_slot()

        self.assertEqual(self.available(), [slot])

    def test_excludes_past_dates(self, _now):
        make_slot(day_offset=-1)

        self.assertEqual(self.available(), [])

    def test_excludes_slots_of_today_that_already_started(self, _now):
        make_slot(day_offset=0, hour=9)
        make_slot(day_offset=0, hour=10)  # Empieza justo ahora.
        later = make_slot(day_offset=0, hour=11)

        self.assertEqual(self.available(), [later])

    def test_excludes_inactive_slots(self, _now):
        make_slot(is_active=False)

        self.assertEqual(self.available(), [])

    def test_excludes_full_slots(self, _now):
        slot = make_slot(capacity=2)
        book(slot, 'ABC123', turn=1)
        book(slot, 'XYZ987', turn=2)

        self.assertEqual(self.available(), [])

    def test_cancelled_appointments_do_not_fill_the_slot(self, _now):
        slot = make_slot(capacity=1)
        book(slot, 'ABC123', turn=1, status=Appointment.Status.CANCELLED)

        self.assertEqual(self.available(), [slot])

    def test_free_count_counts_only_active_appointments(self, _now):
        slot = make_slot(capacity=3)
        book(slot, 'ABC123', turn=1)
        book(slot, 'XYZ987', turn=2, status=Appointment.Status.NO_SHOW)

        self.assertEqual(self.available()[0].free_count, 2)

    def test_limit_of_max_booking_days(self, _now):
        configuration = CdaConfiguration.get()
        configuration.max_booking_days = 10
        configuration.save()
        last_day = make_slot(day_offset=10)
        make_slot(day_offset=11)

        self.assertEqual(self.available(), [last_day])

    def test_ordered_by_date_and_time(self, _now):
        third = make_slot(day_offset=2, hour=7)
        second = make_slot(day_offset=1, hour=9)
        first = make_slot(day_offset=1, hour=8)

        self.assertEqual(self.available(), [first, second, third])

    def test_uses_bogota_time_not_utc(self, _now):
        # A las 10:00 de Bogotá ya son las 15:00 UTC: una franja de las 12:00 sigue disponible.
        noon = make_slot(day_offset=0, hour=12)

        self.assertEqual(self.available(), [noon])


@mock.patch('appointments.services.local_now', return_value=NOW)
class AvailableTimeSlotListViewTests(TestCase):

    def test_is_public(self, _now):
        response = self.client.get(reverse('appointments:available_slots'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'appointments/available_slots.html')
        self.assertTemplateUsed(response, 'layouts/public.html')

    def test_groups_slots_by_date(self, _now):
        make_slot(day_offset=1, hour=8)
        make_slot(day_offset=1, hour=9)
        make_slot(day_offset=2, hour=8)

        response = self.client.get(reverse('appointments:available_slots'))

        self.assertContains(response, 'Martes 3 de Noviembre')
        self.assertContains(response, 'Miércoles 4 de Noviembre')
        self.assertContains(response, 'card-header', count=2)
        self.assertContains(response, '09:00')

    def test_hides_unavailable_slots(self, _now):
        make_slot(hour=8, is_active=False)

        response = self.client.get(reverse('appointments:available_slots'))

        self.assertNotContains(response, '08:00')
        self.assertContains(response, 'no hay horarios disponibles')

    def test_shows_free_spots_and_cda_data(self, _now):
        configuration = CdaConfiguration.get()
        configuration.cda_name = 'CDA Medellín Centro'
        configuration.save()
        make_slot(capacity=2)

        response = self.client.get(reverse('appointments:available_slots'))

        self.assertContains(response, 'CDA Medellín Centro')
        self.assertContains(response, '2 cupos')

    def test_home_links_to_available_slots(self, _now):
        response = self.client.get(reverse('home'))

        self.assertContains(response, reverse('appointments:available_slots'))
