import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";

type Preferences = {
  enabled: boolean;
  proactive: boolean;
  triggers: string[];
  quiet_start: number | null;
  quiet_end: number | null;
  utc_offset_minutes: number;
};
type Job = {
  id: string;
  text: string;
  due: number;
  interval: number | null;
  state: string;
};
type Update = { id: string; text: string; priority: string; reason: string };
type Status = { jobs: Job[]; preferences: Preferences; error: string | null };
export function OperationsPanel({
  sessionId,
  issue,
}: {
  sessionId: string | null;
  issue: (error: unknown) => void;
}) {
  const [status, setStatus] = useState<Status | null>(null),
    [inbox, setInbox] = useState<Update[]>([]);
  const [text, setText] = useState(""),
    [due, setDue] = useState(""),
    [repeat, setRepeat] = useState("0"),
    [active, setActive] = useState(false),
    [high, setHigh] = useState(false),
    [busy, setBusy] = useState(false),
    [note, setNote] = useState("");
  const alive = useRef(true),
    generation = useRef(0),
    requestId = useRef<string | null>(null);
  useEffect(() => {
    alive.current = true;
    async function load() {
      if (document.hidden) {
        generation.current++;
        setStatus(null);
        setInbox([]);
        setText("");
        return;
      }
      const expected = generation.current;
      try {
        const [state, updates] = await Promise.all([
          bridge.api<Status>("/operations"),
          bridge.api<Update[]>("/operations/inbox"),
        ]);
        if (alive.current && expected === generation.current) {
          setStatus(state);
          setInbox(updates);
        }
      } catch (error) {
        if (alive.current && expected === generation.current) issue(error);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 5000);
    document.addEventListener("visibilitychange", load);
    return () => {
      alive.current = false;
      generation.current++;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
    };
  }, []);
  async function mutate(path: string, body: unknown) {
    setBusy(true);
    const expected = generation.current;
    try {
      await bridge.api(path, body);
      const [state, updates] = await Promise.all([
        bridge.api<Status>("/operations"),
        bridge.api<Update[]>("/operations/inbox"),
      ]);
      if (alive.current && expected === generation.current) {
        setStatus(state);
        setInbox(updates);
        setNote("Saved on your PC.");
        return true;
      }
    } catch (error) {
      if (alive.current && expected === generation.current) issue(error);
    } finally {
      if (alive.current) setBusy(false);
    }
    return false;
  }
  return (
    <section className="page operations">
      <span className="section-number">PERSONAL OPERATIONS</span>
      <h2>Reminders and updates</h2>
      <p>
        Runs while ADAM is open. Overdue reminders return on restart; missed
        repeat intervals produce one update. Scheduled jobs never run tools or
        send messages to other people.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!due || !text.trim()) return;
          const id = requestId.current ?? crypto.randomUUID();
          requestId.current = id;
          void mutate("/operations/schedule", {
            request_id: id,
            text,
            due_at: new Date(due).toISOString(),
            every_seconds: Number(repeat) || null,
            priority: high ? "HIGH" : "NORMAL",
            route: active ? "ACTIVE" : "DESKTOP",
            session_id: active ? sessionId : null,
          }).then((saved) => {
            if (saved) {
              requestId.current = null;
              setText("");
            }
          });
        }}
      >
        <label>
          Reminder
          <textarea
            maxLength={500}
            required
            value={text}
            onChange={(event) => {
              requestId.current = null;
              setText(event.target.value);
            }}
          />
        </label>
        <label>
          When (this PC’s local time)
          <input
            type="datetime-local"
            required
            value={due}
            onChange={(event) => {
              requestId.current = null;
              setDue(event.target.value);
            }}
          />
        </label>
        <label>
          Repeat
          <select
            value={repeat}
            onChange={(event) => {
              requestId.current = null;
              setRepeat(event.target.value);
            }}
          >
            <option value="0">Once</option>
            <option value="3600">Every hour</option>
            <option value="86400">Every 24 hours</option>
            <option value="604800">Every 7 days</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={high}
            onChange={(event) => {
              requestId.current = null;
              setHigh(event.target.checked);
            }}
          />{" "}
          High priority (quiet hours still apply)
        </label>
        <label>
          <input
            type="checkbox"
            checked={active}
            disabled={!sessionId}
            onChange={(event) => {
              requestId.current = null;
              setActive(event.target.checked);
            }}
          />{" "}
          Route to this conversation’s active phone; offline fallback to PC.
          Phone sees only “ADAM update available”.
        </label>
        <button className="primary" disabled={busy}>
          Schedule reminder
        </button>
      </form>
      <p role="status">
        {note}
        {status?.error ? " · " + status.error : ""}
      </p>
      {status && (
        <fieldset disabled={busy}>
          <legend>Interruption preferences</legend>
          <label>
            <input
              type="checkbox"
              checked={status.preferences.enabled}
              onChange={(event) =>
                void mutate("/operations/preferences", {
                  ...status.preferences,
                  enabled: event.target.checked,
                })
              }
            />{" "}
            Enable reminder delivery
          </label>
          <label>
            <input
              type="checkbox"
              checked={status.preferences.proactive}
              onChange={(event) =>
                void mutate("/operations/preferences", {
                  ...status.preferences,
                  proactive: event.target.checked,
                  triggers: event.target.checked ? ["unread_reminders"] : [],
                })
              }
            />{" "}
            Suggest reviewing reminders unread for 24 hours (at most once a day)
          </label>
          <p>
            Suggestions use only this inbox. They never inspect your files,
            microphone or browsing. Turning them off withdraws pending
            suggestions.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              const minutes = (value: FormDataEntryValue | null) => {
                if (!value) return null;
                const [h, m] = String(value).split(":").map(Number);
                return h * 60 + m;
              };
              void mutate("/operations/preferences", {
                ...status.preferences,
                quiet_start: minutes(data.get("start")),
                quiet_end: minutes(data.get("end")),
                utc_offset_minutes: Number(data.get("offset")),
              });
            }}
          >
            <label>
              Quiet hours start
              <input
                name="start"
                type="time"
                defaultValue={
                  status.preferences.quiet_start === null
                    ? ""
                    : `${String(Math.floor(status.preferences.quiet_start / 60)).padStart(2, "0")}:${String(status.preferences.quiet_start % 60).padStart(2, "0")}`
                }
              />
            </label>
            <label>
              Quiet hours end
              <input
                name="end"
                type="time"
                defaultValue={
                  status.preferences.quiet_end === null
                    ? ""
                    : `${String(Math.floor(status.preferences.quiet_end / 60)).padStart(2, "0")}:${String(status.preferences.quiet_end % 60).padStart(2, "0")}`
                }
              />
            </label>
            <label>
              UTC offset in minutes
              <input
                name="offset"
                type="number"
                min={-720}
                max={840}
                defaultValue={status.preferences.utc_offset_minutes}
              />
            </label>
            <p>
              300 means Pakistan time. Fixed offset; adjust manually for
              daylight saving. Leave both times blank to disable quiet hours.
            </p>
            <button>Save quiet hours</button>
          </form>
        </fieldset>
      )}
      <h3>Inbox</h3>
      <p>
        Full text appears only in this unlocked owner view. No OS push
        notifications are emitted. Mobile alerts need the trusted browser
        visible.
      </p>
      {inbox.map((update) => (
        <article className="memory-card" key={update.id}>
          <small>{update.priority}</small>
          <p>{update.text}</p>
          <details>
            <summary>Why this appeared</summary>
            <p>{update.reason}</p>
          </details>
          <button
            disabled={busy}
            onClick={() =>
              void mutate("/operations/acknowledge", { identifier: update.id })
            }
          >
            Mark reviewed
          </button>
        </article>
      ))}
      {!inbox.length && (
        <p>
          No updates here. Quiet hours or active-device routing may defer them.
        </p>
      )}
      <h3>Scheduled jobs</h3>
      {status?.jobs.map((job) => (
        <article className="memory-card" key={job.id}>
          <p>{job.text}</p>
          <small>
            {new Date(job.due * 1000).toLocaleString()} · {job.state}
            {job.interval ? " · repeats" : ""}
          </small>
          {job.state === "SCHEDULED" && (
            <button
              disabled={busy}
              onClick={() =>
                void mutate("/operations/cancel", { identifier: job.id })
              }
            >
              Cancel
            </button>
          )}
        </article>
      ))}
    </section>
  );
}
