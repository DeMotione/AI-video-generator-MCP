import hashlib

from django.contrib.auth.views import LoginView
from django.core.cache import cache

from .forms import LoginForm


class StudioLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def throttle_key(self):
        source = self.request.META.get("REMOTE_ADDR", "unknown")
        return "login:" + hashlib.sha256(source.encode()).hexdigest()

    def post(self, request, *args, **kwargs):
        if cache.get(self.throttle_key(), 0) >= 10:
            form = self.get_form_class()(request=request)
            form.is_bound = True
            form.full_clean()
            form.add_error(None, "Too many attempts. Please try again in 15 minutes.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self.throttle_key()
        cache.set(key, cache.get(key, 0) + 1, timeout=900)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self.throttle_key())
        return super().form_valid(form)
