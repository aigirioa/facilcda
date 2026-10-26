import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from appointments.models import Appointment, TimeSlot
from customers.models import Owner

from .models import Vehicle
from .validators import normalize_plate, validate_model_year, validate_plate


def make_owner():
    return Owner.objects.create(
        document_type=Owner.DocumentType.CC, document_number='1020304050',
        first_name='Laura', last_name='Restrepo', email='laura@example.com', phone='3001234567',
    )


def make_vehicle(owner, **kwargs):
    data = {
        'plate': 'ABC123',
        'vehicle_type': Vehicle.VehicleType.LIGHT_PRIVATE,
        'brand': 'Renault',
        'line': 'Logan',
        'model_year': 2018,
        'owner': owner,
    }
    data.update(kwargs)
    return Vehicle.objects.create(**data)


class PlateValidatorTests(SimpleTestCase):

    def test_valid_plates(self):
        for plate in ['ABC123', 'ABC12D']:
            with self.subTest(plate=plate):
                validate_plate(plate)

    def test_invalid_plates(self):
        for plate in ['AB1234', 'ABC1234', 'ABCD12', '123ABC', 'abc123', 'ABC1D2', '']:
            with self.subTest(plate=plate), self.assertRaises(ValidationError):
                validate_plate(plate)

    def test_normalize_plate(self):
        self.assertEqual(normalize_plate(' abc-123 '), 'ABC123')
        self.assertEqual(normalize_plate('abc 12d'), 'ABC12D')

    def test_model_year_range(self):
        validate_model_year(1950)
        validate_model_year(timezone.now().year + 1)
        for year in [1949, timezone.now().year + 2]:
            with self.subTest(year=year), self.assertRaises(ValidationError):
                validate_model_year(year)


class VehicleModelTests(TestCase):

    def setUp(self):
        self.owner = make_owner()

    def test_plate_is_saved_uppercase_without_spaces(self):
        vehicle = make_vehicle(self.owner, plate='abc 123')

        self.assertEqual(vehicle.plate, 'ABC123')

    def test_full_clean_normalizes_and_validates_plate(self):
        vehicle = Vehicle(
            plate='abc-12d', vehicle_type=Vehicle.VehicleType.MOTORCYCLE,
            brand='Yamaha', model_year=2020, owner=self.owner,
        )
        vehicle.full_clean()

        self.assertEqual(vehicle.plate, 'ABC12D')

    def test_full_clean_rejects_invalid_plate(self):
        vehicle = Vehicle(
            plate='A1', vehicle_type=Vehicle.VehicleType.LIGHT_PRIVATE,
            brand='Renault', model_year=2018, owner=self.owner,
        )
        with self.assertRaises(ValidationError) as ctx:
            vehicle.full_clean()
        self.assertIn('plate', ctx.exception.message_dict)


class VehicleConstraintTests(TestCase):

    def setUp(self):
        self.owner = make_owner()

    def test_duplicate_plate_is_rejected(self):
        make_vehicle(self.owner)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_vehicle(self.owner, plate='abc123')

    def test_database_rejects_invalid_plate_format(self):
        vehicle = make_vehicle(self.owner)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Vehicle.objects.filter(pk=vehicle.pk).update(plate='12AB')

    def test_database_rejects_model_year_before_1950(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_vehicle(self.owner, model_year=1949)

    def test_owner_with_vehicles_cannot_be_deleted(self):
        make_vehicle(self.owner)
        with self.assertRaises(ProtectedError):
            self.owner.delete()


class VehicleHistoryTests(TestCase):

    def test_history_is_ordered_from_newest_to_oldest(self):
        owner = make_owner()
        vehicle = make_vehicle(owner)
        old_slot = TimeSlot.objects.create(
            date=datetime.date(2026, 1, 10), start_time=datetime.time(8, 0), end_time=datetime.time(8, 30),
        )
        new_slot = TimeSlot.objects.create(
            date=datetime.date(2026, 6, 10), start_time=datetime.time(8, 0), end_time=datetime.time(8, 30),
        )
        old = Appointment.objects.create(
            vehicle=vehicle, owner=owner, slot=old_slot, turn=1, status=Appointment.Status.FINISHED,
        )
        new = Appointment.objects.create(vehicle=vehicle, owner=owner, slot=new_slot, turn=1)

        self.assertEqual(list(vehicle.history()), [new, old])
