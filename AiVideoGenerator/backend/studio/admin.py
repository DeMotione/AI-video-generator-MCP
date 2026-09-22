from django.contrib import admin

from .models import Conversation, Generation


@admin.register(Generation)
class GenerationAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = tuple(field.name for field in Generation._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "updated_at")
    readonly_fields = ("id", "owner", "title", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
