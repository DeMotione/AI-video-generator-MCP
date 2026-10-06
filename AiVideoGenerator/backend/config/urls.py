from django.contrib import admin
from django.urls import include, path

from . import health

urlpatterns = [
    path("healthz/", health.live),
    path("readyz/", health.ready),
    path("admin/", admin.site.urls),
    path("auth/", include("accounts.urls")),
    path("", include("studio.urls")),
]
