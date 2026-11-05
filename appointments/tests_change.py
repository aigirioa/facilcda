import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from facilcda.dates import local_today

from .models import Appointment, TimeSlot
from .services import (
    NOT_CHANGEABLE_MESSAGE,
    SAME_SLOT_MESSAGE,
    SLOT_FULL_MESSAGE,
    SLOT_UNAVAILABLE_MESSAGE,
    AppointmentNotChangeableError,
    SlotUnavailableError,
    book_appointment,
    cancel_appointment,
    reschedule_appointment,
)
from .tests_booking import make_slot, owner_data, vehicle_data


BOGOTA = ZoneInfo('America/Bogota')


def move_slot_to_yesterday(appointment):
    """La franja ya empezó. Se mueve después de agendar porque no se puede agendar en el pasado."""
    TimeSlot.objects.filter(pk=appointment.slot_id).update(date=local_today() - datetime.timedelta(days=1))
    appointment.refresh_from_db()


def set_status(appointment, status):
    appointment.status = status
    appointment.save()


class CanBeChangedTests(TestCase):

    def setUp(self):
        self.appointment = book_appointment(make_slot().pk, owner_data(), vehicle_data())

    def at(self, minutes_from_start):
        start = datetime.datetime.combine(self.appointment.slot.date, self.appointment.slot.start_time, BOGOTA)
        return mock.patch('appointments.models.local_now', return_value=start + datetime.timedelta(minutes=minutes_from_start))

    def test_scheduled_appointment_before_its_slot_can_be_changed(self):
        with self.at(-1):
            self.assertTrue(self.appointment.can_be_changed)

    def test_cannot_be_changed_once_the_slot_starts(self):
        with self.at(0):
            self.assertFalse(self.appointment.can_be_changed)
        with self.at(10):
            self.assertFalse(self.appointment.can_be_changed)

    def test_only_scheduled_appointments_can_be_changed(self):
        for status in [Appointment.Status.RECEIVED, Appointment.Status.IN_PROGRESS, Appointment.Status.FINISHED,
                       Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW]:
            with self.subTest(status=status):
                self.appointment.status = status
                self.assertFalse(self.appointment.can_be_changed)


class RescheduleAppointmentTests(TestCase):

    def setUp(self):
        self.old_slot = make_slot()
        self.appointment = book_appointment(self.old_slot.pk, owner_data(), vehicle_data())
        self.new_slot = make_slot(day_offset=2, hour=9)

    def test_moves_the_appointment_and_frees_the_old_turn(self):
        rescheduled = reschedule_appointment(self.appointment.pk, self.new_slot.pk)

        rescheduled.refresh_from_db()
        self.assertEqual(rescheduled.slot, self.new_slot)
        self.assertEqual(rescheduled.turn, 1)
        self.assertEqual(rescheduled.code, self.appointment.code)
        self.assertEqual(rescheduled.status, Appointment.Status.SCHEDULED)
        self.assertEqual(self.old_slot.available_spots, 2)
        self.assertEqual(self.new_slot.available_spots, 1)

    def test_takes_the_first_free_turn_of_the_new_slot(self):
        book_appointment(self.new_slot.pk, owner_data(document_number='55667788'), vehicle_data(plate='XYZ987'))

        rescheduled = reschedule_appointment(self.appointment.pk, self.new_slot.pk)

        self.assertEqual(rescheduled.turn, 2)

    def test_freed_turn_can_be_booked_by_someone_else(self):
        reschedule_appointment(self.appointment.pk, self.new_slot.pk)

        other = book_appointment(self.old_slot.pk, owner_data(document_number='55667788'), vehicle_data(plate='XYZ987'))

        self.assertEqual(other.turn, 1)

    def test_same_slot_is_rejected(self):
        with self.assertRaisesMessage(SlotUnavailableError, SAME_SLOT_MESSAGE):
            reschedule_appointment(self.appointment.pk, self.old_slot.pk)

    def test_full_slot_is_rejected_and_the_appointment_stays(self):
        full_slot = make_slot(day_offset=3, capacity=1)
        book_appointment(full_slot.pk, owner_data(document_number='55667788'), vehicle_data(plate='XYZ987'))

        with self.assertRaisesMessage(SlotUnavailableError, SLOT_FULL_MESSAGE):
            reschedule_appointment(self.appointment.pk, full_slot.pk)

        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.slot, self.old_slot)
        self.assertEqual(self.appointment.turn, 1)

    def test_inactive_past_or_missing_slot_is_rejected(self):
        inactive = make_slot(day_offset=3, is_active=False)
        past = make_slot(day_offset=-1)
        for slot_id in [inactive.pk, past.pk, None, 999999]:
            with self.subTest(slot_id=slot_id):
                with self.assertRaisesMessage(SlotUnavailableError, SLOT_UNAVAILABLE_MESSAGE):
                    reschedule_appointment(self.appointment.pk, slot_id)

    def test_rejected_if_the_appointment_is_not_scheduled(self):
        set_status(self.appointment, Appointment.Status.RECEIVED)

        with self.assertRaisesMessage(AppointmentNotChangeableError, NOT_CHANGEABLE_MESSAGE):
            reschedule_appointment(self.appointment.pk, self.new_slot.pk)

    def test_rejected_if_the_slot_already_started(self):
        move_slot_to_yesterday(self.appointment)

        with self.assertRaises(AppointmentNotChangeableError):
            reschedule_appointment(self.appointment.pk, self.new_slot.pk)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.slot, self.old_slot)


class CancelAppointmentTests(TestCase):

    def setUp(self):
        self.slot = make_slot(capacity=1)
        self.appointment = book_appointment(self.slot.pk, owner_data(), vehicle_data())

    def test_cancels_and_frees_the_turn(self):
        cancelled = cancel_appointment(self.appointment.pk)

        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, Appointment.Status.CANCELLED)
        self.assertIsNotNone(cancelled.cancelled_at)
        self.assertEqual(self.slot.available_spots, 1)
        other = book_appointment(self.slot.pk, owner_data(document_number='55667788'), vehicle_data(plate='XYZ987'))
        self.assertEqual(other.turn, 1)

    def test_the_plate_can_book_again_after_cancelling(self):
        cancel_appointment(self.appointment.pk)

        new_appointment = book_appointment(make_slot(day_offset=2).pk, owner_data(), vehicle_data())

        self.assertTrue(new_appointment.is_active)

    def test_rejected_if_the_appointment_is_not_scheduled(self):
        for status in [Appointment.Status.IN_PROGRESS, Appointment.Status.CANCELLED]:
            with self.subTest(status=status):
                set_status(self.appointment, status)
                with self.assertRaises(AppointmentNotChangeableError):
                    cancel_appointment(self.appointment.pk)

    def test_rejected_if_the_slot_already_started(self):
        move_slot_to_yesterday(self.appointment)

        with self.assertRaises(AppointmentNotChangeableError):
            cancel_appointment(self.appointment.pk)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.SCHEDULED)
        self.assertIsNone(self.appointment.cancelled_at)


class ChangeViewsTests(TestCase):

    def setUp(self):
        cache.clear()
        self.old_slot = make_slot()
        self.appointment = book_appointment(self.old_slot.pk, owner_data(), vehicle_data())
        self.new_slot = make_slot(day_offset=2, hour=9)
        self.my_appointment_url = reverse('appointments:my_appointment')
        self.reschedule_url = reverse('appointments:reschedule_appointment')
        self.cancel_url = reverse('appointments:cancel_appointment')

    def lookup(self):
        self.client.post(reverse('appointments:lookup'), {'plate': 'ABC123', 'document_number': '1020304050'})

    def test_my_appointment_shows_the_buttons_while_it_can_be_changed(self):
        self.lookup()

        response = self.client.get(self.my_appointment_url)

        self.assertContains(response, f'href="{self.reschedule_url}"')
        self.assertContains(response, f'href="{self.cancel_url}"')

    def test_my_appointment_hides_the_buttons_once_the_slot_started(self):
        move_slot_to_yesterday(self.appointment)
        self.lookup()

        response = self.client.get(self.my_appointment_url)

        self.assertNotContains(response, f'href="{self.reschedule_url}"')
        self.assertNotContains(response, f'href="{self.cancel_url}"')
        self.assertContains(response, 'ya no se puede reprogramar ni cancelar')

    def test_reschedule_page_lists_other_available_slots(self):
        self.lookup()

        response = self.client.get(self.reschedule_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['slots']), [self.new_slot])

    def test_reschedule_moves_the_appointment(self):
        self.lookup()

        response = self.client.post(self.reschedule_url, {'slot': self.new_slot.pk}, follow=True)

        self.assertRedirects(response, self.my_appointment_url)
        self.assertContains(response, 'Reprogramamos tu cita.')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.slot, self.new_slot)

    def test_reschedule_to_an_unavailable_slot_shows_a_message(self):
        self.new_slot.is_active = False
        self.new_slot.save()
        self.lookup()

        response = self.client.post(self.reschedule_url, {'slot': self.new_slot.pk}, follow=True)

        self.assertRedirects(response, self.reschedule_url)
        self.assertContains(response, SLOT_UNAVAILABLE_MESSAGE)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.slot, self.old_slot)

    def test_reschedule_with_an_invalid_value_shows_a_message(self):
        self.lookup()

        response = self.client.post(self.reschedule_url, {'slot': 'abc'}, follow=True)

        self.assertRedirects(response, self.reschedule_url)
        self.assertContains(response, SLOT_UNAVAILABLE_MESSAGE)

    def test_cancel_page_asks_for_confirmation_without_cancelling(self):
        self.lookup()

        response = self.client.get(self.cancel_url)

        self.assertContains(response, '¿Seguro que quieres cancelar esta cita?')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.SCHEDULED)

    def test_cancel_cancels_the_appointment(self):
        self.lookup()

        response = self.client.post(self.cancel_url, follow=True)

        self.assertRedirects(response, self.my_appointment_url)
        self.assertContains(response, 'Cancelaste tu cita.')
        self.assertContains(response, 'Cancelada')
        self.assertContains(response, 'Agendar una nueva cita')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.CANCELLED)

    def test_without_lookup_redirects_to_the_lookup_form(self):
        for url in [self.reschedule_url, self.cancel_url]:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse('appointments:lookup'))
                self.assertRedirects(self.client.post(url, {'slot': self.new_slot.pk}), reverse('appointments:lookup'))
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.SCHEDULED)
        self.assertEqual(self.appointment.slot, self.old_slot)

    def test_not_changeable_appointment_returns_to_my_appointment(self):
        set_status(self.appointment, Appointment.Status.RECEIVED)
        self.lookup()

        for url in [self.reschedule_url, self.cancel_url]:
            with self.subTest(url=url):
                response = self.client.get(url, follow=True)
                self.assertRedirects(response, self.my_appointment_url)
                self.assertContains(response, 'ya no se puede reprogramar ni cancelar')
                self.assertRedirects(self.client.post(url, {'slot': self.new_slot.pk}), self.my_appointment_url)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.RECEIVED)
        self.assertEqual(self.appointment.slot, self.old_slot)
