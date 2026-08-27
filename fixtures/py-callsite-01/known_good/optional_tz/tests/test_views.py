import pytest


@pytest.mark.django_db
def test_detail_returns_the_rendered_notification(client, notification):
    response = client.get(f"/notifications/{notification.pk}/")
    assert response.status_code == 200
    assert "Room ready" in response.json()["text"]


@pytest.mark.django_db
def test_detail_honours_the_locale_parameter(client, notification):
    response = client.get(f"/notifications/{notification.pk}/?locale=ja")
    assert response.json()["text"].startswith("[ja]")
