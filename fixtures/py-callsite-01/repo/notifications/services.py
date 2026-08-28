def format_notification(notification, locale):
    """Render a notification for display to a guest."""
    return f"[{locale}] {notification.title}: {notification.body}"
