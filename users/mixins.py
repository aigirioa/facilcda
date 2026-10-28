from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from configuration.constants import CDA_ADMIN_GROUP


def is_cda_admin(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name=CDA_ADMIN_GROUP).exists())


class CdaAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Vistas del panel: sin sesión redirige al login; con sesión pero sin el grupo responde 403."""

    def test_func(self):
        return is_cda_admin(self.request.user)
