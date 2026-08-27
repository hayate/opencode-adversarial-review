from zoneinfo import ZoneInfo


def _stamp(notification, tz):
    """Rendered creation time, or nothing when the guest has no timezone.

    Open Question 1 in the ticket: walk-in guests have UserProfile.timezone
    unset. The stated assumption is to leave those renders exactly as they are
    today rather than guessing a fallback, so this returns an empty string.
    """
    if not tz:
        return ""
    local = notification.created_at.astimezone(ZoneInfo(tz))
    return f" ({local.strftime('%Y-%m-%d %H:%M')})"


def guest_timezone(notification):
    profile = getattr(notification.user, "profile", None)
    return getattr(profile, "timezone", None)


def format_notification(notification, locale):
    """Render a notification for display to a guest."""
    stamp = _stamp(notification, guest_timezone(notification))
    return f"[{locale}] {notification.title}: {notification.body}{stamp}"
