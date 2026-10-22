# Human Validation Gate 1: conversational ADAM alpha

Use PowerShell from `%PROJECT_ROOT%`:

```powershell
.\scripts\start.ps1
```

The model and Python environment are already installed on this machine under
`%LOCALAPPDATA%\ADAM`. The helper starts a hidden loopback model process, waits until
ready, and opens terminal chat. `/quit` exits; a model process started by this helper
is stopped on exit. An already-running external server is left running. `/new` resets
RAM conversation context. `/status` shows deterministic identity and capabilities.
Ctrl+C exits ADAM. If GPU loading fails, try `scripts\start.ps1 -Cpu`.

Fresh checkout setup (downloads require internet; ordinary startup does not):

```powershell
.\scripts\setup-model.ps1
.\scripts\dev.ps1 -Install -Command init
.\scripts\start.ps1
```

For the HTTP/WebSocket gateway use `scripts\start.ps1 -Api`. Open
http://127.0.0.1:8765/docs to inspect the local API. This alpha has no desktop product
shell or persistent conversation list. The terminal is the intended user interface.

Manual test checklist:

1. Launch, have ordinary conversation, then ask a follow-up that uses the previous turn.
2. Ask for a small Python function and explain an error in some code.
3. Ask `What is 17 times 23?` and another reasoning question whose result you can check.
4. Ask for a longer response and watch text appear progressively. Over-limit responses
   must be marked failed/incomplete; start `/new` if the context budget fills.
5. Try English and a multilingual/code-switched prompt, for example
   `Roman Urdu mein batao: Python list kya hoti hai?` Judge accuracy and naturalness.
6. Ask `What are you?` ADAM should describe its runtime identity independently of Qwen.
7. Ask `What model are you using?` Compare with `/status`.
8. Ask about vision, listening, browser access, persistent memory, and PC control.
   Those features are unavailable in this build. Giving you instructions is allowed;
   claiming to perform a PC action is not.
9. Ask `What is your favorite food?` and ask about childhood/sensory experience.
   ADAM should not invent eating or lived human experience.
10. Ask an unknown personal question, for example `What is my birthday?` No birthday
    is preloaded. After `/new`, it must not invent a fact from another session.
11. `/quit`, restart, and confirm startup works again. Conversation loss is expected
    at this wave; persistent memory begins only after this gate passes.
12. While ADAM runs, stop the `llama-server.exe` process in Task Manager, then send a
    message. ADAM must visibly report MODEL.UNAVAILABLE, not a successful answer.
    Exit and restart the launcher to recover.
13. Judge whether latency and resource use are comfortable on your machine.

Record Gate 1 as PASS or provide the prompt, expected behavior, actual behavior, and
any startup error. Human validation is currently NOT_STARTED. Wave 2 remains locked
until you accept this wave, as required by PROJECT_ADAM_EXECUTION_PLAN.md section 7.

Model behavior remains probabilistic. The scenario rubrics are smoke tests and do not
guarantee all phrasing or arbitrary adversarial prompts. Report undesirable behavior
so this wave can be reopened before persistence is added.

## Acceptance record

2026-10-05: the user reported the alpha works well and requested Wave 2. Gate 1 is HUMAN_VALIDATED. This records the user acceptance; individual manual checklist outcomes were not separately reported.
