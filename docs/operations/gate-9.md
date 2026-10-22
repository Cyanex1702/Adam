# Human Validation Gate 9 — Desktop product

Wave 9 delivers milestones 10.0 and 10.1. Automated results are recorded in
`wave-9-report.md`; human validation remains pending. Wave 10 voice is not started.

1. Open **ADAM Desktop** from the Start menu. Use your existing owner passphrase,
   or create one on a new profile. Check that first launch and errors make sense.
2. Have a normal conversation. Try English and Roman Urdu, Enter to send,
   Shift+Enter for a new line, and Stop response. Check that partial interrupted
   responses are clearly marked. ADAM's model answers remain unverified.
3. Save `/remember preference editor = VS Code`. Find it in Saved memory and
   inspect REPORTED provenance. Close/reopen ADAM, unlock, and resume the saved
   conversation. Your identity and committed history should persist.
4. Switch to fictional demo from Settings. Owner conversations and preferences
   must be absent there; developer entry must be disabled. Lock and sign back
   into owner to return to your real profile.
5. Try avatar off and reduced motion. The orb should reflect work/error/offline
   state, with no pretend emotion, listening or speaking. Resize, minimize and
   reopen the window. Judge responsiveness during actual model use; the rolling
   FPS number is an observation, not a performance guarantee under full CPU load.
6. Open Developer mode and re-enter your passphrase. Inspect model/compute status
   and traces. Unload/reload the model if desired. Restart local service from
   Settings; this locks the UI and preserves saved data. Do not run the terminal
   launcher concurrently on the same managed model port.
7. Use the app for a longer session and report any confusing behavior or failure.

The gate passes when the desktop is comfortable for extended use and has no
unresolved critical/high-severity issue. Automated native-host/process checks do
not replace your judgement about window behavior, visual comfort or sustained
WebView2 performance. Voice/vision and a native tool-approval screen are outside
this wave's shell scope; existing approved tools remain accessible through the
earlier interfaces. Do not interpret an idle orb as an available microphone.

For setup/build and storage details, see `desktop.md`.
