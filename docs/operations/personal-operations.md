# Personal operations — Wave 13

Open **Reminders** after signing in as the owner. Enter a reminder and a local
PC date/time. Choose once, hourly, every 24 hours or every 7 days. The API also
accepts bounded fixed intervals from 60 seconds to one year, with explicitly
zoned timestamps. Daily intervals are elapsed 24 hours, not a daylight-saving
calendar schedule. Invalid/naive timestamps and likely credential material are
refused. Ordinary chat never silently creates reminders.

ADAM must be open. Closing ADAM or shutting down the PC does not wake it at the
due time. On restart, one overdue update is emitted; recurring jobs skip missed
intervals to the next future occurrence. Job advancement and update insertion
commit together. Duplicate request IDs reuse their receipt; changed fields with
the same ID are denied. Mark reviewed dismisses an update. Cancel withdraws both
the future job and its pending updates. Pause preserves jobs and queues; resume
can deliver overdue reminders. There are 500 retained jobs, 1,000 unread updates,
and 50 dispatches per tick. Completed/acknowledged data is pruned after 30 days;
full queues retain pending jobs for later delivery.

**Scheduling currently supports reminder jobs.** It does not run saved tool plans,
execute terminal commands, send external messages or hold an authentication token
for later use. Review/approve actions through the existing PC tools/task flow.
The background worker rechecks persisted enablement at each dispatch, and owner
API mutations recheck current authentication authority. Guest/demo profiles and
mobile devices cannot create, configure or acknowledge owner reminders.

The desktop shows a generic update badge and an owner-only inbox. The ACTIVE
route follows the selected conversation's primary device if its signed status
poll was received within 30 seconds. Approved mobile devices see only
“ADAM update available. Review on your PC.” No private reminder text or session
ID is sent in that alert. Revocation/handoff or stale/offline presence redirects
the same unacknowledged item to the desktop. Delivery is a visible inbox offer,
not an acoustic or OS delivery acknowledgement. Opening the same item more than
once is possible until the owner marks it reviewed.

There are **no OS push notifications**. Desktop alerts need ADAM running; mobile
alerts need the trusted Android browser open and visible. Neither Windows nor
Android lock screens receive private OS notifications from ADAM. Full desktop
text appears in the unlocked owner inbox; actual OS-lock and phone behavior still
needs the human check. Browser visibility/offline clearing remains in place.

Quiet hours apply to all priorities and defer delivery without dropping the queue.
Enter both times, or blank both. Equal times mean quiet all day. Crossing midnight
works. The offset is explicit minutes east/west of UTC: Pakistan is **300**.
Offsets are fixed; adjust manually when travelling or for daylight saving.

Proactive suggestions default **off**. Opt in to the registered
`unread_reminders` trigger to get one explained suggestion when an owner reminder
has been unread for 24 hours. Cooldown is 24 hours, quiet hours suppress it,
and disabling suggestions withdraws pending suggestions. It reads only this
reminder inbox. There is no file, microphone, browsing or external-account watch.
Unregistered conditions are refused; adding new conditions requires a code change.

Jobs/settings/inbox live in `operations/jobs.sqlite3` in the existing ADAM data
folder. They survive restart and installer upgrades. A damaged optional store
fails closed while local chat stays available; preserve it before repair.
The existing encrypted backup format does **not** include the new operations
store. For a full manual copy, close ADAM first and preserve the whole data folder;
do not copy live SQLite/WAL files independently or overwrite another private profile.

See [Gate 13](gate-13.md) for real desktop/Android validation.
