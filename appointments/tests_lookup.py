from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .access import MY_APPOINTMENT_SESSION_KEY
from .models import Appointment
from .services import book_appointment, find_appointment
from .tests_booking import make_slot, owner_data, vehicle_data
from .throttling import MAX_LOOKUP_FAILURES, client_ip


LOOKUP_FAILED = 'No encontramos una cita con esos datos. Revisa la placa y el número de documento.'
LOOKUP_BLOCKED = 'Hiciste demasiados intentos.'


def finish(appointment, status=Appointment.Status.FINISHED):
    appointment.status = status
    if status == Appointment.Status.CANCELLED:
        appointment.cancelled_at = timezone.now()
    appointment.save()


class FindAppointmentTests(TestCase):

    def setUp(self):
        self.appointment = book_appointment(make_slot().pk, owner_data(), vehicle_data())

    def test_matches_plate_and_document_written_with_spaces_or_lowercase(self):
        self.assertEqual(find_appointment('abc 123', ' 1020304050 '), self.appointment)

    def test_wrong_document_or_unknown_plate_returns_none(self):
        self.assertIsNone(find_appointment('ABC123', '99999999'))
        self.assertIsNone(find_appointment('XYZ987', '1020304050'))

    def test_active_appointment_is_preferred_over_a_later_finished_one(self):
        finish(self.appointment)
        later = book_appointment(make_slot(day_offset=5).pk, owner_data(), vehicle_data())
        finish(later)
        active = book_appointment(make_slot(day_offset=2).pk, owner_data(), vehicle_data())

        self.assertEqual(find_appointment('ABC123', '1020304050'), active)

    def test_without_active_appointment_returns_the_most_recent(self):
        finish(self.appointment)
        latest = book_appointment(make_slot(day_offset=4).pk, owner_data(), vehicle_data())
        finish(latest, Appointment.Status.CANCELLED)

        self.assertEqual(find_appointment('ABC123', '1020304050'), latest)

    def test_document_of_the_person_who_booked_is_required(self):
        finish(self.appointment)
        book_appointment(make_slot(day_offset=3).pk, owner_data(document_number='55667788'), vehicle_data())

        # Quien agendó antes sigue viendo su propia cita, no la del nuevo propietario.
        self.assertEqual(find_appointment('ABC123', '1020304050'), self.appointment)


class AppointmentLookupViewTests(TestCase):

    def setUp(self):
        cache.clear()
        self.appointment = book_appointment(make_slot().pk, owner_data(), vehicle_data())
        self.url = reverse('appointments:lookup')

    def lookup(self, plate='ABC123', document_number='1020304050', **extra):
        return self.client.post(self.url, {'plate': plate, 'document_number': document_number}, **extra)

    def test_form_is_shown(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'appointments/lookup_form.html')

    def test_correct_data_opens_my_appointment(self):
        response = self.lookup(plate='abc-123')

        self.assertRedirects(response, reverse('appointments:my_appointment'))
        response = self.client.get(reverse('appointments:my_appointment'))
        self.assertContains(response, self.appointment.code)
        self.assertContains(response, 'Agendada')

    def test_wrong_document_and_unknown_plate_show_the_same_generic_message(self):
        wrong_document = self.lookup(document_number='99999999')
        unknown_plate = self.lookup(plate='XYZ987')

        for response in (wrong_document, unknown_plate):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, LOOKUP_FAILED)
        self.assertNotIn(MY_APPOINTMENT_SESSION_KEY, self.client.session)

    def test_blocks_after_five_failures_even_with_correct_data(self):
        for _ in range(MAX_LOOKUP_FAILURES):
            self.lookup(document_number='99999999')

        response = self.lookup()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, LOOKUP_BLOCKED)
        self.assertNotIn(MY_APPOINTMENT_SESSION_KEY, self.client.session)

    def test_four_failures_do_not_block(self):
        for _ in range(MAX_LOOKUP_FAILURES - 1):
            self.lookup(document_number='99999999')

        self.assertRedirects(self.lookup(), reverse('appointments:my_appointment'))

    def test_failures_are_counted_per_ip(self):
        for _ in range(MAX_LOOKUP_FAILURES):
            self.lookup(document_number='99999999', REMOTE_ADDR='10.0.0.1')

        response = self.lookup(REMOTE_ADDR='10.0.0.2')

        self.assertRedirects(response, reverse('appointments:my_appointment'))

    def test_block_ends_when_the_window_expires(self):
        for _ in range(MAX_LOOKUP_FAILURES):
            self.lookup(document_number='99999999')
        cache.clear()  # Lo que hace la caché al vencer los 15 minutos.

        self.assertRedirects(self.lookup(), reverse('appointments:my_appointment'))

    def test_invalid_plate_format_shows_the_field_error_and_does_not_count(self):
        for _ in range(MAX_LOOKUP_FAILURES):
            response = self.lookup(plate='AB')

        self.assertIn('plate', response.context['form'].errors)
        self.assertNotContains(response, LOOKUP_FAILED)
        self.assertRedirects(self.lookup(), reverse('appointments:my_appointment'))


class ClientIpTests(TestCase):

    def setUp(self):
        self.request = RequestFactory().get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='1.1.1.1, 2.2.2.2')

    def test_uses_remote_addr_by_default(self):
        self.assertEqual(client_ip(self.request), '127.0.0.1')

    @override_settings(USE_X_FORWARDED_FOR=True)
    def test_behind_the_proxy_uses_the_address_added_by_nginx(self):
        self.assertEqual(client_ip(self.request), '2.2.2.2')


class MyAppointmentViewTests(TestCase):

    def setUp(self):
        cache.clear()
        self.appointment = book_appointment(make_slot().pk, owner_data(), vehicle_data())
        self.url = reverse('appointments:my_appointment')

    def lookup(self):
        self.client.post(reverse('appointments:lookup'), {'plate': 'ABC123', 'document_number': '1020304050'})

    def test_without_lookup_redirects_to_the_lookup_form(self):
        response = self.client.get(self.url)

        self.assertRedirects(response, reverse('appointments:lookup'))

    def test_another_session_cannot_see_the_appointment(self):
        self.lookup()

        response = self.client_class().get(self.url)

        self.assertRedirects(response, reverse('appointments:lookup'))

    def test_access_expires_after_thirty_minutes(self):
        self.lookup()
        session = self.client.session
        session[MY_APPOINTMENT_SESSION_KEY]['granted_at'] -= 31 * 60
        session.save()

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse('appointments:lookup'))
        self.assertNotIn(MY_APPOINTMENT_SESSION_KEY, self.client.session)

    def test_shows_cancelled_appointment_when_it_is_the_most_recent(self):
        finish(self.appointment, Appointment.Status.CANCELLED)
        self.lookup()

        response = self.client.get(self.url)

        self.assertContains(response, self.appointment.code)
        self.assertContains(response, 'Cancelada')

    def test_exit_closes_the_lookup(self):
        self.lookup()

        response = self.client.post(reverse('appointments:my_appointment_exit'))

        self.assertRedirects(response, reverse('home'))
        self.assertRedirects(self.client.get(self.url), reverse('appointments:lookup'))

    def test_home_button_opens_the_lookup_form(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, f'href="{reverse("appointments:lookup")}" class="btn btn-outline-primary btn-lg"')
