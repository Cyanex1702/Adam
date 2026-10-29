import { useEffect, useRef, useState, type FormEvent } from "react";
import * as bridge from "./bridge";
import { Avatar } from "./Avatar";
import { ChatText } from "./ChatText";
import { OperationsBadge } from "./OperationsBadge";
import { InternetPanel } from "./InternetPanel";
import { ComputerPanel } from "./ComputerPanel";
import { DistributionPanel } from "./DistributionPanel";
import { PersonalPanel } from "./PersonalPanel";
import { TrainingPanel } from "./TrainingPanel";
import { PortfolioPanel } from "./PortfolioPanel";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { ModelLibraryPanel } from "./ModelLibraryPanel";
import { VisionPanel } from "./VisionPanel";
import { OperationsPanel } from "./OperationsPanel";
import { MeshPanel } from "./MeshPanel";
import { VoicePanel, type VoiceHandle } from "./VoicePanel";
import {
  friendlyError,
  readPreferences,
  visualState,
  type AvatarState,
  type Preferences,
} from "./state";

type View = "chat" | "memory" | "internet" | "vision" | "computer" | "distribution" | "personal" | "training" | "portfolio" | "operations" | "settings" | "developer" | "diagnostics" | "models";
type Auth = { mode: "owner" | "guest" | "demo"; developer: boolean };
type Session = {
  session_id: string;
  created_at: string;
  updated_at: string;
  closed: boolean;
};
type Turn = {
  turn_id: number;
  user_text: string;
  assistant_text: string;
  model_id: string;
};
type Message = { role: "user" | "assistant"; text: string; note?: string };
type Service = {
  configured: boolean;
  recovery: boolean;
  model_status: string;
  model_error: string | null;
  model_lifecycle?: string;
  model_device?: string;
  release: string;
  issues?: string[];
};
const preferenceKey = "adam.desktop.preferences.v1";
function Brand() {
  return (
    <div className="brand">
      <svg viewBox="0 0 32 32" aria-hidden="true">
        <circle
          cx="16"
          cy="16"
          r="13"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <path
          d="M10 22 16 9l6 13M12 18h8"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
      </svg>
      <span>
        ADAM<small>LOCAL WORKSPACE</small>
      </span>
    </div>
  );
}
function Icon({ kind }: { kind: string }) {
  const paths: Record<string, string> = {
    chat: "M4 4h16v12H9l-5 4V4Z",
    memory: "M5 3h14v18l-7-4-7 4V3Z",
    settings:
      "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2",
    developer: "m8 5-6 7 6 7m8-14 6 7-6 7m-3-16-2 18",
    models: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4v5l3 2",
  };
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d={paths[kind]}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
export function App() {
  const [view, setView] = useState<View>("chat"),
    [auth, setAuth] = useState<Auth | null>(null),
    [service, setService] = useState<Service | null>(null),
    [loading, setLoading] = useState(true);
  const [background, setBackground] = useState(false), [trayAvailable, setTrayAvailable] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  useEffect(() => {
    void bridge.backgroundStatus().then(value => {
      setBackground(value.enabled); setTrayAvailable(value.tray_available);
    }).catch(() => {});
    const hidden = bridge.onHidden(() => voice.current?.reset());
    return () => { void hidden.then(remove => remove()); };
  }, []);
  const [notice, setNotice] = useState(""),
    [lastServiceCode, setLastServiceCode] = useState<string | null>(null),
    [password, setPassword] = useState(""),
    [confirm, setConfirm] = useState(""),
    [authBusy, setAuthBusy] = useState(false);
  const [sessions, setSessions] = useState<Session[]>([]),
    [sessionId, setSessionId] = useState<string | null>(null),
    [history, setHistory] = useState<Turn[]>([]),
    [pending, setPending] = useState<Message[]>([]);
  const [draft, setDraft] = useState(""),
    [careful, setCareful] = useState(false),
    [audioEnergy, setAudioEnergy] = useState(0),
    [busy, setBusy] = useState(false),
    [avatarState, setAvatarState] = useState<AvatarState>("OFFLINE"),
    [identity, setIdentity] = useState<any>(null);
  const [query, setQuery] = useState(""),
    [memories, setMemories] = useState<any[]>([]),
    [memoryLoading, setMemoryLoading] = useState(false),
    [memorySearched, setMemorySearched] = useState(false);
  const [developer, setDeveloper] = useState<any>(null),
    [devPassword, setDevPassword] = useState(""),
    [devBusy, setDevBusy] = useState(false);
  const [preferences, setPreferences] = useState<Preferences>(() =>
    readPreferences(
      localStorage.getItem(preferenceKey),
      matchMedia("(prefers-reduced-motion: reduce)").matches,
    ),
  );
  const epoch = useRef(0),
    voice = useRef<VoiceHandle>(null),
    runningChat = useRef<Promise<void> | null>(null),
    requestId = useRef<string | null>(null),
    bottom = useRef<HTMLDivElement>(null),
    composer = useRef<HTMLTextAreaElement>(null),
    booted = useRef(false),
    busyRef = useRef(false);
  const connectionBusy = useRef(false), pollEnabled = useRef(false), pollFailures = useRef(0), automaticReconnects = useRef(0);
  busyRef.current = busy;
  function issue(error: unknown) {
    setNotice(friendlyError(error));
    if (error === "AUTH.REQUIRED" || error === "AUTH.CHANGED") {
      clearPrivate();
      setAuth(null);
    }
    if (error === "AUTH.ELEVATION_REQUIRED") {
      setDeveloper(null);
      setAuth((old) => (old ? { ...old, developer: false } : null));
    }
  }
  function clearPrivate() {
    voice.current?.reset();
    epoch.current++;
    requestId.current = null;
    void bridge.cancel();
    setSessions([]);
    setSessionId(null);
    setHistory([]);
    setPending([]);
    setDraft("");
    setMemories([]);
    setQuery("");
    setMemorySearched(false);
    setDeveloper(null);
    setDevPassword("");
    setIdentity(null);
    setBusy(false);
    setView("chat");
  }
  async function refresh(expected = epoch.current) {
    const [listed, card] = await Promise.all([
      bridge.api<Session[]>("/sessions"),
      bridge.api("/identity"),
    ]);
    if (expected === epoch.current) {
      setSessions(listed);
      setIdentity(card);
    }
  }
  async function boot(restart = false) {
    if (connectionBusy.current) return;
    connectionBusy.current = true;
    pollEnabled.current = false;
    setLoading(true);
    clearPrivate();
    setAuth(null);
    setNotice("");
    setAvatarState("OFFLINE");
    try {
      await bridge.start(restart);
      const status = await bridge.api<Service>("/desktop/status");
      pollEnabled.current = true;
      setService(status);
      setLastServiceCode(null);
      setAvatarState(status.model_status === "HEALTHY" ? "IDLE" : "OFFLINE");
    } catch (error) {
      setLastServiceCode(typeof error === "string" ? error : "DESKTOP.START_FAILED");
      issue(error);
    } finally {
      connectionBusy.current = false;
      setLoading(false);
    }
  }
  useEffect(() => {
    if (!booted.current) {
      booted.current = true;
      void boot();
    }
    const timer = setInterval(() => {
      if (booted.current && pollEnabled.current && !connectionBusy.current) {
        connectionBusy.current = true;
        bridge
          .api<Service>("/desktop/status")
          .then((status) => {
            pollFailures.current = 0;
            setService(status);
            if (!busyRef.current)
              setAvatarState((old) =>
                visualState(old, {
                  kind: "connection",
                  online: status.model_status === "HEALTHY",
                }),
              );
          })
          .catch(async (error) => {
            if (++pollFailures.current < 2) return;
            pollEnabled.current = false;
            setService(null);
            clearPrivate();
            setAuth(null);
            setAvatarState("OFFLINE");
            setView("diagnostics");
            setNotice(friendlyError(error));
            setLastServiceCode(typeof error === "string" ? error : "DESKTOP.CONNECTION_LOST");
            if (automaticReconnects.current++ === 0) {
              try { await bridge.start(false); setService(await bridge.api<Service>("/desktop/status")); pollEnabled.current = true; }
              catch { /* One bounded reconnect; diagnostics remain accessible. */ }
            }
          }).finally(() => { connectionBusy.current = false; });
      }
    }, 5000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    localStorage.setItem(preferenceKey, JSON.stringify(preferences));
  }, [preferences]);
  useEffect(() => {
    bottom.current?.scrollIntoView({
      behavior: preferences.reducedMotion ? "auto" : "smooth",
      block: "end",
    });
  }, [pending, history, preferences.reducedMotion]);
  async function inspectHardware() {
    const expected = epoch.current;
    try {
      const hardware = await bridge.api("/developer/hardware?benchmark=true");
      if (expected === epoch.current)
        setDeveloper((old: any) => ({ ...old, hardware }));
    } catch (error) {
      if (expected === epoch.current) issue(error);
    }
  }
  async function signIn(event: FormEvent) {
    event.preventDefault();
    if (authBusy) return;
    setAuthBusy(true);
    setNotice("");
    const secret = password;
    setPassword("");
    setConfirm("");
    clearPrivate();
    try {
      if (!service?.configured) {
        if (secret !== confirm) {
          setNotice("The passphrases do not match.");
          return;
        }
        await bridge.api("/desktop/setup", { password: secret });
        setService((old) => (old ? { ...old, configured: true } : old));
      }
      await bridge.api("/auth/login", { password: secret });
      setAuth(await bridge.api<Auth>("/auth/status"));
      await refresh();
      setAvatarState(service?.model_status === "HEALTHY" ? "IDLE" : "OFFLINE");
    } catch (error) {
      issue(error);
    } finally {
      setAuthBusy(false);
    }
  }
  async function demo() {
    if (authBusy || busy) return;
    setAuthBusy(true);
    const hadAuth = !!auth;
    clearPrivate();
    setAuth(null);
    setNotice("");
    try {
      await bridge.api(hadAuth ? "/auth/switch" : "/auth/session", {
        mode: "demo",
      });
      setAuth(await bridge.api<Auth>("/auth/status"));
      await refresh();
      setAvatarState(service?.model_status === "HEALTHY" ? "IDLE" : "OFFLINE");
    } catch (error) {
      issue(error);
    } finally {
      setAuthBusy(false);
    }
  }
  async function lock() {
    clearPrivate();
    setAuth(null);
    setPassword("");
    setConfirm("");
    setNotice("");
    try {
      await bridge.api("/auth/logout", {});
    } catch {
      /* Local UI is locked even if the service already stopped. */
    }
  }
  function newConversation() {
    if (busy) return;
    setView("chat");
    setSessionId(null);
    setHistory([]);
    setPending([]);
    setNotice("");
    setAvatarState(service?.model_status === "HEALTHY" ? "IDLE" : "OFFLINE");
    composer.current?.focus();
  }
  async function openSession(item: Session) {
    if (busy) return;
    const expected = ++epoch.current;
    setView("chat");
    setPending([]);
    setNotice("");
    try {
      if (item.closed)
        await bridge.api(`/sessions/${item.session_id}/resume`, {});
      const turns = await bridge.api<Turn[]>(
        `/sessions/${item.session_id}/history`,
      );
      if (expected === epoch.current) {
        setSessionId(item.session_id);
        setHistory(turns);
      }
    } catch (error) {
      issue(error);
    }
  }
  async function earlier() {
    if (!sessionId || !history.length) return;
    const expected = epoch.current;
    try {
      const turns = await bridge.api<Turn[]>(
        `/sessions/${sessionId}/history?before=${history[0].turn_id}`,
      );
      if (expected === epoch.current) setHistory((old) => [...turns, ...old]);
      if (!turns.length)
        setNotice("You have reached the beginning of this conversation.");
    } catch (error) {
      issue(error);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    await sendText(draft);
  }
  function sendText(text: string): Promise<void> {
    const operation = performSend(text);
    runningChat.current = operation;
    return operation;
  }
  async function stopResponse() {
    await bridge.cancel();
    await runningChat.current;
  }
  async function performSend(input: string) {
    if (!input.trim() || busyRef.current || !auth) return;
    const text = input.trim(),
      expected = epoch.current,
      id = crypto.randomUUID();
    requestId.current = id;
    busyRef.current = true;
    voice.current?.begin();
    setDraft("");
    setNotice("");
    setBusy(true);
    setPending([
      { role: "user", text },
      { role: "assistant", text: "" },
    ]);
    setAvatarState((old) => visualState(old, { kind: "request" }));
    let activeSession = sessionId,
      terminal = false;
    try {
      const result = await bridge.send(
        id,
        { text, session_id: sessionId, careful },
        (event) => {
          if (expected !== epoch.current || requestId.current !== id) return;
          if (event.session_id) {
            voice.current?.session(event.session_id);
            activeSession = event.session_id;
            setSessionId(event.session_id);
          }
          setAvatarState((old) => visualState(old, { kind: "backend", event }));
          if (event.event_type === "agent.started" && event.payload.model)
            setIdentity((old: any) => old ? { ...old, model: event.payload.model } : old);
          if (event.event_type === "agent.started" && event.payload.model_selection?.switched)
            setNotice(`Using ${event.payload.model?.display_name ?? "an approved local model"} for this task. Your conversation keeps its context.`);
          if (event.event_type === "agent.token") {
            voice.current?.append(String(event.payload.text ?? ""));
            setPending((old) => [
              old[0],
              {
                role: "assistant",
                text: (old[1]?.text ?? "") + String(event.payload.text ?? ""),
              },
            ]);
          }
          if (event.event_type === "agent.completed") {
            voice.current?.append("", true);
            terminal = true;
            setPending((old) => [
              old[0],
              {
                role: "assistant",
                text: String(event.payload.text ?? old[1]?.text ?? ""),
                note:
                  event.payload.epistemic_status === "UNCERTAIN"
                    ? "Model answer · unverified"
                    : undefined,
              },
            ]);
          }
          if (event.event_type === "agent.error") {
            voice.current?.begin();
            terminal = true;
            const code = event.payload.error?.code ?? "DESKTOP.REQUEST_FAILED";
            setNotice(friendlyError(code));
            setPending((old) =>
              old.map((message) => ({
                ...message,
                note: "Not saved · interrupted turn",
              })),
            );
          }
        },
      );
      if (expected !== epoch.current) return;
      if (result.cancelled) {
        voice.current?.begin();
        setNotice("Response stopped. The unfinished turn was not saved.");
        setPending((old) =>
          old.map((message) => ({ ...message, note: "Not saved · stopped" })),
        );
        setAvatarState((old) => visualState(old, { kind: "cancel" }));
      }
      if (terminal && activeSession) {
        const turns = await bridge.api<Turn[]>(
          `/sessions/${activeSession}/history`,
        );
        if (expected === epoch.current && turns.length) {
          setHistory(turns);
          setPending([]);
        }
      }
      await refresh(expected);
    } catch (error) {
      if (expected === epoch.current) {
        voice.current?.begin();
        issue(error);
        setAvatarState("ERROR");
        setPending((old) =>
          old.map((message) => ({
            ...message,
            note: "Not saved · interrupted turn",
          })),
        );
      }
    } finally {
      if (expected === epoch.current) {
        requestId.current = null;
        setBusy(false);
        busyRef.current = false;
        composer.current?.focus();
      }
    }
  }
  async function searchMemory(event: FormEvent) {
    event.preventDefault();
    const expected = epoch.current;
    setMemoryLoading(true);
    setNotice("");
    try {
      const values = await bridge.api<any[]>(
        "/memory?query=" + encodeURIComponent(query),
      );
      if (expected === epoch.current) {
        setMemories(values);
        setMemorySearched(true);
      }
    } catch (error) {
      issue(error);
    } finally {
      setMemoryLoading(false);
    }
  }
  async function loadDeveloper() {
    const expected = epoch.current;
    const values = await Promise.all([
      bridge.api("/developer/health"),
      bridge.api("/developer/compute"),
      bridge.api("/developer/traces"),
    ]);
    if (expected === epoch.current)
      setDeveloper({
        health: values[0],
        compute: values[1],
        traces: values[2],
      });
  }
  async function elevate(event: FormEvent) {
    event.preventDefault();
    setDevBusy(true);
    const secret = devPassword;
    setDevPassword("");
    try {
      await bridge.api("/auth/elevate", { password: secret });
      setAuth(await bridge.api<Auth>("/auth/status"));
      await loadDeveloper();
      setNotice("Developer access unlocked for five minutes.");
    } catch (error) {
      issue(error);
    } finally {
      setDevBusy(false);
    }
  }
  function openView(next: View) {
    if (busy) return;
    setView(next);
    setNotice("");
    if (next === "developer" && auth?.developer)
      void loadDeveloper().catch(issue);
  }
  const title =
    view === "models" ? "Local model library" : view === "diagnostics" ? "Diagnostics & performance" : view === "chat"
      ? "Conversation"
      : view === "memory"
        ? "Saved memory"
        : view === "internet"
          ? "Internet and integrations"
        : view === "vision"
          ? "Images and screen reading"
        : view === "computer"
          ? "Reviewed computer actions"
        : view === "distribution"
          ? "Setup and recovery"
        : view === "personal"
          ? "Personal intelligence"
        : view === "training"
          ? "Behavior training experiment"
        : view === "portfolio"
          ? "Demo and benchmarks"
        : view === "operations"
          ? "Reminders and updates"
          : view === "settings"
            ? "Workspace settings"
            : "Developer console";
  const model = identity?.model;
  return (
    <div
      className={
        "desktop " + (preferences.reducedMotion ? "reduced-motion" : "")
      }
    >
      <aside className="sidebar">
        <Brand />
        <button
          className="new-chat"
          onClick={newConversation}
          disabled={!auth || busy}
        >
          <span>＋</span> New conversation
        </button>
        <nav aria-label="Workspace">
          <button
            className={view === "chat" ? "selected" : ""}
            onClick={() => openView("chat")}
            disabled={!auth || busy}
          >
            <Icon kind="chat" />
            Conversations
          </button>
          <button
            className={view === "memory" ? "selected" : ""}
            onClick={() => openView("memory")}
            disabled={!auth || busy}
          >
            <Icon kind="memory" />
            Saved memory
          </button>
          <button
            className={view === "operations" ? "selected" : ""}
            onClick={() => openView("operations")}
            disabled={auth?.mode !== "owner" || busy}
          >
            <Icon kind="clock" />
            Reminders{auth?.mode === "owner" && <OperationsBadge />}
          </button>
          <button className={view === "models" ? "selected" : ""} onClick={() => openView("models")} disabled={auth?.mode !== "owner" || busy} title="Discover, approve and switch local GGUF models"><Icon kind="models" />Model library</button>
          <details className="advanced-navigation"><summary>Tools &amp; more</summary>
          <button className={view === "personal" ? "selected" : ""} onClick={() => openView("personal")} disabled={!auth || auth.mode === "guest" || busy} title="Relationships, timelines and goals linked to your memories">Personal intelligence</button>
          <button className={view === "distribution" ? "selected" : ""} onClick={() => openView("distribution")} disabled={auth?.mode !== "owner" || busy} title="Install a model, manage backups and restore your workspace">Setup and recovery</button>
          <button className={view === "internet" ? "selected" : ""}
            onClick={() => openView("internet")} disabled={auth?.mode !== "owner" || busy}>
            <Icon kind="chat" /> Internet
          </button>
          <button className={view === "computer" ? "selected" : ""} onClick={() => openView("computer")} disabled={auth?.mode !== "owner" || busy}>Computer actions</button>
          <button className={view === "training" ? "selected" : ""} onClick={() => openView("training")} disabled={auth?.mode !== "owner" || busy}>Behavior experiment</button>
          <button className={view === "portfolio" ? "selected" : ""} onClick={() => openView("portfolio")} disabled={!auth || busy}>Demo and benchmarks</button>
          <button className={view === "vision" ? "selected" : ""}
            onClick={() => openView("vision")} disabled={auth?.mode !== "owner" || busy}>
            <Icon kind="chat" /> Vision
          </button>
          </details>
        </nav>
        <div className="recent-label">
          Recent chats <span>{sessions.length || "0"}</span>
        </div>
        <div className="session-list">
          {sessions.map((item, index) => (
            <button
              key={item.session_id}
              title={item.session_id}
              className={sessionId === item.session_id ? "active" : ""}
              onClick={() => void openSession(item)}
              disabled={busy}
            >
              <span className="session-glyph">◷</span>
              <span>
                Conversation {sessions.length - index}
                <small>
                  {new Date(item.updated_at).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                  })}
                  {item.closed ? " · closed" : ""}
                </small>
              </span>
            </button>
          ))}
          {!sessions.length && (
            <p className="sidebar-hint">
              {auth
                ? "Your conversations will appear here."
                : "Unlock to see your saved conversations."}
            </p>
          )}
        </div>
        <nav className="bottom-nav" aria-label="Application">
          <button className={view === "diagnostics" ? "selected" : ""} onClick={() => openView("diagnostics")} disabled={busy} title="Check resources, troubleshoot startup, and choose Eco or Priority mode">
            <Icon kind="settings" /> Diagnostics
          </button>
          <button
            className={view === "settings" ? "selected" : ""}
            onClick={() => openView("settings")}
            disabled={!auth || busy}
          >
            <Icon kind="settings" />
            Settings
          </button>
          <button
            className={view === "developer" ? "selected" : ""}
            onClick={() => openView("developer")}
            disabled={auth?.mode !== "owner" || busy}
          >
            <Icon kind="developer" />
            Developer mode
          </button>
        </nav>
        <div className="profile">
          <span className="profile-avatar">
            {auth?.mode === "demo" ? "D" : "A"}
          </span>
          <span>
            {auth
              ? auth.mode === "owner"
                ? "Owner workspace"
                : "Fictional demo"
              : "Workspace locked"}
            <small>
              {auth?.mode === "demo"
                ? "Separate synthetic data"
                : "Only on this PC"}
            </small>
          </span>
          {auth && (
            <button
              className="lock-button"
              onClick={() => void lock()}
              title="Lock workspace"
              aria-label="Lock workspace"
            >
              ↗
            </button>
          )}
        </div>
      </aside>
      <div className="workspace">
        <header>
          <div>
            <span className="eyebrow">ADAM WORKSPACE</span>
            <h1>{auth ? title : "Welcome to ADAM"}</h1>
          </div>
          <div className="header-actions">
          <button
            type="button"
            onClick={() => setView("diagnostics")}
            title="Open diagnostics and model settings"
            className={
              "connection " +
              (service?.model_status === "HEALTHY" ? "online" : "")
            }
          >
            <span />
            {loading
              ? "Starting local service"
              : !service
                ? "Service offline"
                : service.model_status === "HEALTHY"
                  ? "Local model ready"
                  : service.model_lifecycle === "LOADING" ? "Loading model…" : "Model needs attention"}
            {service?.model_device === "vulkan" ? " · GPU" : service?.model_device === "cpu" ? " · CPU" : ""}
            {background && " · background enabled"}
          </button>
          <button className={"activity-toggle" + (activityOpen ? " active" : "")} onClick={() => setActivityOpen(value => !value)} aria-expanded={activityOpen} aria-controls="assistant-activity">Activity</button>
          </div>
        </header>
        {notice && (
          <div className="notice" role="status">
            {notice}
            <button aria-label="Dismiss notice" onClick={() => setNotice("")}>
              ×
            </button>
          </div>
        )}
        <div className={"content-grid" + (activityOpen ? " with-activity" : "")}>
          <main>
            {view === "diagnostics" ? (
              <DiagnosticsPanel owner={auth?.mode === "owner"} reconnect={() => void boot(true)} back={() => setView("chat")} serviceError={lastServiceCode} issue={issue} />
            ) : view === "models" && auth?.mode === "owner" ? (
              <ModelLibraryPanel issue={issue} />
            ) : !auth ? (
              <section className="unlock">
                <span className="section-number">PRIVATE BY DEFAULT</span>
                <h2>
                  {loading
                    ? "Opening your workspace…"
                    : service?.recovery
                      ? "Your data needs attention"
                      : service?.configured
                        ? "Welcome back."
                        : "A private place to begin."}
                </h2>
                <p>
                  {service?.recovery
                    ? "ADAM found a storage or configuration problem and opened read-only recovery. Your data has not been changed. Use the local recovery guide before continuing."
                    : "Unlock your local assistant. Your saved conversations and notes are stored on this PC."}
                </p>
                {!loading && service && !service.recovery && (
                  <>
                    <form onSubmit={signIn}>
                      <label>
                        {service.configured
                          ? "Owner passphrase"
                          : "Create owner passphrase"}
                        <input
                          type="password"
                          value={password}
                          onChange={(event) => setPassword(event.target.value)}
                          minLength={service.configured ? 1 : 12}
                          maxLength={1024}
                          autoComplete={
                            service.configured
                              ? "current-password"
                              : "new-password"
                          }
                          required
                        />
                      </label>
                      {!service.configured && (
                        <label>
                          Confirm passphrase
                          <input
                            type="password"
                            value={confirm}
                            onChange={(event) => setConfirm(event.target.value)}
                            autoComplete="new-password"
                            required
                          />
                        </label>
                      )}
                      <button className="primary" disabled={authBusy}>
                        {authBusy
                          ? "Opening…"
                          : service.configured
                            ? "Unlock workspace"
                            : "Create & unlock"}{" "}
                        <span>→</span>
                      </button>
                    </form>
                    <div className="or-line">
                      <span />
                      OR
                      <span />
                    </div>
                    <button
                      className="secondary"
                      onClick={() => void demo()}
                      disabled={authBusy}
                    >
                      Explore fictional demo <span>↗</span>
                    </button>
                  </>
                )}
                {!loading && (
                  <button className="secondary" onClick={() => setView("diagnostics")}>
                    Open diagnostics &amp; recovery help
                  </button>
                )}
                {service?.issues?.map((code) => <p className="diagnostic-code" key={code}><code>{code}</code> — {friendlyError(code)}</p>)}
                {!loading && (
                  <button
                    className="text-button"
                    onClick={() => void boot(true)}
                  >
                    Restart local service
                  </button>
                )}
                <p className="fine-print">
                  No cloud account. Microphone starts only when you record.
                  <br />
                  Your passphrase is never saved as plain text.
                </p>
              </section>
            ) : view === "chat" ? (
              <section className="chat-view">
                <div className="chat-scroll">
                  {!history.length && !pending.length ? (
                    <div className="welcome">
                      <span className="section-number">
                        YOUR LOCAL WORKSPACE
                      </span>
                      <h2>
                        What are we working on?
                      </h2>
                      <p>
                        Ask a question, work through an idea, or pick up where you left off.
                      </p>
                      <div className="welcome-model"><span className={service?.model_status === "HEALTHY" ? "ready-dot" : "waiting-dot"} /><span>{model?.display_name ?? "Your local model"}</span><span className="device-label">{service?.model_device === "vulkan" ? "GPU · Vulkan" : service?.model_device === "cpu" ? "CPU" : "Local server"}</span></div>
                      <div className="suggestions">
                        {[
                          [
                            "What can ADAM do?",
                            "What can you do right now?",
                          ],
                          ["Save a preference", "/remember preference "],
                          [
                            "Recall a note",
                            "What do you remember about my preferences?",
                          ],
                        ].map(([label, text]) => (
                          <button
                            key={label}
                            onClick={() => {
                              setDraft(text);
                              composer.current?.focus();
                            }}
                          >
                            {label}
                            <span>↗</span>
                          </button>
                        ))}
                      </div>
                      <span className="welcome-note">
                        {auth.mode === "demo"
                          ? "DEMO · FICTIONAL DATA ONLY"
                          : "LOCAL · PRIVATE · MODEL-INDEPENDENT"}
                      </span>
                    </div>
                  ) : (
                    <div className="messages">
                      {history.length >= 100 && (
                        <button
                          className="text-button"
                          onClick={() => void earlier()}
                        >
                          Load earlier messages
                        </button>
                      )}
                      {history
                        .flatMap<Message>((turn) => [
                          { role: "user" as const, text: turn.user_text },
                          {
                            role: "assistant" as const,
                            text: turn.assistant_text,
                            note:
                              turn.model_id === "grounded_source_service"
                                ? "From local sources"
                                : turn.model_id ===
                                    "deterministic_memory_service"
                                  ? "Memory command"
                                  : "Model answer · unverified",
                          },
                        ])
                        .concat(pending)
                        .map((message, index) => (
                          <article
                            className={"message " + message.role}
                            key={index}
                          >
                            <div className="message-role">
                              {message.role === "user" ? "YOU" : "ADAM"}
                              <span>{message.note}</span>
                            </div>
                            <div className="message-text">
                              {(message.role === "assistant" && message.text ? <ChatText text={message.text} /> : message.text) || (
                                <span className="working-dots">
                                  Preparing a response…
                                </span>
                              )}
                            </div>
                          </article>
                        ))}
                      <div ref={bottom} />
                    </div>
                  )}
                </div>
                <form className="composer" onSubmit={submit}>
                  {busy && !pending.at(-1)?.text && <p className="preparing-answer" role="status">{careful ? "Checking the stated facts, then preparing an answer…" : "Preparing your local answer…"} The first CPU reply can take several minutes while the model processes context. You can stop at any time.</p>}
                  <label className="sr-only" htmlFor="message">
                    Message ADAM
                  </label>
                  <textarea
                    ref={composer}
                    id="message"
                    placeholder="What's on your mind?"
                    value={draft}
                    maxLength={12000}
                    rows={2}
                    disabled={busy}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (
                        event.key === "Enter" &&
                        !event.shiftKey &&
                        !event.nativeEvent.isComposing
                      ) {
                        event.preventDefault();
                        if (!busy && draft.trim())
                          event.currentTarget.form?.requestSubmit();
                      }
                    }}
                  />
                  <div className="composer-bottom">
                    <label className="careful-toggle" title="Experimental: uses two bounded model passes to list premises, then answer. Slower; it can still repeat the same mistake.">
                      <input type="checkbox" checked={careful} onChange={event => setCareful(event.target.checked)} disabled={busy} /> Careful answer · experimental
                    </label>
                    <span>
                      Text & local voice <i /> Shift + Enter for a new line
                    </span>
                    {busy ? (
                      <button
                        type="button"
                        className="send-button stop"
                        onClick={() => {
                          voice.current?.begin();
                          void stopResponse();
                        }}
                        aria-label="Stop response"
                      >
                        ■
                      </button>
                    ) : (
                      <button
                        type="submit"
                        className="send-button"
                        disabled={!draft.trim()}
                        aria-label="Send message"
                      >
                        ↑
                      </button>
                    )}
                  </div>
                </form>
                <details className="voice-drawer" onToggle={event => { if (!event.currentTarget.open) voice.current?.reset(); }}>
                <summary>Local voice <span>Record, listen and manage speech settings</span></summary>
                <VoicePanel
                  sessionId={sessionId}
                  ref={voice}
                  busy={busy}
                  onSend={sendText}
                  onInterrupt={stopResponse}
                  onActivity={(state, energy) => {
                    setAudioEnergy(energy);
                    if (state === "SPEAKING" && energy > 0.005)
                      setAvatarState("SPEAKING");
                    else if (state === "LISTENING") setAvatarState("LISTENING");
                    else if (!busyRef.current)
                      setAvatarState(
                        service?.model_status === "HEALTHY"
                          ? "IDLE"
                          : "OFFLINE",
                      );
                  }}
                />
                </details>
                <p className="chat-footnote">
                  ADAM can be wrong. Verify important answers. Never paste
                  passwords or credentials.
                </p>
              </section>
            ) : view === "personal" ? (
              <PersonalPanel key={auth.mode} issue={issue} />
            ) : view === "training" ? (
              <TrainingPanel issue={issue} />
            ) : view === "portfolio" ? (
              <PortfolioPanel key={auth.mode} mode={auth.mode} issue={issue} />
            ) : view === "internet" ? (
              <InternetPanel issue={issue} />
            ) : view === "vision" ? (
              <VisionPanel issue={issue} />
            ) : view === "computer" ? (
              <ComputerPanel issue={issue} />
            ) : view === "distribution" ? (
              <DistributionPanel issue={issue} />
            ) : view === "operations" ? (
              <OperationsPanel
                key={auth?.mode}
                sessionId={sessionId}
                issue={issue}
              />
            ) : view === "memory" ? (
              <section className="page">
                <span className="section-number">EXPLICIT MEMORY</span>
                <h2>A few things worth keeping.</h2>
                <p>
                  Search saved records and inspect their provenance. Owner
                  memory is separate from fictional demo data.
                </p>
                <form className="search-form" onSubmit={searchMemory}>
                  <label className="sr-only" htmlFor="memory-query">
                    Search memory
                  </label>
                  <input
                    id="memory-query"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    maxLength={2000}
                    placeholder="Search a preference, fact, or project…"
                  />
                  <button className="primary" disabled={memoryLoading}>
                    {memoryLoading ? "Searching…" : "Search memory"}
                  </button>
                </form>
                <div className="memory-results">
                  {memories.map((memory, index) => (
                    <article
                      className="memory-card"
                      key={memory.memory_id ?? index}
                    >
                      <span className="tag">
                        {memory.memory_type ?? "Saved record"}
                      </span>
                      <p>{memory.content}</p>
                      <small>
                        {memory.epistemic_status ?? "REPORTED"} ·{" "}
                        {memory.key ?? memory.memory_id}
                      </small>
                    </article>
                  ))}
                  {memorySearched && !memories.length && (
                    <p className="empty-state">
                      No saved memory matched that search.
                    </p>
                  )}
                </div>
                <div className="hint-card">
                  Save a preference from chat with{" "}
                  <code>/remember preference key = value</code>. Use{" "}
                  <code>/forget key</code> to remove it explicitly.
                </div>
              </section>
            ) : view === "settings" ? (
              <section className="page">
                <span className="section-number">THIS WORKSPACE</span>
                <h2>Keep it comfortable.</h2>
                <p>
                  Display preferences stay on this PC. Model capabilities below
                  come from the running service.
                </p>
                <div className="setting-row">
                  <div>
                    <strong>Keep ADAM running in the background</strong>
                    <p>Off by default for each launch. When enabled, closing the window keeps the model and scheduled work running. Microphone capture stops while hidden. Use the ADAM tray icon to reopen or quit and free RAM.</p>
                  </div>
                  <input type="checkbox" aria-label="Keep ADAM running in the background"
                    disabled={!trayAvailable || auth.mode !== "owner"} checked={background}
                    onChange={event => {
                      const enabled = event.target.checked;
                      void bridge.backgroundMode(enabled).then(value => setBackground(value.enabled)).catch(issue);
                    }} />
                </div>
                {!trayAvailable && <p className="fine-print">A tray indicator is unavailable. Closing the window quits ADAM.</p>}
                <div className="setting-row">
                  <div>
                    <strong>Abstract avatar</strong>
                    <p>Show the current operational state.</p>
                  </div>
                  <input
                    type="checkbox"
                    aria-label="Show abstract avatar"
                    checked={preferences.avatar}
                    onChange={(event) =>
                      setPreferences((old) => ({
                        ...old,
                        avatar: event.target.checked,
                      }))
                    }
                  />
                </div>
                <div className="setting-row">
                  <div>
                    <strong>Reduce motion</strong>
                    <p>Use a static orb and immediate scrolling.</p>
                  </div>
                  <input
                    type="checkbox"
                    aria-label="Reduce motion"
                    checked={preferences.reducedMotion}
                    onChange={(event) =>
                      setPreferences((old) => ({
                        ...old,
                        reducedMotion: event.target.checked,
                      }))
                    }
                  />
                </div>
                <div className="settings-card">
                  <span className="eyebrow">
                    ACTIVE MODEL · DECLARED CAPABILITIES
                  </span>
                  <h3>{model?.display_name ?? "Unavailable"}</h3>
                  <dl>
                    <dt>Context</dt>
                    <dd>
                      {model?.context_limit?.toLocaleString() ?? "—"} tokens
                    </dd>
                    <dt>Languages</dt>
                    <dd>{model?.languages?.join(", ") || "Not declared"}</dd>
                    <dt>Voice</dt>
                    <dd>Local · enable recording in chat</dd>
                    <dt>Vision</dt>
                    <dd>Unavailable</dd>
                    <dt>Data</dt>
                    <dd>Local to this PC</dd>
                    <dt>Runtime</dt>
                    <dd>{service?.release ?? "—"}</dd>
                  </dl>
                </div>
                <div className="settings-actions">
                  <button className="secondary" onClick={() => { voice.current?.reset(); void bridge.quit().catch(issue); }}>Quit ADAM and stop owned model</button>
                  <button
                    className="secondary"
                    onClick={() => void demo()}
                    disabled={authBusy || auth.mode === "demo"}
                  >
                    Switch to fictional demo
                  </button>
                  <button className="secondary" onClick={() => void lock()}>
                    Lock / return to owner login
                  </button>
                  <button
                    className="text-button"
                    onClick={() => void boot(true)}
                  >
                    Restart local service
                  </button>
                </div>
                <p className="fine-print">
                  Restarting locks the workspace. Saved conversations and memory
                  are preserved. Models and embedding assets are installed
                  separately from the application.
                </p>
              </section>
            ) : (
              <section className="page">
                <span className="section-number">OWNER · DEVELOPER MODE</span>
                <h2>See what is actually running.</h2>
                <p>
                  Resource readings and operational metadata. Conversation text
                  and hidden reasoning are excluded from traces.
                </p>
                {!auth.developer ? (
                  <form onSubmit={elevate}>
                    <label>
                      Re-enter owner passphrase
                      <input
                        type="password"
                        value={devPassword}
                        onChange={(event) => setDevPassword(event.target.value)}
                        autoComplete="current-password"
                        required
                      />
                    </label>
                    <button className="primary" disabled={devBusy}>
                      Unlock developer view
                    </button>
                  </form>
                ) : (
                  <>
                    <div className="developer-actions">
                      <button
                        className="secondary"
                        onClick={() => void loadDeveloper().catch(issue)}
                      >
                        Refresh diagnostics
                      </button>
                      {["load", "unload"].map((action) => (
                        <button
                          className="secondary"
                          key={action}
                          onClick={() =>
                            void bridge
                              .api("/developer/compute/" + action, {})
                              .then(loadDeveloper)
                              .catch(issue)
                          }
                        >
                          {action === "load" ? "Load model" : "Unload model"}
                        </button>
                      ))}
                      <button
                        className="secondary"
                        onClick={() => void inspectHardware()}
                      >
                        Inspect hardware
                      </button>
                    </div>
                    <MeshPanel
                      sessionId={sessionId}
                      stopVoice={() => voice.current?.reset()}
                    />
                    {developer &&
                      Object.entries(developer).map(([key, value]) => (
                        <details key={key} open={key === "compute"}>
                          <summary>{key}</summary>
                          <pre>{JSON.stringify(value, null, 2)}</pre>
                        </details>
                      ))}
                  </>
                )}
              </section>
            )}
          </main>
          {activityOpen && <aside className="right-panel" id="assistant-activity">
            <Avatar
              state={avatarState}
              preferences={preferences}
              audioEnergy={audioEnergy}
            />
            <section className="local-card">
              <span className="local-shield">◈</span>
              <div>
                <strong>Rooted in your PC.</strong>
                <p>
                  Your model is replaceable.
                  <br />
                  Your identity and memory stay.
                </p>
              </div>
            </section>
            <div className="right-footer">
              <span>ADAM / {service?.release ?? "local"}</span>
              <span>LOCAL VOICE WORKSPACE</span>
            </div>
          </aside>}
        </div>
      </div>
    </div>
  );
}
