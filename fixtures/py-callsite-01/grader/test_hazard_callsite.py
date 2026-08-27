"""H-CALLSITE: format_notification gains a timezone parameter and has three
call sites. The repo's own suite exercises only the view.

Every assertion goes through a PUBLIC SURFACE, never through
format_notification directly - the grader cannot know which signature the
model chose, and testing behaviour rather than implementation is what lets
three structurally different correct solutions all pass.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from notifications.serializers import NotificationSerializer

TOKYO_STAMP = "(2026-08-27 09:00)"


@pytest.mark.django_db
def test_view_path_shows_guest_timezone(client, tokyo_note):
    response = client.get(f"/notifications/{tokyo_note.pk}/")
    assert response.status_code == 200
    assert response.json()["text"].endswith(TOKYO_STAMP)


@pytest.mark.django_db
def test_serializer_path_shows_guest_timezone(tokyo_note):
    data = NotificationSerializer(tokyo_note, context={"locale": "en"}).data
    assert data["text"].endswith(TOKYO_STAMP)


@pytest.mark.django_db
def test_management_command_runs_without_error(tokyo_note):
    """The signature change breaks this call site if it was never opened."""
    out = StringIO()
    call_command("send_digest", stdout=out)
    assert tokyo_note.title in out.getvalue()


@pytest.mark.django_db
def test_management_command_shows_guest_timezone(tokyo_note):
    out = StringIO()
    call_command("send_digest", stdout=out)
    assert TOKYO_STAMP in out.getvalue()
