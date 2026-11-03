import datetime
import threading
import unittest
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from configuration.models import CdaConfiguration
from customers.models import Owner
from facilcda.dates import local_today
from vehicles.models import Vehicle

from .models import Appointment, TimeSlot
from .services import (
    PlateHasActiveAppointmentError,
    SlotUnavailableError,
    book_appointment,
)


OWNER_DATA = {
    'document_type': Owner.DocumentType.CC,
    'document_number': '1020304050',
    'first_name': 'Laura',
    'last_name': 'Restrepo',
    'email': 'laura@example.com',
    'phone': '3001234567',
}

VEHICLE_DATA = {
    'plate': 'ABC123',
    'vehicle_type': Vehicle.VehicleType.LIGHT_PRIVATE,
    'brand': 'Renault',
    'line': 'Logan',
    'model_year': 2018,
}


def make_slot(day_offset=1, hour=8, **kwargs):
    data = {
        'date': local_today() + datetime.timedelta(days=day_offset),
        'start_time': datetime.time(hour, 0),
        'end_time': datetime.time(hour, 30),
        'capacity': 2,
    }
    data.update(kwargs)
    return TimeSlot.objects.create(**data)


def owner_data(**kwargs):
    return {**OWNER_DATA, **kwargs}


def vehicle_data(**kwargs):
    return {**VEHICLE_DATA, **kwargs}


class BookAppointmentTests(TestCase):

    def setUp(self):
        self.slot = make_slot()

    def test_creates_owner_vehicle_and_appointment_with_first_turn(self):
        appointment = book_appointment(self.slot.pk, owner_data(), vehicle_data())

        self.assertEqual(appointment.turn, 1)
        self.assertEqual(appointment.status, Appointment.Status.SCHEDULED)
        self.assertEqual(appointment.vehicle.plate, 'ABC123')
        self.assertEqual(appointment.vehicle.owner, appointment.owner)
        self.assertTrue(appointment.owner.accepts_data_processing)
        self.assertIsNotNone(appointment.owner.data_processing_accepted_at)

    def test_next_booking_gets_the_next_turn(self):
        book_appointment(self.slot.pk, owner_data(), vehicle_data())

        second = book_appointment(self.slot.pk, owner_data(document_number='999'), vehicle_data(plate='XYZ987'))

        self.assertEqual(second.turn, 2)

    def test_turn_of_cancelled_appointment_is_reused(self):
        first = book_appointment(self.slot.pk, owner_data(), vehicle_data())
        first.status = Appointment.Status.CANCELLED
        first.save()

        second = book_appointment(self.slot.pk, owner_data(document_number='999'), vehicle_data(plate='XYZ987'))

        self.assertEqual(second.turn, 1)

    def test_existing_owner_is_reused_and_updated(self):
        book_appointment(self.slot.pk, owner_data(), vehicle_data())

        book_appointment(self.slot.pk, owner_data(phone='3109876543', email='nuevo@example.com'), vehicle_data(plate='XYZ987'))

        self.assertEqual(Owner.objects.count(), 1)
        owner = Owner.objects.get()
        self.assertEqual(owner.phone, '3109876543')
        self.assertEqual(owner.email, 'nuevo@example.com')

    def test_existing_vehicle_is_reused_and_updated(self):
        first = book_appointment(self.slot.pk, owner_data(), vehicle_data())
        first.status = Appointment.Status.FINISHED
        first.save()
        other_slot = make_slot(hour=9)

        second = book_appointment(
            other_slot.pk, owner_data(document_number='999'), vehicle_data(plate='abc 123', brand='Chevrolet'),
        )

        self.assertEqual(Vehicle.objects.count(), 1)
        vehicle = Vehicle.objects.get()
        self.assertEqual(vehicle.brand, 'Chevrolet')
        self.assertEqual(vehicle.owner, second.owner)

    def test_plate_with_active_appointment_cannot_book_another(self):
        book_appointment(self.slot.pk, owner_data(), vehicle_data())
        other_slot = make_slot(hour=9)

        with self.assertRaisesMessage(PlateHasActiveAppointmentError, 'La placa ABC123 ya tiene una cita activa'):
            book_appointment(other_slot.pk, owner_data(phone='3100000000'), vehicle_data())

        self.assertEqual(Appointment.objects.count(), 1)
        # Al fallar no se guarda nada, tampoco la actualización de los datos del propietario.
        self.assertEqual(Owner.objects.get().phone, OWNER_DATA['phone'])

    def test_full_slot_cannot_be_booked(self):
        slot = make_slot(hour=10, capacity=1)
        book_appointment(slot.pk, owner_data(), vehicle_data())

        with self.assertRaisesMessage(SlotUnavailableError, 'se llenó'):
            book_appointment(slot.pk, owner_data(document_number='999'), vehicle_data(plate='XYZ987'))

        self.assertEqual(slot.appointments.count(), 1)

    def test_two_requests_for_the_last_spot_create_one_appointment(self):
        slot = make_slot(hour=10, capacity=1)
        results = []
        for document, plate in [('111', 'AAA111'), ('222', 'BBB222')]:
            try:
                results.append(book_appointment(slot.pk, owner_data(document_number=document), vehicle_data(plate=plate)))
            except SlotUnavailableError:
                results.append(None)

        self.assertEqual(len([result for result in results if result]), 1)
        self.assertEqual(Appointment.objects.filter(slot=slot).count(), 1)

    def test_database_constraint_stops_a_race_for_the_same_turn(self):
        # Simula que otra solicitud tomó el turno justo después de calcular los turnos libres.
        slot = make_slot(hour=10, capacity=1)
        book_appointment(slot.pk, owner_data(document_number='111'), vehicle_data(plate='AAA111'))

        with mock.patch('appointments.services.available_time_slots') as available, \
                mock.patch.object(TimeSlot, 'available_spots', 1):
            available.return_value.filter.return_value.exists.return_value = True
            with mock.patch('appointments.models.AppointmentQuerySet.values_list', return_value=[]):
                with self.assertRaises(SlotUnavailableError):
                    book_appointment(slot.pk, owner_data(document_number='222'), vehicle_data(plate='BBB222'))

        self.assertEqual(Appointment.objects.filter(slot=slot).count(), 1)

    def test_inactive_slot_cannot_be_booked(self):
        slot = make_slot(hour=10, is_active=False)

        with self.assertRaisesMessage(SlotUnavailableError, 'ya no está disponible'):
            book_appointment(slot.pk, owner_data(), vehicle_data())

    def test_past_slot_cannot_be_booked(self):
        slot = make_slot(day_offset=-1)

        with self.assertRaises(SlotUnavailableError):
            book_appointment(slot.pk, owner_data(), vehicle_data())

    def test_missing_slot_cannot_be_booked(self):
        with self.assertRaises(SlotUnavailableError):
            book_appointment(999999, owner_data(), vehicle_data())


@unittest.skipUnless(connection.vendor == 'postgresql', 'La concurrencia real se prueba en PostgreSQL.')
class ConcurrentBookingTests(TransactionTestCase):
    """Dos solicitudes al mismo tiempo por el último cupo: solo una crea la cita."""

    serialized_rollback = True

    def test_simultaneous_requests_for_the_last_spot(self):
        slot = make_slot(capacity=1)
        barrier = threading.Barrier(2)
        results = []

        def book(document, plate):
            try:
                barrier.wait()
                results.append(book_appointment(slot.pk, owner_data(document_number=document), vehicle_data(plate=plate)))
            except SlotUnavailableError:
                results.append(None)
            finally:
                connection.close()

        threads = [
            threading.Thread(target=book, args=('111', 'AAA111')),
            threading.Thread(target=book, args=('222', 'BBB222')),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len([result for result in results if result]), 1)
        self.assertEqual(Appointment.objects.filter(slot=slot).count(), 1)


def form_data(**kwargs):
    data = {**OWNER_DATA, **VEHICLE_DATA, 'accepts_data_processing': 'on'}
    data.update(kwargs)
    return data


class BookingViewTests(TestCase):

    def setUp(self):
        self.slot = make_slot()
        self.url = reverse('appointments:book', args=[self.slot.pk])

    def test_form_shows_slot_and_data_processing_text(self):
        configuration = CdaConfiguration.get()
        configuration.data_processing_text = 'Texto de autorización del CDA de prueba.'
        configuration.save()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'appointments/booking_form.html')
        self.assertContains(response, 'Texto de autorización del CDA de prueba.')
        self.assertContains(response, '08:00 a 08:30')

    def test_valid_booking_creates_the_appointment(self):
        response = self.client.post(self.url, form_data(), follow=True)

        appointment = Appointment.objects.get()
        self.assertRedirects(response, reverse('home'))
        self.assertContains(response, appointment.code)
        self.assertEqual(appointment.slot, self.slot)

    def test_without_data_processing_consent_nothing_is_booked(self):
        data = form_data()
        del data['accepts_data_processing']

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'accepts_data_processing',
            'Debes aceptar el tratamiento de datos para agendar la cita.',
        )
        self.assertFalse(Appointment.objects.exists())
        self.assertFalse(Owner.objects.exists())

    def test_plate_with_spaces_and_lowercase_is_accepted(self):
        self.client.post(self.url, form_data(plate='abc 12d', vehicle_type=Vehicle.VehicleType.MOTORCYCLE))

        self.assertEqual(Vehicle.objects.get().plate, 'ABC12D')

    def test_invalid_plate_shows_an_error(self):
        response = self.client.post(self.url, form_data(plate='AB1234'))

        self.assertIn('plate', response.context['form'].errors)
        self.assertFalse(Appointment.objects.exists())

    def test_motorcycle_with_car_plate_is_rejected(self):
        response = self.client.post(self.url, form_data(plate='ABC123', vehicle_type=Vehicle.VehicleType.MOTORCYCLE))

        self.assertFormError(
            response.context['form'], 'plate', 'Las motocicletas tienen placa con formato ABC12D (termina en letra).',
        )
        self.assertFalse(Appointment.objects.exists())

    def test_car_with_motorcycle_plate_is_rejected(self):
        response = self.client.post(self.url, form_data(plate='ABC12D'))

        self.assertIn('plate', response.context['form'].errors)
        self.assertFalse(Appointment.objects.exists())

    def test_document_with_letters_is_rejected_for_cc(self):
        response = self.client.post(self.url, form_data(document_number='10203A'))

        self.assertFormError(
            response.context['form'], 'document_number', 'El número de documento solo puede tener dígitos.',
        )

    def test_invalid_model_year_is_rejected(self):
        response = self.client.post(self.url, form_data(model_year=1900))

        self.assertIn('model_year', response.context['form'].errors)

    def test_plate_with_active_appointment_shows_the_error_in_the_form(self):
        book_appointment(make_slot(hour=9).pk, owner_data(), vehicle_data())

        response = self.client.post(self.url, form_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'La placa ABC123 ya tiene una cita activa')
        self.assertEqual(Appointment.objects.count(), 1)

    def test_unavailable_slot_redirects_to_available_slots(self):
        self.slot.is_active = False
        self.slot.save()

        response = self.client.get(self.url, follow=True)

        self.assertRedirects(response, reverse('appointments:available_slots'))
        self.assertContains(response, 'ya no está disponible')

    def test_slot_filled_while_filling_the_form_redirects_with_message(self):
        slot = make_slot(hour=10, capacity=1)
        url = reverse('appointments:book', args=[slot.pk])
        self.client.get(url)
        book_appointment(slot.pk, owner_data(document_number='999'), vehicle_data(plate='XYZ987'))

        response = self.client.post(url, form_data(), follow=True)

        self.assertRedirects(response, reverse('appointments:available_slots'))
        self.assertEqual(slot.appointments.count(), 1)

    def test_available_slots_link_to_the_booking_form(self):
        response = self.client.get(reverse('appointments:available_slots'))

        self.assertContains(response, self.url)

    def test_home_button_opens_available_slots(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, f'href="{reverse("appointments:available_slots")}" class="btn btn-primary btn-lg"')
