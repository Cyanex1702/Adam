import asyncio
import sqlite3
from collections import OrderedDict
from collections.abc import AsyncGenerator
from contextlib import aclosing, suppress
from dataclasses import dataclass, field
from time import perf_counter

from pydantic import Field

from adam.compute.contracts import ComputeError
from adam.compute.resources import ManagedProvider
from adam.core.config import Settings
from adam.core.contracts import (
    AdamError,
    Contract,
    ErrorEnvelope,
    EventEnvelope,
    SessionId,
    TraceId,
    new_id,
)
from adam.core.privacy import contains_secret, protected_suffix_length, safe_transcript
from adam.core.storage import ConversationStore
from adam.core.working import ContextBuilder
from adam.identity.service import IdentityService
from adam.intelligence.service import Intelligence, PersonalError
from adam.knowledge.grounding import GroundingService
from adam.knowledge.retrieval import QueryRequest, RetrievalService
from adam.knowledge.service import KnowledgeService
from adam.memory.consolidation import ConsolidationService
from adam.memory.service import MemoryCommandError, MemoryService, parse_command
from adam.models.base import Message, ModelProvider, ModelRegistry, closing_stream
from adam.observability.service import TraceService as TraceService
from adam.security.policy import Principal
from adam.security.request import check_authority
from adam.tasks.service import TaskService
from adam.tools.service import ActionService


class ChatRequest(Contract):
    text: str = Field(min_length=1, max_length=16000)
    session_id: SessionId | None = None
    sensitivity: str = "PERSONAL"
    knowledge_namespace: str | None = Field(default=None, pattern=r"^[\w-]{1,64}$")
    careful: bool = False


@dataclass
class Session:
    session_id: SessionId
    messages: list[Message] = field(default_factory=list)
    busy: bool = False


class SessionManager:
    def __init__(self, maximum: int, store: ConversationStore, recent_turns: int) -> None:
        self.maximum = maximum
        self.store = store
        self.recent_turns = recent_turns
        self.sessions: OrderedDict[SessionId, Session] = OrderedDict()

    def _make_room(self, trace_id: TraceId) -> None:
        if len(self.sessions) < self.maximum:
            return
        idle = next((sid for sid, session in self.sessions.items() if not session.busy), None)
        if idle is not None:
            del self.sessions[idle]
            return
        raise AdamError(
            ErrorEnvelope(
                code="SESSION.CAPACITY",
                trace_id=trace_id,
                message="All active sessions are busy. Retry after a response finishes.",
                retryable=True,
            )
        )

    def resolve(self, session_id: SessionId | None, trace_id: TraceId) -> Session:
        if session_id is not None:
            stored = self.store.get(session_id)
            if not stored or stored["closed"]:
                raise AdamError(
                    ErrorEnvelope(
                        code="SESSION.NOT_FOUND",
                        trace_id=trace_id,
                        message="Session not found or closed. Start or resume a conversation.",
                    )
                )
            if session_id not in self.sessions:
                self._make_room(trace_id)
                self.sessions[session_id] = Session(
                    session_id, self.store.recent(session_id, self.recent_turns)
                )
            session = self.sessions[session_id]
        else:
            self._make_room(trace_id)
            session = Session(SessionId(new_id()))
            self.store.create(session.session_id)
            self.sessions[session.session_id] = session
        if session.busy:
            raise AdamError(
                ErrorEnvelope(
                    code="SESSION.BUSY",
                    trace_id=trace_id,
                    message="A response is already running in this session.",
                    retryable=True,
                )
            )
        self.sessions.move_to_end(session.session_id)
        return session

    def close(self, session_id: SessionId) -> bool:
        session = self.sessions.get(session_id)
        if session is not None and session.busy:
            return False
        self.sessions.pop(session_id, None)
        return self.store.close(session_id)

    def reopen(self, session_id: SessionId) -> bool:
        session = self.sessions.get(session_id)
        if session and session.busy:
            return False
        return self.store.reopen(session_id)


class Runtime:
    def __init__(
        self, settings: Settings, provider: ModelProvider, principal: Principal | None = None
    ) -> None:
        self.settings = settings
        self.compute = (
            provider
            if isinstance(provider, ManagedProvider)
            else ManagedProvider(provider, settings)
        )
        provider = self.compute
        self.principal = principal or Principal()
        if self.principal.mode != "owner":
            directory = (
                settings.data_dir / "profiles" / self.principal.mode / self.principal.profile_id
            )
            self.settings = settings.model_copy(
                update={
                    "data_dir": directory,
                    "identity_dir": None,
                    "knowledge": settings.knowledge.model_copy(
                        update={"allowed_roots": [directory / "samples"]}
                    ),
                }
            )
        settings = self.settings
        self.provider: ModelProvider = provider
        self.registry = ModelRegistry(provider)
        self.store = ConversationStore(settings.data_dir / "runtime.sqlite3", settings.recent_turns)
        self.sessions = SessionManager(settings.max_sessions, self.store, settings.recent_turns)
        self.traces = TraceService(settings.data_dir, settings.tracing)
        identity_directory = settings.identity_dir
        if identity_directory is None and (settings.data_dir / "identity").exists():
            identity_directory = settings.data_dir / "identity"
        self.identity = IdentityService(identity_directory)
        self.memories = MemoryService(self.store, self.principal)
        self.consolidation = ConsolidationService(self.memories)
        self.consolidation.background_runner = self.compute.background
        self.knowledge = KnowledgeService(self.store, settings.knowledge)
        self.retrieval = RetrievalService(self.knowledge, principal=self.principal)
        self.grounding = GroundingService(self.retrieval)
        self.actions = ActionService(settings.data_dir)
        self.actions.traces = self.traces
        self.actions.readers["memory.search"] = lambda args: {
            "records": [
                item.model_dump(mode="json") for item in self.memories.search(str(args["query"]))
            ]
        }
        self.actions.readers["knowledge.search"] = lambda args: self.retrieval.search(
            QueryRequest(query=str(args["query"]), namespace=str(args["namespace"]))
        ).model_dump(mode="json")
        self.tasks = TaskService(settings.data_dir, self.actions)
        self.context = ContextBuilder(
            provider, provider.get_context_limit(), settings.model.max_tokens
        )

    def system_prompt(self) -> str:
        return (
            f"Trusted runtime mode: {self.principal.mode}. "
            + (
                "This is a synthetic demo profile, not the real owner's data. "
                if self.principal.mode == "demo"
                else "This guest profile has no owner-store access. "
                if self.principal.mode == "guest"
                else ""
            )
            + self.identity.prompt(
                self.provider.get_capabilities(),
                self.settings.features.text,
                self.settings.knowledge.enabled,
                tools_enabled=True,
                voice_enabled=self.settings.features.voice,
                speaker_enabled=self.settings.features.speaker_id,
                mobile_enabled=self.settings.features.mobile_mesh,
            )
            + " Current compute envelope (runtime state, not personal memory): "
            + str(self.compute.envelope())
        )

    async def stream(self, request: ChatRequest) -> AsyncGenerator[EventEnvelope, None]:
        try:
            async with self.compute.turn(("analyze " if request.careful else "") + request.text):
                self.context = ContextBuilder(
                    self.provider,
                    self.provider.get_context_limit(),
                    self.compute.settings.model.max_tokens,
                )
                async with aclosing(self._stream(request)) as stream:
                    async for event in stream:
                        yield event
        except ComputeError as error:
            yield EventEnvelope(
                event_type="agent.error",
                trace_id=TraceId(new_id()),
                payload={"error": {"code": error.code}, "state": "DEGRADED"},
            )

    async def _stream(self, request: ChatRequest) -> AsyncGenerator[EventEnvelope, None]:
        trace_id = TraceId(new_id())
        session: Session | None = None
        started = perf_counter()
        status = "FAILED"
        error_code: str | None = None
        model = self.provider.get_capabilities()
        answer_provider = model.model_id
        locked = False
        lease_task: asyncio.Task[None] | None = None
        lease_lost = asyncio.Event()

        def write_trace() -> None:
            self.traces.record(
                EventEnvelope(
                    event_type="agent.turn_trace",
                    trace_id=trace_id,
                    session_id=session.session_id if session else None,
                    payload={
                        "status": status,
                        "error_code": error_code,
                        "model": model.model_dump(),
                        "answer_provider": answer_provider,
                        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                    },
                )
            )

        def point(
            subsystem: str,
            event: str,
            state: str,
            *,
            duration_ms: float | None = None,
            references: list[str] | None = None,
            metrics: dict[str, int | float | bool] | None = None,
        ) -> None:
            self.traces.emit(
                str(trace_id),
                subsystem,
                event,
                state,
                duration_ms=duration_ms,
                references=references,
                metrics=metrics,
            )

        try:
            if request.sensitivity not in {
                "PUBLIC",
                "PERSONAL",
                "PRIVATE",
                "CONFIDENTIAL",
            } or contains_secret(request.text):
                raise AdamError(
                    ErrorEnvelope(
                        code="PRIVACY.SECRET_REJECTED",
                        trace_id=trace_id,
                        message="Do not submit credentials. Use a non-secret placeholder.",
                    )
                )
            if not self.settings.features.text:
                raise AdamError(
                    ErrorEnvelope(
                        code="CAPABILITY.DISABLED",
                        trace_id=trace_id,
                        message="Text generation is disabled in configuration.",
                    )
                )
            if not request.text.strip():
                raise AdamError(
                    ErrorEnvelope(
                        code="INPUT.INVALID",
                        trace_id=trace_id,
                        message="Enter a non-empty message.",
                    )
                )
            session = self.sessions.resolve(request.session_id, trace_id)
            point("runtime", "session", "RESOLVED", references=[str(session.session_id)])
            if not self.store.acquire(session.session_id, trace_id):
                raise AdamError(
                    ErrorEnvelope(
                        code="SESSION.BUSY",
                        trace_id=trace_id,
                        message="Session is active in another runtime. Retry shortly.",
                        retryable=True,
                    )
                )
            session.busy = True
            locked = True

            async def renew_lease() -> None:
                assert session is not None
                while True:
                    await asyncio.sleep(20)
                    try:
                        if not await asyncio.to_thread(
                            self.store.renew, session.session_id, trace_id
                        ):
                            lease_lost.set()
                            return
                    except (sqlite3.Error, OSError):
                        lease_lost.set()
                        return

            lease_task = asyncio.create_task(renew_lease())
            if request.text.startswith("/ask ") or request.knowledge_namespace is not None:
                answer_provider = "grounded_source_service"
                stage_started = perf_counter()
                try:
                    query = (
                        request.text[5:].strip()
                        if request.text.startswith("/ask ")
                        else request.text
                    )
                    grounded = await asyncio.to_thread(
                        self.grounding.answer,
                        QueryRequest(
                            query=query, namespace=request.knowledge_namespace or "default"
                        ),
                    )
                    await asyncio.to_thread(self.knowledge.refresh)
                    point(
                        "knowledge",
                        "retrieval",
                        grounded.status,
                        duration_ms=(perf_counter() - stage_started) * 1000,
                        references=[str(item.chunk.chunk_id) for item in grounded.citations],
                        metrics={
                            "evidence_count": len(grounded.citations),
                            "sufficient": grounded.sufficiency.sufficient,
                        },
                    )
                    status = "PREPARED_RAG_ANSWER"
                    write_trace()
                    if lease_lost.is_set() or not self.store.renew(session.session_id, trace_id):
                        raise ValueError("Session lease lost.")
                    with self.store.connect() as db:
                        check_authority()
                        db.execute("BEGIN IMMEDIATE")
                        row = db.execute(
                            "SELECT value FROM runtime_metadata WHERE key='knowledge_revision'"
                        ).fetchone()
                        if (int(row[0]) if row else 0) != grounded.retrieval.revision:
                            raise ValueError("Knowledge changed; retry.")
                        self.store.append_in(
                            db,
                            session.session_id,
                            request.text,
                            grounded.text,
                            trace_id,
                            "grounded_source_service",
                        )
                except ValueError:
                    raise AdamError(
                        ErrorEnvelope(
                            code="RAG.QUERY_REJECTED",
                            trace_id=trace_id,
                            message="Invalid query or sources/session changed; inspect and retry.",
                            retryable=True,
                        )
                    ) from None
                status = "SUCCEEDED"
                yield EventEnvelope(
                    event_type="agent.started",
                    trace_id=trace_id,
                    session_id=session.session_id,
                    payload={"state": "RETRIEVING", "provider": "grounded_source_service"},
                )
                yield EventEnvelope(
                    event_type="agent.token",
                    trace_id=trace_id,
                    session_id=session.session_id,
                    payload={"text": grounded.text},
                )
                yield EventEnvelope(
                    event_type="agent.completed",
                    trace_id=trace_id,
                    session_id=session.session_id,
                    payload={
                        "text": grounded.text,
                        "result": grounded.model_dump(mode="json"),
                        "epistemic_status": grounded.epistemic_status,
                        "provenance": grounded.policy,
                    },
                )
                return
            personal_command, _, personal_query = request.text.strip().partition(" ")
            if personal_command in {"/graph", "/timeline", "/briefing", "/goals"}:
                if self.principal.mode == "guest":
                    raise AdamError(
                        ErrorEnvelope(
                            code="POLICY.GUEST_READ_ONLY",
                            trace_id=trace_id,
                            message="Use an owner or fictional demo profile.",
                        )
                    )
                personal = Intelligence(self.memories)
                answer_provider = "deterministic_personal_service"
                try:
                    result = (
                        await asyncio.to_thread(personal.graph, personal_query)
                        if personal_command == "/graph"
                        else await asyncio.to_thread(personal.timeline, personal_query)
                        if personal_command == "/timeline"
                        else await asyncio.to_thread(personal.briefing)
                    )
                except PersonalError as exc:
                    raise AdamError(
                        ErrorEnvelope(code=exc.code, trace_id=trace_id, message=exc.code)
                    ) from None
                if personal_command == "/graph":
                    rows = [
                        f"{i['subject']} -> {i['relation']} -> {i['object']} "
                        f"({i['epistemic_status']} annotation; source {i['memory_id']}, "
                        f"{i['source_status']})"
                        for i in result["links"][:10]
                    ]
                elif personal_command == "/timeline":
                    rows = [
                        f"{i['valid_from']}: {i['key']} = {i['content']} "
                        f"({i['status']}, {i['epistemic_status']}; {i['memory_id']})"
                        for i in result["events"][:10]
                    ]
                else:
                    rows = [
                        f"{i['title']}: {i['progress']}% ({i['status']})"
                        for i in result["active_goals"][:10]
                    ]
                    rows += [
                        "INFERRED routine: " + i["description"]
                        for i in result["routine_candidates"][:5]
                    ]
                answer = (
                    "Recorded personal evidence; annotations/inferences "
                    "do not override source facts.\n"
                    + ("\n".join(rows) if rows else "No matching supported records.")
                )[:8000]
                with self.store.connect() as db:
                    check_authority()
                    self.store.append_in(
                        db,
                        session.session_id,
                        request.text,
                        answer,
                        trace_id,
                        "deterministic_personal_service",
                    )
                status = "SUCCEEDED"
                point("personal", "query", "SUCCEEDED")
                yield EventEnvelope(
                    event_type="agent.completed",
                    trace_id=trace_id,
                    session_id=session.session_id,
                    payload={
                        "text": answer,
                        "result": result,
                        "epistemic_status": "REPORTED",
                        "provenance": "personal source evidence",
                    },
                )
                return
            command = parse_command(request.text)
            if command:
                stage_started = perf_counter()
                if self.principal.mode == "guest":
                    raise AdamError(
                        ErrorEnvelope(
                            code="POLICY.GUEST_READ_ONLY",
                            trace_id=trace_id,
                            message="Guest mode cannot run memory commands.",
                        )
                    )
                answer_provider = "deterministic_memory_service"
                status = "PREPARED_MEMORY_COMMAND"
                write_trace()
                try:
                    with self.store.connect() as db:
                        check_authority()
                        db.execute("BEGIN IMMEDIATE")
                        manager = (
                            self.consolidation
                            if command.action
                            in {
                                "candidates",
                                "accept_candidate",
                                "reject_candidate",
                                "consolidate",
                                "archive",
                                "pin",
                                "unpin",
                            }
                            else self.memories
                        )
                        answer, result = manager.execute(db, command, session.session_id, trace_id)
                        if command.action not in {"show", "why", "candidates"}:
                            self.store.bump_memory_revision(db)
                        self.store.append_in(
                            db,
                            session.session_id,
                            request.text,
                            answer,
                            trace_id,
                            "deterministic_memory_service",
                        )
                except MemoryCommandError as exc:
                    raise AdamError(
                        ErrorEnvelope(
                            code="MEMORY.INVALID_COMMAND", trace_id=trace_id, message=str(exc)
                        )
                    ) from None
                except ValueError:
                    raise AdamError(
                        ErrorEnvelope(
                            code="MEMORY.INVALID_COMMAND",
                            trace_id=trace_id,
                            message="Use an exact memory ID or key and valid command syntax.",
                        )
                    ) from None
                session.messages = self.store.recent(session.session_id, self.settings.recent_turns)
                status = "SUCCEEDED"
                point(
                    "memory",
                    "command",
                    "SUCCEEDED",
                    duration_ms=(perf_counter() - stage_started) * 1000,
                )
                yield EventEnvelope(
                    event_type="agent.started",
                    trace_id=trace_id,
                    session_id=session.session_id,
                    payload={"state": "MEMORY", "provider": "memory_service"},
                )
                yield EventEnvelope(
                    event_type="agent.token",
                    trace_id=trace_id,
                    session_id=session.session_id,
                    payload={"text": answer},
                )
                yield EventEnvelope(
                    event_type="agent.completed",
                    trace_id=trace_id,
                    session_id=session.session_id,
                    payload={
                        "text": answer,
                        "result": result,
                        "epistemic_status": "VERIFIED",
                        "provenance": "deterministic_memory_service; "
                        "owner claims retain their own reported status",
                    },
                )
                return
            stage_started = perf_counter()
            health = await self.provider.health_check()
            point(
                "model",
                "health",
                health.status,
                duration_ms=(perf_counter() - stage_started) * 1000,
            )
            if health.status != "HEALTHY":
                raise AdamError(
                    ErrorEnvelope(
                        code=health.reason or "MODEL.UNAVAILABLE",
                        message="The configured local model is not ready. Check the model server.",
                        trace_id=trace_id,
                        retryable=True,
                    )
                )
            memory_revision = self.store.memory_revision()
            state = self.store.working(session.session_id)
            if request.text.lower().startswith("for this conversation"):
                state.instructions.append(request.text)
                self.store.set_working(session.session_id, state)
            stored = self.store.get(session.session_id)
            assert stored is not None
            session.messages = self.store.recent(session.session_id, self.settings.recent_turns)
            stage_started = perf_counter()
            memory_context = self.memories.context(request.text, session.session_id)
            point(
                "memory",
                "retrieval",
                "FILTERED",
                duration_ms=(perf_counter() - stage_started) * 1000,
                metrics={"context_bytes": len(memory_context.encode("utf-8"))},
                references=[item.memory_id for item in self.memories.search(request.text, limit=6)],
            )
            stage_started = perf_counter()
            messages, budget = await self.context.build(
                self.system_prompt(),
                state,
                stored["summary"],
                session.messages,
                request.text,
                trace_id,
                memories=memory_context,
            )
            point(
                "context",
                "budget",
                "PREPARED",
                duration_ms=(perf_counter() - stage_started) * 1000,
                metrics={
                    "input_tokens": budget.input_tokens,
                    "reserve": budget.response_reserve,
                    "dropped_turns": budget.dropped_turns,
                    "limit": budget.context_limit,
                },
            )
            self.store.set_budget(session.session_id, budget)

            def event(kind: str, payload: dict[str, object]) -> EventEnvelope:
                return EventEnvelope(
                    event_type=kind,
                    trace_id=trace_id,
                    session_id=session.session_id if session else None,
                    payload=payload,
                )

            yield event(
                "agent.started",
                {
                    "model": model.model_dump(),
                    "state": "THINKING",
                    "context_budget": budget.model_dump(),
                    "model_selection": self.compute.controller.library.last_route
                    if self.compute.controller
                    else None,
                },
            )
            chunks: list[str] = []
            pending_output = ""
            size = 0
            stage_started = perf_counter()
            first_token = True
            from adam.models.review import reviewed_stream

            review_statistics: dict[str, object] = {}
            output_stream = (
                reviewed_stream(
                    self.provider,
                    messages,
                    trace_id,
                    self.compute.settings.model.max_tokens,
                    review_statistics,
                )
                if request.careful
                else self.provider.stream(messages, trace_id)
            )
            async with closing_stream(output_stream) as model_stream:
                async for chunk in model_stream:
                    if first_token:
                        point(
                            "model",
                            "first_token",
                            "RECEIVED",
                            duration_ms=(perf_counter() - stage_started) * 1000,
                        )
                        first_token = False
                    check_authority()
                    if lease_lost.is_set():
                        raise AdamError(
                            ErrorEnvelope(
                                code="SESSION.LEASE_LOST",
                                trace_id=trace_id,
                                message="Session lock was lost. This turn was not saved.",
                                retryable=True,
                            )
                        )
                    chunks.append(chunk)
                    if contains_secret("".join(chunks)):
                        raise AdamError(
                            ErrorEnvelope(
                                code="PRIVACY.SECRET_OUTPUT",
                                trace_id=trace_id,
                                message="Credential-bearing model output was blocked.",
                            )
                        )
                    size += len(chunk)
                    if size > 256000:
                        raise AdamError(
                            ErrorEnvelope(
                                code="MODEL.RESPONSE_LIMIT",
                                trace_id=trace_id,
                                message="Response limit reached. Partial response is incomplete.",
                            )
                        )
                    pending_output += chunk
                    held = protected_suffix_length(pending_output)
                    visible = pending_output[:-held] if held else pending_output
                    pending_output = pending_output[-held:] if held else ""
                    if visible:
                        yield event("agent.token", {"text": visible})
            answer = "".join(chunks)
            if not answer.strip():
                raise AdamError(
                    ErrorEnvelope(
                        code="MODEL.EMPTY_RESPONSE",
                        trace_id=trace_id,
                        message="The model returned no answer.",
                        retryable=True,
                    )
                )
            status = "GENERATED"
            if self.store.memory_revision() != memory_revision:
                raise AdamError(
                    ErrorEnvelope(
                        code="MEMORY.CONTEXT_CHANGED",
                        trace_id=trace_id,
                        message="Memory changed during generation. Retry with the updated context.",
                        retryable=True,
                    )
                )
            if pending_output:
                yield event("agent.token", {"text": pending_output})
            point(
                "model",
                "generation",
                "COMPLETED",
                duration_ms=(perf_counter() - stage_started) * 1000,
                metrics={"output_chars": size},
            )
            write_trace()
            if not self.store.renew(session.session_id, trace_id):
                raise AdamError(
                    ErrorEnvelope(
                        code="SESSION.LEASE_LOST",
                        trace_id=trace_id,
                        message="Session lock was lost. This turn was not saved.",
                        retryable=True,
                    )
                )
            check_authority()
            self.store.append(
                session.session_id,
                request.text,
                answer,
                trace_id,
                model.model_id,
                expected_memory_revision=memory_revision,
            )
            session.messages.extend(
                [
                    Message(role="user", content=request.text),
                    Message(role="assistant", content=safe_transcript(answer)),
                ]
            )
            session.messages = session.messages[-self.settings.recent_turns * 2 :]
            status = "SUCCEEDED"
            yield event(
                "agent.completed",
                {
                    "text": answer,
                    "model": model.model_dump(),
                    "epistemic_status": "UNCERTAIN",
                    "provenance": "model_generation",
                    "identity_version": self.identity.pack.identity.version,
                    "identity_digest": self.identity.digest,
                    "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                    "context_budget": budget.model_dump(),
                    "answer_mode": "CAREFUL_TWO_PASS" if request.careful else "STANDARD",
                    "review": review_statistics,
                },
            )
        except AdamError as exc:
            error_code = exc.error.code
            yield EventEnvelope(
                event_type="agent.error",
                trace_id=trace_id,
                session_id=session.session_id if session else None,
                payload={"error": exc.error.model_dump(mode="json"), "state": "DEGRADED"},
            )
        except Exception as exc:
            status = "FAILED"
            error_code = "SYSTEM.INTERNAL"
            if isinstance(exc, OSError):
                error_code = "SYSTEM.TRACE_UNAVAILABLE"
            elif isinstance(exc, sqlite3.Error):
                error_code = "SYSTEM.STORAGE_UNAVAILABLE"
            error = ErrorEnvelope(
                code=error_code,
                trace_id=trace_id,
                message="ADAM could not complete this turn safely. Check local runtime health.",
            )
            yield EventEnvelope(
                event_type="agent.error",
                trace_id=trace_id,
                session_id=session.session_id if session else None,
                payload={"error": error.model_dump(mode="json"), "state": "DEGRADED"},
            )
        except (asyncio.CancelledError, GeneratorExit):
            status = "CANCELLED"
            raise
        finally:
            if lease_task:
                lease_task.cancel()
                with suppress(asyncio.CancelledError):
                    await lease_task
            if session and locked:
                session.busy = False
                with suppress(sqlite3.Error, OSError):
                    self.store.release(session.session_id, trace_id)
            try:
                write_trace()
            except OSError:
                pass  # The prepared trace was mandatory; terminal telemetry is best effort.

    async def chat(self, request: ChatRequest) -> EventEnvelope:
        result: EventEnvelope | None = None
        async for event in self.stream(request):
            result = event
        assert result is not None
        return result
