"""Hidden grader fixtures. Never visible to the agent (spec section 5)."""

from datetime import datetime, timezone

import pytest
from django.contrib.auth.models import User

from notifications.models import Hotel, Notification, UserProfile

CREATED_AT = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)
TITLE = "Room ready"
BODY = "Your room is ready for check-in."


@pytest.fixture
def hotel(db):
    return Hotel.objects.create(name="Grader Hotel", timezone="Asia/Tokyo")


def _guest(hotel, username, tz):
    user = User.objects.create(username=username)
    UserProfile.objects.create(user=user, hotel=hotel, timezone=tz)
    return user


@pytest.fixture
def tokyo_guest(db, hotel):
    return _guest(hotel, "tokyo_guest", "Asia/Tokyo")


@pytest.fixture
def london_guest(db, hotel):
    return _guest(hotel, "london_guest", "Europe/London")


@pytest.fixture
def walkin_guest(db, hotel):
    """A walk-in who never completed online check-in: timezone is NULL."""
    return _guest(hotel, "walkin_guest", None)


def _note(user):
    return Notification.objects.create(
        user=user, title=TITLE, body=BODY, created_at=CREATED_AT, sent=False
    )


@pytest.fixture
def tokyo_note(db, tokyo_guest):
    return _note(tokyo_guest)


@pytest.fixture
def london_note(db, london_guest):
    return _note(london_guest)


@pytest.fixture
def walkin_note(db, walkin_guest):
    return _note(walkin_guest)
