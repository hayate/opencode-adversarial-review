from django.core.management.base import BaseCommand

from notifications.digest import digest_subject, format_digest_line
from notifications.models import Notification
from notifications.services import format_notification, guest_timezone


class Command(BaseCommand):
    help = "Render the nightly digest for unsent notifications."

    def handle(self, *args, **options):
        pending = Notification.objects.filter(sent=False).select_related("user")
        self.stdout.write(digest_subject(pending.count()))
        for note in pending:
            self.stdout.write(format_digest_line(note))
            locale = getattr(note.user, "locale", "en")
            self.stdout.write(format_notification(note, locale, tz=guest_timezone(note)))
