"""Nightly digest rendering.

Deliberately separate from services.format_notification: Marketing owns the
digest wording and it is versioned against their copy deck.
"""

DIGEST_SUBJECT = "Your stay updates"


def digest_subject(count):
    return f"{DIGEST_SUBJECT} ({count})"


def format_digest_line(notification):
    """One line of the nightly digest."""
    return f"- {notification.title}: {notification.body}"
