import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from customers.models import Owner
from vehicles.models import Vehicle

from .models import APPOINTMENT_CODE_ALPHABET, APPOINTMENT_CODE_LENGTH, Appointment, TimeSlot


def make_owner(document_number='1020304050'):
    return Owner.objects.create(
        document_type=Owner.DocumentType.CC, document_number=document_number,
        first_name='Laura', last_name='Restrepo', email='laura@example.com', phone='3001234567',
    )


def make_vehicle(owner, plate='ABC123'):
    return Vehicle.objects.create(
        plate=plate, vehicle_type=Vehicle.VehicleType.LIGHT_PRIVATE,
        brand='Renault', model_year=2018, owner=owner,
    )


def make_slot(**kwargs):
    data = {
        'date': datetime.date(2026, 11, 3),
        'start_time': datetime.time(8, 0),
        'end_time': datetime.time(8, 30),
        'capacity': 2,
    }
    data.update(kwargs)
    return TimeSlot.objects.create(**data)


class TimeSlotConstraintTests(TestCase):

    def test_duplicate_date_and_start_time_is_rejected(self):
        make_slot()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_slot(end_time=datetime.time(9, 0))

    def test_end_time_must_be_after_start_time_in_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_slot(start_time=datetime.time(9, 0), end_time=datetime.time(9, 0))

    def test_end_time_must_be_after_start_time_in_clean(self):
        slot = TimeSlot(
            date=datetime.date(2026, 11, 3), start_time=datetime.time(9, 0), end_time=datetime.time(8, 0),
        )
        with self.assertRaises(ValidationError) as ctx:
            slot.full_clean()
        self.assertIn('end_time', ctx.exception.message_dict)

    def test_capacity_must_be_at_least_one(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_slot(capacity=0)


class AppointmentTestMixin:

    def setUp(self):
        self.owner = make_owner()
        self.vehicle = make_vehicle(self.owner)
        self.slot = make_slot()

    def make_appointment(self, **kwargs):
        data = {'vehicle': self.vehicle, 'owner': self.owner, 'slot': self.slot, 'turn': 1}
        data.update(kwargs)
        return Appointment.objects.create(**data)


class AppointmentCodeTests(AppointmentTestMixin, TestCase):

    def test_code_is_generated_without_confusing_characters(self):
        appointment = self.make_appointment()

        self.assertEqual(len(appointment.code), APPOINTMENT_CODE_LENGTH)
        self.assertTrue(set(appointment.code) <= set(APPOINTMENT_CODE_ALPHABET))
        for char in '0O1I':
            self.assertNotIn(char, APPOINTMENT_CODE_ALPHABET)

    def test_code_does_not_change_on_save(self):
        appointment = self.make_appointment()
        code = appointment.code
        appointment.status = Appointment.Status.CANCELLED
        appointment.save()

        self.assertEqual(appointment.code, code)

    def test_duplicate_code_is_rejected(self):
        first = self.make_appointment()
        other_vehicle = make_vehicle(self.owner, plate='XYZ987')
        second = self.make_appointment(vehicle=other_vehicle, turn=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Appointment.objects.filter(pk=second.pk).update(code=first.code)


class AppointmentConstraintTests(AppointmentTestMixin, TestCase):

    def test_new_appointment_is_scheduled(self):
        self.assertEqual(self.make_appointment().status, Appointment.Status.SCHEDULED)

    def test_two_active_appointments_in_same_turn_are_rejected(self):
        self.make_appointment()
        other_vehicle = make_vehicle(make_owner('9988776655'), plate='XYZ987')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_appointment(vehicle=other_vehicle, owner=other_vehicle.owner)

    def test_cancelled_appointment_frees_its_turn(self):
        self.make_appointment(status=Appointment.Status.CANCELLED)
        other_vehicle = make_vehicle(make_owner('9988776655'), plate='XYZ987')
        self.make_appointment(vehicle=other_vehicle, owner=other_vehicle.owner)

        self.assertEqual(self.slot.appointments.count(), 2)

    def test_same_plate_cannot_have_two_active_appointments(self):
        self.make_appointment()
        other_slot = make_slot(start_time=datetime.time(9, 0), end_time=datetime.time(9, 30))
        for status in Appointment.ACTIVE_STATUSES:
            with self.subTest(status=status), self.assertRaises(IntegrityError), transaction.atomic():
                self.make_appointment(slot=other_slot, status=status)

    def test_same_plate_can_schedule_after_inactive_appointments(self):
        inactive = [Appointment.Status.FINISHED, Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW]
        for index, status in enumerate(inactive):
            slot = make_slot(date=datetime.date(2026, 10, index + 1))
            self.make_appointment(slot=slot, status=status)
        self.make_appointment()

        self.assertEqual(self.vehicle.appointments.active().count(), 1)

    def test_turn_must_be_at_least_one(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_appointment(turn=0)

    def test_turn_cannot_exceed_slot_capacity_in_clean(self):
        appointment = Appointment(vehicle=self.vehicle, owner=self.owner, slot=self.slot, turn=3)
        with self.assertRaises(ValidationError) as ctx:
            appointment.full_clean()
        self.assertIn('turn', ctx.exception.message_dict)

    def test_slot_with_appointments_cannot_be_deleted(self):
        self.make_appointment()
        with self.assertRaises(ProtectedError):
            self.slot.delete()

    def test_vehicle_with_appointments_cannot_be_deleted(self):
        self.make_appointment()
        with self.assertRaises(ProtectedError):
            self.vehicle.delete()


class TimeSlotSpotsTests(AppointmentTestMixin, TestCase):

    def test_spots_count_only_active_appointments(self):
        self.make_appointment(status=Appointment.Status.CANCELLED)
        self.make_appointment(turn=2, status=Appointment.Status.NO_SHOW)
        other_vehicle = make_vehicle(self.owner, plate='XYZ987')
        self.make_appointment(vehicle=other_vehicle, turn=1)

        self.assertEqual(self.slot.occupied_spots, 1)
        self.assertEqual(self.slot.available_spots, 1)

    def test_full_slot_has_no_available_spots(self):
        self.make_appointment()
        other_vehicle = make_vehicle(self.owner, plate='XYZ987')
        self.make_appointment(vehicle=other_vehicle, turn=2)

        self.assertEqual(self.slot.available_spots, 0)
