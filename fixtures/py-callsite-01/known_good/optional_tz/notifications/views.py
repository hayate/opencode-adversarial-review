from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import Notification
from notifications.services import format_notification, guest_timezone


class NotificationDetail(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk):
        note = Notification.objects.get(pk=pk)
        locale = request.GET.get("locale", "en")
        return Response({"text": format_notification(note, locale, guest_timezone(note))})
