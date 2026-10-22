# Human validation Gate 11

Status: NOT_STARTED. The user requested progression on 2026-10-08. This authorizes
Wave 11 implementation; it does not establish that Gate 10 acoustics passed.
Spatial audio (12.2) is DEFERRED for the current mono capture path.

Use the installed 0.11.0 desktop with two consenting real people. Enroll the owner
and one guest after fresh owner reauthentication, following [speakers.md](speakers.md).
Start with headphones and reviewed push-to-talk. Record examples, competing load,
language, recognition mistakes, false speaker matches and response latency.

- Owner versus known guest, then an unknown guest. Uncertainty must require review.
- Background speech without addressing ADAM in conversation mode.
- Simultaneous requests and one speaker confusing another's command. Require
  separate repetition when overlap cannot be understood; do not accept merged commands.
- Guest issuing a privileged command while the owner is present. Voice matches
  must never supply authentication or bypass explicit action approval.
- Owner interruption while a guest speaks; visible Stop must always remain usable.
- Replayed owner audio and, if practical, cloned speech against a sensitive request.
  A match can occur; existing password/session/approval boundaries must still apply.
- Speaker changes mid-session, short utterances, pauses and low-volume speech.
- Remove a template and confirm subsequent speech is unknown. Switch profiles,
  lock or hide while recording; obsolete results must not cross profiles.
- Try Urdu/English code-switching and a longer conversation. Record false rejects
  and false accepts rather than treating a displayed similarity as a probability.

Pass only when owner/guest boundaries survive real social noise and uncertain
identity reduces automatic behavior. Automated prerecorded fixtures do not pass
this gate. Gate 10's unresolved intermittent reply-to-audio observation remains
part of real-use validation; no fix for its uncaptured original cause is claimed.
