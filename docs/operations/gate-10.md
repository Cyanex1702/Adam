# Human validation Gate 10

Status: NOT_STARTED. Automated evidence does not pass this gate.
The user requested progression from Wave 9 on 2026-10-08; this authorizes Wave 10
work without representing unobserved Wave 9 native comfort tests as completed.

Use the installed 0.10.0 app with real microphone permission granted by the user.
Begin with headphones and Record voice / Finish recording / transcript review.
Confirm the raw transcript matches what you said, and low-confidence or wrong
recognition can be edited, discarded or replaced with typed text.

Then test Conversation mode with these conditions:

- Quiet speech, fast speech and low volume.
- Slow thinking pauses, incomplete sentences and filler words.
- Fan noise and practical traffic/background noise.
- Urdu/English code-switching; choose recognition language deliberately if needed.
- Read-aloud replies: mhm should continue, stop should cancel, and actually/wait
  corrections should cancel before a replacement request starts.
- Speaker echo without headphones; stop using conversation mode if ADAM mistakes
  its own output or background speech for a request.
- Switch profile, lock and minimize/hide while recording or speaking. Confirm
  capture/playback stop and no obsolete transcript/reply crosses profiles.
- Reset pause style; confirm it does not require persistent personal voice data.
- Try Windows and Kokoro voices, including a multilingual Kokoro reply. Measure
  time from stopping speech to visible transcript/response and first audio.
- Keep a longer conversation and record cutoffs, false turn endings, invented
  words, interruption delay and whether timing feels comfortable.

Record hardware, competing applications, engine, language and examples of any
failure. Gate passes only when extended ordinary use avoids frequent cutoffs,
false turns and silent transcript invention. Wave 11 remains NOT_STARTED.

Pay particular attention to a reply completing as text but failing to speak.
One integrated automated attempt hit that failure; a rerun passed without an
application change. Its original error code was not captured. Record any visible
error notice and current resource load if this recurs.
