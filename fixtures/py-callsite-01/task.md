# Show guests when a notification was created, in their own timezone

## Context / Why

Guest notifications currently render with no time information at all. Guests
have no way to tell whether "Your room is ready" arrived ten minutes ago or
yesterday afternoon, and reception has been fielding "is this message current?"
questions at check-in. Adding the creation time to the rendered text closes
that gap.

`created_at` is already stored on every notification. `UserProfile.timezone`
already holds the guest's timezone where we have it.

## User story

As a guest, I want each notification to show when it was created, in my own
timezone, so that I can tell at a glance whether it is still relevant.

## Scope

**In scope**

*   The rendered notification text includes the time the notification was
    created.
*   The time is shown in the guest's own timezone, not the server's.
*   This applies consistently everywhere a notification is rendered for a
    guest.

**Out of scope / exclusions**

*   **The nightly digest wording** - `notifications/digest.py`. Marketing owns
    that copy and is revising it in a sibling ticket. Its output must be
    unchanged by this ticket, **including the per-notification lines the digest
    renders itself**. Do not "make it consistent" here.
*   How `created_at` is stored. It stays UTC in the database.
*   Locale-aware date formatting. One format for every locale for now;
    localising it is a separate ticket.
*   Delivery of notifications by push or email. This is display only.
*   Any change to `UserProfile`, `Hotel`, or `Notification` schema. Everything
    needed is already on the models.

## Acceptance Criteria

**Functionality**

*   Wherever a guest sees a rendered notification, the text shows when it was
    created.
*   The time shown is in the guest's own timezone.
*   The rendering is consistent across every surface a guest can reach.
*   The nightly digest's own output is unchanged.

**Format**

```
[en] Room ready: Your room is ready for check-in. (2026-08-27 09:00)
```

**Scenario validations**

*   **Tokyo guest** - *Given* a guest whose timezone is `Asia/Tokyo` and a
    notification created at `2026-08-27T00:00Z`, *when* the notification is
    rendered, *then* the text ends with `(2026-08-27 09:00)`.
*   **London guest** - *Given* the same notification and a guest whose timezone
    is `Europe/London`, *then* the text ends with `(2026-08-27 01:00)`.
*   **Consistency** - *Given* the same notification and the same guest, *then*
    every surface that renders it produces the same string.
*   **Digest untouched** - *Given* the nightly digest runs, *then* the lines it
    renders itself are exactly what they are today.

## Open Questions

1.  **Guests with no timezone.** `UserProfile.timezone` is nullable - walk-in
    guests who never completed online check-in have it unset. For those, I am
    assuming we leave the rendered text exactly as it is today rather than
    guessing a fallback (the hotel's timezone? UTC?). Please confirm before
    anyone picks one, since a wrong guess shows the guest a time that is simply
    incorrect rather than absent.
2.  **Seconds.** The format above is to the minute. Assuming that is enough.

## Notes

Please cover the new behaviour with tests.
