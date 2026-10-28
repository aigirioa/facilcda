from django.contrib.auth.views import LoginView, LogoutView

from .forms import LoginForm


login_view = LoginView.as_view(
    template_name='users/login.html',
    authentication_form=LoginForm,
    redirect_authenticated_user=True,
)

logout_view = LogoutView.as_view()
