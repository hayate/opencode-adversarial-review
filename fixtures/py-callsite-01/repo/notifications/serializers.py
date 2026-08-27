from rest_framework import serializers

from notifications.services import format_notification


class NotificationSerializer(serializers.Serializer):
    text = serializers.SerializerMethodField()

    def get_text(self, obj):
        return format_notification(obj, self.context.get("locale", "en"))
