import uuid

from django.conf import settings
from django.db import models


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=80, default="Untitled creation")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class Generation(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SUBMITTING = "submitting", "Sending to renderer"
        RUNNING = "running", "Generating"
        COMPLETED = "completed", "Ready"
        FAILED = "failed", "Failed"
        UNKNOWN = "unknown", "Needs attention"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="generations"
    )
    prompt = models.TextField(max_length=2000)
    image_key = models.CharField(max_length=300)
    image_name = models.CharField(max_length=150)
    image_width = models.PositiveIntegerField()
    image_height = models.PositiveIntegerField()
    video_key = models.CharField(max_length=300, blank=True)
    video_mime = models.CharField(max_length=40, default="video/mp4")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    comfy_id = models.CharField(max_length=100, blank=True)
    message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]
