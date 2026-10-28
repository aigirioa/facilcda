from django.contrib.auth.models import AnonymousUser, Group, User
from django.test import TestCase
from django.urls import reverse

from configuration.constants import CDA_ADMIN_GROUP

from .mixins import is_cda_admin


PASSWORD = 'clave-segura-123'


class LoginTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='operador', password=PASSWORD)
        self.user.groups.add(Group.objects.get(name=CDA_ADMIN_GROUP))

    def test_login_page_renders(self):
        response = self.client.get(reverse('users:login'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/login.html')
        self.assertContains(response, 'Iniciar sesión')

    def test_valid_login_redirects_to_the_panel(self):
        response = self.client.post(reverse('users:login'), {'username': 'operador', 'password': PASSWORD})

        self.assertRedirects(response, reverse('appointments:slot_list'))

    def test_invalid_login_shows_an_error(self):
        response = self.client.post(reverse('users:login'), {'username': 'operador', 'password': 'otra'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertTrue(response.context['form'].errors)

    def test_logout_requires_post_and_redirects_to_login(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse('users:logout')).status_code, 405)
        response = self.client.post(reverse('users:logout'))

        self.assertRedirects(response, reverse('users:login'))
        self.assertNotIn('_auth_user_id', self.client.session)


class IsCdaAdminTests(TestCase):

    def test_member_of_group(self):
        user = User.objects.create_user(username='operador', password=PASSWORD)
        user.groups.add(Group.objects.get(name=CDA_ADMIN_GROUP))

        self.assertTrue(is_cda_admin(user))

    def test_superuser(self):
        self.assertTrue(is_cda_admin(User.objects.create_superuser(username='admin', password=PASSWORD)))

    def test_user_without_group(self):
        self.assertFalse(is_cda_admin(User.objects.create_user(username='otro', password=PASSWORD)))

    def test_anonymous_user(self):
        self.assertFalse(is_cda_admin(AnonymousUser()))
