import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";

export function PersonalPanel({ issue }: { issue: (error: unknown) => void }) {
  const [query, setQuery] = useState(""), [memories, setMemories] = useState<any[]>([]);
  const [links, setLinks] = useState<any[]>([]), [events, setEvents] = useState<any[]>([]);
  const [goals, setGoals] = useState<any[]>([]), [briefing, setBriefing] = useState<any>(null);
  const [evidence, setEvidence] = useState(""), [subject, setSubject] = useState("");
  const [relation, setRelation] = useState("works_on"), [object, setObject] = useState("");
  const [inferred, setInferred] = useState(false), [historical, setHistorical] = useState(false);
  const [asOf, setAsOf] = useState(""), [title, setTitle] = useState(""), [project, setProject] = useState("");
  const [editing, setEditing] = useState<any>(null), [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const epoch = useRef(0), alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    void run(refresh);
    function hidden() {
      if (document.hidden) {
        epoch.current++; setMemories([]); setLinks([]); setEvents([]); setGoals([]);
        setBriefing(null); setTitle(""); setProject(""); setSubject(""); setObject("");
        setEvidence(""); setEditing(null); setNote(""); setBusy(false);
        setQuery(""); setRelation("works_on"); setAsOf("");
      }
    }
    document.addEventListener("visibilitychange", hidden);
    return () => { alive.current = false; epoch.current++; document.removeEventListener("visibilitychange", hidden); };
  }, []);
  async function run(work: () => Promise<void>) {
    setBusy(true); setNote("");
    try { await work(); } catch (error) { if (alive.current) issue(error); }
    finally { if (alive.current) setBusy(false); }
  }
  async function refresh() {
    const stamp = epoch.current;
    const [state, graph, timeline, saved] = await Promise.all([
      bridge.api("/personal"), bridge.api("/personal/graph", { query, historical }),
      bridge.api("/personal/timeline", { query, as_of: asOf ? new Date(asOf).toISOString() : null }),
      bridge.api(`/memory?query=${encodeURIComponent(query)}`),
    ]);
    if (!alive.current || epoch.current !== stamp || document.hidden) return;
    setGoals(state.goals); setBriefing(state.briefing); setLinks(graph.links);
    setEvents(timeline.events); setMemories(saved);
  }
  async function saveGoal(value: any) {
    await bridge.api("/personal/goal", value); await refresh();
  }
  return <section className="settings-panel personal-panel">
    <h2>Personal intelligence</h2>
    <p>Relationships and history retain their sources. Inferences are suggestions; current source evidence takes precedence.</p>
    <form onSubmit={(event) => { event.preventDefault(); void run(refresh); }}>
      <label>Search people, projects or facts <input value={query} onChange={(e) => setQuery(e.target.value)} maxLength={1000} /></label>
      <label><input type="checkbox" checked={historical} onChange={(e) => setHistorical(e.target.checked)} /> Include historical relationships</label>
      <label>Facts valid as of (optional, this device's time) <input type="datetime-local" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
      <button disabled={busy}>Search and refresh</button>
    </form>
    {note && <p role="status">{note}</p>}
    <h3>Relationships</h3>
    {!links.length && <p>No supported relationships match. Add an annotation to a saved fact below.</p>}
    {links.map((item) => <article className="memory-card" key={item.id}>
      <strong>{item.subject} → {item.relation} → {item.object}</strong>
      <p>{item.epistemic_status} annotation · Source: {item.source_status}, {item.source_epistemic_status}</p>
      <details><summary>Why do you think this?</summary><p>{item.source.content}</p>
        <p>{item.memory_id}</p><p>{item.source.provenance.map((p: any) => `${p.source}: ${p.timestamp}`).join("; ")}</p>
      </details>
      <button disabled={busy} onClick={() => void run(async () => { await bridge.api("/personal/remove", { kind: "link", id: item.id }); await refresh(); })}>Remove annotation</button>
    </article>)}
    <form onSubmit={(event) => { event.preventDefault(); void run(async () => {
      await bridge.api("/personal/link", { memory_id: evidence, subject, relation, object, epistemic_status: inferred ? "INFERRED" : "REPORTED" });
      await refresh(); setNote("Annotation added. Correct an annotation by removing it and reviewing a replacement.");
    }); }}>
      <h4>Add a reviewed relationship</h4>
      <label>Current source memory <select required value={evidence} onChange={(e) => setEvidence(e.target.value)}>
        <option value="">Choose a saved fact</option>{memories.filter((m) => m.status === "CURRENT").map((m) => <option key={m.memory_id} value={m.memory_id}>{m.key}: {m.content}</option>)}
      </select></label>
      <label>Subject <input required maxLength={120} value={subject} onChange={(e) => setSubject(e.target.value)} /></label>
      <label>Relationship <input required maxLength={80} value={relation} onChange={(e) => setRelation(e.target.value)} /></label>
      <label>Object <input required maxLength={120} value={object} onChange={(e) => setObject(e.target.value)} /></label>
      <label><input type="checkbox" checked={inferred} onChange={(e) => setInferred(e.target.checked)} /> This relationship is my inference</label>
      <p>Subject and object must appear in the source. Retracted, forgotten or superseded facts cannot support a current relationship.</p>
      <button disabled={busy || !evidence}>Save annotation</button>
    </form>
    <h3>Timeline</h3>
    {events.map((item) => <article className="memory-card" key={item.memory_id}>
      <strong>{item.key}</strong><p>{item.content}</p><small>{item.status} · {item.epistemic_status} · {item.valid_from} {item.valid_until && `until ${item.valid_until}`}</small>
      <details><summary>Source</summary><p>{item.memory_id}</p><p>{item.provenance.map((p: any) => `${p.source}: ${p.timestamp}`).join("; ")}</p></details>
    </article>)}
    {!events.length && <p>No recorded events match this search/time.</p>}
    <h3>Goals and project progress</h3>
    <form onSubmit={(event) => { event.preventDefault(); void run(async () => {
      await saveGoal({ ...(editing ? { id: editing.id, revision: editing.revision, status: editing.status, progress: editing.progress, due: editing.due } : {}), title, project });
      setEditing(null); setTitle(""); setProject("");
    }); }}>
      <label>Goal <input required maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label>Project <input maxLength={120} value={project} onChange={(e) => setProject(e.target.value)} /></label>
      <button disabled={busy}>{editing ? "Save goal changes" : "Create goal"}</button>
      {editing && <button type="button" onClick={() => { setEditing(null); setTitle(""); setProject(""); }}>Cancel edit</button>}
    </form>
    {goals.map(({ memory_id, history, ...item }) => <article className="memory-card" key={item.id}>
      <strong>{item.title}</strong><p>{item.project} · {item.status} · {item.progress}%</p>
      <button disabled={busy} onClick={() => { setEditing(item); setTitle(item.title); setProject(item.project); }}>Edit</button>
      <button disabled={busy || item.status === "COMPLETED" || item.progress >= 90} onClick={() => void run(() => saveGoal({ ...item, progress: Math.min(90, item.progress + 10) }))}>+10% progress</button>
      <button disabled={busy} onClick={() => void run(() => saveGoal({ ...item, status: item.status === "PAUSED" ? "ACTIVE" : "PAUSED", progress: Math.min(99, item.progress) }))}>{item.status === "PAUSED" ? "Resume" : "Pause"}</button>
      <button disabled={busy || item.status === "COMPLETED"} onClick={() => void run(() => saveGoal({ ...item, status: "COMPLETED", progress: 100 }))}>Complete</button>
      <button disabled={busy} onClick={() => void run(async () => { await bridge.api("/personal/remove", { kind: "goal", id: item.id }); await refresh(); })}>Stop tracking</button>
      <details><summary>Progress history</summary>{history.map((h: any, i: number) => <p key={i}>{h.occurred_at}: {h.status}, {h.progress}%</p>)}<small>Memory: {memory_id}. Forget this goal's memory to erase its supporting statement too.</small></details>
    </article>)}
    <h3>Briefing and routine suggestions</h3>
    <p>{briefing?.active_goals?.length ?? 0} active goals. {briefing?.overdue_ids?.length ?? 0} overdue. This view schedules no actions or notifications.</p>
    {briefing?.routine_candidates?.map((item: any, i: number) => <article className="memory-card" key={i}>
      <strong>INFERRED: {item.description}</strong><p>{item.why}</p><p>{item.correction}</p><small>{item.evidence_ids.join(", ")}</small>
    </article>)}
    {!briefing?.routine_candidates?.length && <p>No repeated activity has enough recorded evidence for a routine suggestion.</p>}
  </section>;
}
