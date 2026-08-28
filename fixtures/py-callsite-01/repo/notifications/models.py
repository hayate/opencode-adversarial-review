from django.conf import settings
from django.db import models


class Hotel(models.Model):
    name = models.CharField(max_length=120)
    timezone = models.CharField(max_length=64, default="Asia/Tokyo")

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name="guests")
    # Null for walk-in guests who never completed online check-in.
    timezone = models.CharField(max_length=64, null=True, blank=True)


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    created_at = models.DateTimeField()
    sent = models.BooleanField(default=False)
