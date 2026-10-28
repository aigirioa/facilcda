import datetime
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from .dates import local_now, local_today
from .middleware import DisplayTimezoneMiddleware


class SettingsTests(TestCase):

    def test_localization(self):
        self.assertEqual(settings.LANGUAGE_CODE, 'es-co')
        self.assertEqual(settings.TIME_ZONE, 'UTC')
        self.assertEqual(settings.DISPLAY_TIME_ZONE, 'America/Bogota')
        self.assertTrue(settings.USE_TZ)

    def test_domain_apps_are_installed(self):
        for app in ['users', 'configuration', 'customers', 'vehicles', 'appointments', 'inspections']:
            with self.subTest(app=app):
                self.assertIn(app, settings.INSTALLED_APPS)

    def test_uses_django_default_user_model(self):
        self.assertEqual(settings.AUTH_USER_MODEL, 'auth.User')


class HomePageTests(TestCase):

    def test_home_renders_with_public_layout(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/home.html')
        self.assertTemplateUsed(response, 'layouts/public.html')
        self.assertTemplateUsed(response, 'layouts/base.html')
        self.assertContains(response, 'Agendar cita')
        self.assertContains(response, 'Consultar mi revisión')
        self.assertContains(response, 'name="viewport"')


class AdminLayoutTests(TestCase):

    def test_admin_layout_shows_logged_user(self):
        user = get_user_model().objects.create_user(
            username='admin_cda', password='clave-segura-123', first_name='Ana', last_name='Gómez',
        )
        request = RequestFactory().get('/')
        request.user = user

        html = render_to_string('layouts/admin.html', {'user': user}, request=request)

        self.assertIn('Panel del CDA', html)
        self.assertIn('Ana Gómez', html)


class DisplayTimezoneMiddlewareTests(TestCase):

    def test_request_uses_bogota_time_zone(self):
        middleware = DisplayTimezoneMiddleware(lambda request: timezone.get_current_timezone_name())

        self.assertEqual(middleware(RequestFactory().get('/')), 'America/Bogota')

    def test_time_zone_is_restored_after_request(self):
        middleware = DisplayTimezoneMiddleware(lambda request: None)
        middleware(RequestFactory().get('/'))

        self.assertEqual(timezone.get_current_timezone_name(), 'UTC')

    def test_datetime_is_rendered_in_bogota_time(self):
        utc_noon = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=datetime.timezone.utc)

        def render(request):
            return timezone.localtime(utc_noon).strftime('%H:%M')

        self.assertEqual(DisplayTimezoneMiddleware(render)(RequestFactory().get('/')), '07:00')


class LocalDateTests(TestCase):

    def test_local_now_is_in_bogota_outside_a_request(self):
        self.assertEqual(str(local_now().tzinfo), 'America/Bogota')

    def test_local_today_uses_bogota_date(self):
        # 3 de noviembre a las 02:00 UTC todavía es 2 de noviembre en Bogotá (UTC-5).
        utc_now = datetime.datetime(2026, 11, 3, 2, 0, tzinfo=datetime.timezone.utc)
        with mock.patch('facilcda.dates.timezone.now', return_value=utc_now):
            self.assertEqual(local_today(), datetime.date(2026, 11, 2))
