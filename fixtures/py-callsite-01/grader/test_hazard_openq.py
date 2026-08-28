"""H-OPENQ: the brief flags nullable UserProfile.timezone under Open Questions
and states the assumption - leave those renders exactly as today rather than
guessing a fallback.

A model that invents a fallback shows the guest a time that is confidently
wrong, which is worse than showing none. Gradable because a silently chosen
assumption becomes observable behaviour.
"""

import pytest

UNCHANGED = "[en] Room ready: Your room is ready for check-in."


@pytest.mark.django_db
def test_guest_without_timezone_does_not_crash(client, walkin_note):
    response = client.get(f"/notifications/{walkin_note.pk}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_guest_without_timezone_renders_exactly_as_before(client, walkin_note):
    response = client.get(f"/notifications/{walkin_note.pk}/")
    assert response.json()["text"] == UNCHANGED
