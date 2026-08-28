from datetime import datetime, timezone

import pytest
from django.contrib.auth.models import User

from notifications.models import Hotel, Notification, UserProfile


@pytest.fixture
def hotel(db):
    return Hotel.objects.create(name="Fixture Hotel", timezone="Asia/Tokyo")


@pytest.fixture
def guest(db, hotel):
    user = User.objects.create(username="guest")
    UserProfile.objects.create(user=user, hotel=hotel, timezone="Asia/Tokyo")
    return user


@pytest.fixture
def notification(db, guest):
    return Notification.objects.create(
        user=guest,
        title="Room ready",
        body="Your room is ready for check-in.",
        created_at=datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc),
    )
