from django.urls import path

from notifications.views import NotificationDetail

urlpatterns = [
    path("notifications/<int:pk>/", NotificationDetail.as_view(), name="notification-detail"),
]
