from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import Owner


def make_owner(**kwargs):
    data = {
        'document_type': Owner.DocumentType.CC,
        'document_number': '1020304050',
        'first_name': 'Laura',
        'last_name': 'Restrepo',
        'email': 'laura@example.com',
        'phone': '3001234567',
        'accepts_data_processing': True,
        'data_processing_accepted_at': timezone.now(),
    }
    data.update(kwargs)
    return Owner.objects.create(**data)


class OwnerConstraintTests(TestCase):

    def test_same_document_type_and_number_is_rejected(self):
        make_owner()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_owner(first_name='Otra')

    def test_same_number_with_other_document_type_is_allowed(self):
        make_owner()
        make_owner(document_type=Owner.DocumentType.CE)

        self.assertEqual(Owner.objects.count(), 2)

    def test_database_rejects_consent_without_date(self):
        owner = make_owner()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Owner.objects.filter(pk=owner.pk).update(data_processing_accepted_at=None)

    def test_no_consent_without_date_is_allowed(self):
        owner = make_owner(accepts_data_processing=False, data_processing_accepted_at=None)

        self.assertFalse(owner.accepts_data_processing)


class OwnerValidationTests(TestCase):

    def build(self, **kwargs):
        data = {
            'document_type': Owner.DocumentType.CC,
            'document_number': '1020304050',
            'first_name': 'Laura',
            'last_name': 'Restrepo',
            'email': 'laura@example.com',
            'phone': '3001234567',
        }
        data.update(kwargs)
        return Owner(**data)

    def test_document_number_is_normalized(self):
        owner = make_owner(document_type=Owner.DocumentType.PA, document_number=' ab 12345 ')

        self.assertEqual(owner.document_number, 'AB12345')

    def test_cc_with_letters_is_invalid(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(document_number='10203A').full_clean()
        self.assertIn('document_number', ctx.exception.message_dict)

    def test_passport_allows_letters_and_numbers(self):
        self.build(document_type=Owner.DocumentType.PA, document_number='AB12345').full_clean()

    def test_passport_rejects_symbols(self):
        with self.assertRaises(ValidationError):
            self.build(document_type=Owner.DocumentType.PA, document_number='AB-12345').full_clean()


class OwnerConsentDateTests(TestCase):

    def test_accepting_sets_the_date_on_save(self):
        owner = make_owner(data_processing_accepted_at=None)

        self.assertIsNotNone(owner.data_processing_accepted_at)

    def test_accepting_sets_the_date_on_full_clean(self):
        owner = Owner(
            document_type=Owner.DocumentType.CC, document_number='1020304050',
            first_name='Laura', last_name='Restrepo', email='laura@example.com', phone='3001234567',
            accepts_data_processing=True,
        )
        owner.full_clean()

        self.assertIsNotNone(owner.data_processing_accepted_at)

    def test_existing_date_is_kept(self):
        owner = make_owner()
        accepted_at = owner.data_processing_accepted_at
        owner.phone = '3109876543'
        owner.save()

        self.assertEqual(owner.data_processing_accepted_at, accepted_at)

    def test_withdrawing_consent_clears_the_date(self):
        owner = make_owner()
        owner.accepts_data_processing = False
        owner.save()

        self.assertIsNone(owner.data_processing_accepted_at)
