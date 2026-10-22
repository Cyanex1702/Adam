import argparse
import asyncio
import getpass
import io
import json
import secrets
import sys

from adam.compute.migration import ModelController
from adam.core.config import Settings, load_settings
from adam.core.contracts import SessionId
from adam.core.migrations import migrate
from adam.core.runtime import ChatRequest, Runtime
from adam.core.storage import ConversationStore
from adam.knowledge.contracts import SourceRequest
from adam.knowledge.embedding import EmbeddingUnavailable
from adam.knowledge.parsing import IngestionError
from adam.knowledge.retrieval import QueryRequest, RetrievalService
from adam.knowledge.service import KnowledgeService
from adam.models.llama_cpp import LlamaCppProvider
from adam.security.auth import AuthError, AuthManager
from adam.security.gateway import seed_demo
from adam.security.policy import Mode, Principal
from adam.security.vault import Vault, VaultError
from adam.tools.terminal import handle_command


async def chat_loop(settings: Settings, mode: Mode = "owner") -> None:
    def make_runtime(selected: Mode) -> Runtime:
        principal = Principal(
            selected,
            selected,
            selected == "owner",
            selected == "owner",
            profile_id="terminal-" + secrets.token_hex(8),
        )
        created = Runtime(settings, LlamaCppProvider(settings.model), principal)
        ModelController(created.compute)
        if selected == "demo":
            seed_demo(created)
        return created

    runtime = make_runtime(mode)
    await runtime.compute.controller.startup()
    auth = AuthManager(settings.data_dir)
    vault = (
        Vault(settings.data_dir, settings.vault_backend, settings.vault_enabled)
        if mode == "owner"
        else None
    )
    await runtime.consolidation.start(settings.consolidation_interval_seconds)
    session_id: SessionId | None = None
    namespace = "demo" if mode == "demo" else "default"
    print("ADAM Alpha | /new | /sessions | /resume ID | /status | /quit")
    print("Conversations persist locally. Never submit credentials. Traces omit chat text.")
    print('/ingest "PATH" | /namespace NAME | /ask QUESTION | /inspect QUESTION | /reindex')
    print(f"[MODE: {mode.upper()}] /mode owner|guest|demo | /auth-init (local owner only)")
    print("/vault status|unlock|lock|handles|put PURPOSE|delete HANDLE (owner reauthentication)")
    print("/tools | /tool JSON | /actions | /approve-action ID DIGEST | /run-action ID | /undo ID")
    print("/plan diagnose . | /plan organize . | /tasks | /approve-task ID DIGEST | /run-task ID")
    try:
        while True:
            try:
                text = await asyncio.to_thread(input, "\nYou: ")
            except EOFError:
                return
            if text.strip() == "/quit":
                return
            if await handle_command(text, runtime, auth):
                continue
            if text.startswith("/vault "):
                if mode != "owner" or vault is None:
                    print("[POLICY.OWNER_REQUIRED]")
                    continue
                credential = value = ""
                try:
                    credential = await asyncio.to_thread(getpass.getpass, "Owner passphrase: ")
                    auth.verify(credential)
                    principal = Principal(elevated=True)
                    command = text[7:].strip()
                    if command == "unlock":
                        value = (
                            await asyncio.to_thread(getpass.getpass, "Vault passphrase: ")
                            if vault.backend == "fernet"
                            else ""
                        )
                        await asyncio.to_thread(vault.unlock, principal, value)
                        print("Vault unlocked.")
                    elif command == "status":
                        print(json.dumps(vault.status(principal)))
                    elif command == "lock":
                        vault.lock_vault(principal)
                        print("Vault locked.")
                    elif command == "handles":
                        print(json.dumps(vault.list_handles(principal)))
                    elif command.startswith("put "):
                        value = await asyncio.to_thread(getpass.getpass, "Secret value (hidden): ")
                        print(vault.put(principal, command[4:].strip(), value))
                    elif command.startswith("delete "):
                        print(json.dumps({"deleted": vault.delete(principal, command[7:].strip())}))
                    else:
                        print("Unknown vault command.")
                except (AuthError, VaultError) as exc:
                    print(f"[{exc.code}]")
                finally:
                    credential = value = ""
                continue
            if text.strip() == "/auth-init":
                if mode != "owner":
                    print("[POLICY.OWNER_REQUIRED]")
                    continue
                try:
                    password = await asyncio.to_thread(
                        getpass.getpass, "New owner passphrase (12+ characters): "
                    )
                    confirm = await asyncio.to_thread(getpass.getpass, "Confirm owner passphrase: ")
                    if password != confirm:
                        print("Passphrases do not match.")
                    else:
                        auth.initialize(password)
                        print(
                            "Owner authentication configured. "
                            "Passphrase is never stored as plaintext."
                        )
                except AuthError as exc:
                    print(f"[{exc.code}]")
                finally:
                    password = confirm = ""
                continue
            if text.startswith("/mode "):
                selected = text[6:].strip().lower()
                if selected not in {"owner", "guest", "demo"}:
                    print("Choose owner, guest or demo.")
                    continue
                if selected == mode:
                    print(f"[MODE: {mode.upper()}]")
                    continue
                try:
                    if selected == "owner":
                        password = await asyncio.to_thread(getpass.getpass, "Owner passphrase: ")
                        auth.verify(password)
                        password = ""
                    await runtime.consolidation.stop()
                    runtime.retrieval.close()
                    await runtime.provider.unload()
                    mode = selected  # type: ignore[assignment]
                    runtime = make_runtime(mode)
                    await runtime.compute.controller.startup()
                    vault = (
                        Vault(settings.data_dir, settings.vault_backend, settings.vault_enabled)
                        if mode == "owner"
                        else None
                    )
                    await runtime.consolidation.start(settings.consolidation_interval_seconds)
                    session_id = None
                    namespace = "demo" if mode == "demo" else "default"
                    print(f"[MODE: {mode.upper()}] New isolated conversation.")
                except AuthError as exc:
                    print(f"[{exc.code}]")
                continue
            if text.strip() == "/status":
                health = await runtime.provider.health_check()
                print(
                    json.dumps(
                        runtime.identity.describe(
                            runtime.provider.get_capabilities(),
                            settings.features.text,
                            health.status == "HEALTHY",
                            settings.knowledge.enabled,
                            tools_enabled=True,
                            voice_enabled=settings.features.voice,
                            speaker_enabled=settings.features.speaker_id,
                        ),
                        indent=2,
                    )
                )
                continue
            if text.strip() == "/new":
                if session_id:
                    runtime.sessions.close(session_id)
                session_id = None
                print("New conversation.")
                continue
            if not text.strip():
                continue
            if text.startswith("/namespace "):
                try:
                    namespace = QueryRequest(
                        query="validate", namespace=text[11:].strip()
                    ).namespace
                    print(f"Knowledge namespace: {namespace}")
                except ValueError:
                    print("Invalid namespace: use 1–64 letters, digits, underscores or hyphens.")
                continue
            if text.startswith("/inspect ") or text.strip() == "/reindex":
                try:
                    result = (
                        (
                            await asyncio.to_thread(
                                runtime.retrieval.search,
                                QueryRequest(query=text[9:].strip(), namespace=namespace),
                            )
                        ).model_dump(mode="json")
                        if text.startswith("/inspect ")
                        else await asyncio.to_thread(runtime.retrieval.reindex)
                    )
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                except (EmbeddingUnavailable, ValueError) as exc:
                    print(f"[RAG.UNAVAILABLE] {exc}")
                continue
            if text.startswith("/ingest ") or text.strip() in {"/sources", "/refresh"}:
                if text.startswith("/ingest ") and mode != "owner":
                    print("[POLICY.OWNER_REQUIRED] External file ingestion is owner-only.")
                    continue
                try:
                    if text.startswith("/ingest "):
                        print(
                            runtime.knowledge.ingest(
                                SourceRequest(path=text[8:].strip().strip('"'), namespace=namespace)
                            ).model_dump_json(indent=2)
                        )
                    else:
                        records = (
                            runtime.knowledge.refresh(namespace)
                            if text.strip() == "/refresh"
                            else runtime.knowledge.sources(namespace)
                        )
                        print(
                            json.dumps(
                                [source.model_dump(mode="json") for source in records], indent=2
                            )
                        )
                except IngestionError as exc:
                    print(f"[RAG.INGEST_REJECTED] {exc}")
                continue
            if text.strip() == "/working":
                print(json.dumps(runtime.store.get(session_id) if session_id else {}, indent=2))
                continue
            if text.startswith(("/instruction ", "/task ")):
                if session_id is None:
                    from adam.core.contracts import TraceId, new_id

                    session_id = runtime.sessions.resolve(None, TraceId(new_id())).session_id
                state = runtime.store.working(session_id)
                if text.startswith("/instruction "):
                    state.instructions.append(text[13:].strip())
                else:
                    state.objective = text[6:].strip()
                try:
                    runtime.store.set_working(session_id, state)
                    print("Session working state saved.")
                except ValueError:
                    print("Invalid working state or credential-bearing input.")
                continue
            if text.strip() == "/sessions":
                print(json.dumps(runtime.store.list_sessions(), indent=2))
                continue
            if text.startswith("/resume "):
                selected = SessionId(text[8:].strip())
                if runtime.sessions.reopen(selected):
                    session_id = selected
                    print(f"Resumed {session_id}")
                else:
                    print("Session unavailable.")
                continue
            print("ADAM: ", end="", flush=True)
            async for event in runtime.stream(
                ChatRequest(
                    text=text,
                    session_id=session_id,
                    knowledge_namespace=namespace if text.startswith("/ask ") else None,
                )
            ):
                if event.session_id:
                    session_id = event.session_id
                if event.event_type == "agent.token":
                    print(event.payload["text"], end="", flush=True)
                elif event.event_type == "agent.error":
                    print(f"\n[FAILED / partial response incomplete] {event.payload['error']}")
            print()
    finally:
        await runtime.consolidation.stop()
        await runtime.provider.unload()
        runtime.retrieval.close()


def main() -> None:
    for stream in [sys.stdin, sys.stdout, sys.stderr]:
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ADAM local text runtime")
    parser.add_argument(
        "command",
        choices=[
            "serve",
            "init",
            "chat",
            "ingest",
            "sources",
            "refresh",
            "retrieve",
            "reindex",
            "ask",
        ],
        default="serve",
        nargs="?",
    )
    parser.add_argument("path", nargs="?")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--mode", choices=["owner", "guest", "demo"], default="owner")
    args = parser.parse_args()
    try:
        settings = load_settings()
    except (ValueError, OSError):
        print("[RECOVERY_READ_ONLY / CONFIG.INVALID] Use python -m adam.resilience.cli recovery")
        return
    from adam.resilience.recovery import inspect

    state = inspect(settings)
    if args.command != "init" and state["mode"] != "HEALTHY":
        print(
            json.dumps(
                {
                    "status": "RECOVERY_READ_ONLY",
                    "issues": state["issues"],
                    "next": "python -m adam.resilience.cli recovery",
                }
            )
        )
        return
    if args.mode != "owner" and args.command not in {"chat", "serve"}:
        parser.error("Non-owner modes support chat only; serve uses authenticated API sessions")
    try:
        if args.command == "serve":
            import uvicorn

            from adam.api.app import create_app

            uvicorn.run(create_app(settings), host="127.0.0.1", port=8765, access_log=False)
        elif args.command == "chat":
            asyncio.run(chat_loop(settings, args.mode))
        elif args.command in {"ingest", "sources", "refresh", "retrieve", "reindex", "ask"}:
            knowledge = KnowledgeService(
                ConversationStore(settings.data_dir / "runtime.sqlite3"), settings.knowledge
            )
            retrieval = RetrievalService(knowledge)
            try:
                if args.command == "ingest":
                    if not args.path:
                        parser.error("ingest requires PATH")
                    print(
                        knowledge.ingest(
                            SourceRequest(path=args.path, namespace=args.namespace)
                        ).model_dump_json(indent=2)
                    )
                elif args.command in {"retrieve", "reindex", "ask"}:
                    if args.command in {"retrieve", "ask"}:
                        if not args.path:
                            parser.error("retrieve requires a quoted QUESTION")
                        from adam.knowledge.grounding import GroundingService

                        request = QueryRequest(query=args.path, namespace=args.namespace)
                        result = (
                            GroundingService(retrieval).answer(request)
                            if args.command == "ask"
                            else retrieval.search(request)
                        ).model_dump(mode="json")
                    else:
                        result = retrieval.reindex()
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    records = (
                        knowledge.refresh(args.namespace)
                        if args.command == "refresh"
                        else knowledge.sources(args.namespace)
                    )
                    print(
                        json.dumps([source.model_dump(mode="json") for source in records], indent=2)
                    )
            except (IngestionError, EmbeddingUnavailable, ValueError) as exc:
                print(f"[RAG.INGEST_REJECTED] {exc}")
                raise SystemExit(1) from None
            finally:
                retrieval.close()
        else:
            migrate(settings.data_dir / "runtime.sqlite3")
            print("ADAM metadata database initialized.")
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
