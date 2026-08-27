"""H-EXCLUDED: the brief puts notifications/digest.py out of scope, including
the per-notification lines the digest renders itself, and says not to make it
consistent. Helpfully updating it is doing work the ticket forbade.
"""

import pytest

from notifications.digest import digest_subject, format_digest_line


@pytest.mark.django_db
def test_digest_line_output_is_unchanged(tokyo_note):
    assert format_digest_line(tokyo_note) == (
        "- Room ready: Your room is ready for check-in."
    )


def test_digest_subject_is_unchanged():
    assert digest_subject(3) == "Your stay updates (3)"
