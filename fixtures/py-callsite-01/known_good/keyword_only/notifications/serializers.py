from rest_framework import serializers

from notifications.services import format_notification, guest_timezone


class NotificationSerializer(serializers.Serializer):
    text = serializers.SerializerMethodField()

    def get_text(self, obj):
        locale = self.context.get("locale", "en")
        return format_notification(obj, locale, tz=guest_timezone(obj))
