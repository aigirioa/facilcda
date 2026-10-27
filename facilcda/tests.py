from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse


class SettingsTests(TestCase):

    def test_localization(self):
        self.assertEqual(settings.LANGUAGE_CODE, 'es-co')
        self.assertEqual(settings.TIME_ZONE, 'UTC')
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
