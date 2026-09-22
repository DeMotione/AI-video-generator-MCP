from django.urls import path

from . import views

app_name = "studio"
urlpatterns = [
    path("", views.home, name="home"),
    path("api/conversations/", views.conversations, name="conversations"),
    path("api/conversations/new/", views.new_conversation, name="new_conversation"),
    path("api/conversations/<uuid:conversation_id>/", views.conversation_detail, name="detail"),
    path("api/conversations/<uuid:conversation_id>/generate/", views.generate, name="generate"),
    path("private/<uuid:job_id>/<str:kind>/", views.media, name="media"),
]
