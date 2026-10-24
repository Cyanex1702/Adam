import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";
import { friendlyError } from "./state";

const gib = (value: unknown) => typeof value === "number" ? `${(value / 1024 ** 3).toFixed(2)} GB` : "Reading unavailable";

export function DiagnosticsPanel({ owner, reconnect, back, serviceError, issue }: { owner: boolean; reconnect: () => void; back: () => void; serviceError?: string | null; issue: (e: unknown) => void }) {
  const [report, setReport] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; void refresh(); return () => { alive.current = false; }; }, []);
  async function refresh() {
    setBusy(true);
    try { const next = await bridge.api("/desktop/diagnostics"); if (alive.current) setReport(next); }
    catch (error) { if (alive.current) {
      const value = serviceError ?? error;
      const code = typeof value === "string" && /^[A-Z][A-Z0-9_.]{1,99}$/.test(value) ? value : "DESKTOP.CONNECTION_LOST";
      setReport({ report_format: 1, source: "desktop_fallback", performance_mode: "unknown", resources: {}, model: { lifecycle: "SERVICE_UNAVAILABLE", id: "unavailable" }, issues: [{ code, title: friendlyError(code), next_step: "Reconnect once. If the same code returns, preserve your profile and share this report. No conversations or credentials are included." }] }); issue(code);
    } }
    finally { if (alive.current) setBusy(false); }
  }
  async function change(path: string, body: unknown) {
    setBusy(true); setNote("");
    try { const result = await bridge.api(path, body); if (result.status && result.status !== "HEALTHY") throw result.reason ?? "MODEL.UNAVAILABLE"; if (alive.current) { setNote("Applied. Your conversations and memory are unchanged."); await refresh(); } }
    catch (error) { if (alive.current) issue(error); }
    finally { if (alive.current) setBusy(false); }
  }
  return <section className="page diagnostics-page">
    <span className="section-number">WORKSPACE HEALTH</span>
    <h2>Know what needs attention.</h2>
    <p>Live resource checks and specific recovery steps. A model problem does not mean your saved conversations are damaged.</p>
    <div className="diagnostic-toolbar">
      <button onClick={back}>{owner ? "Back to conversation" : "Back to sign in"}</button>
      <button disabled={busy} onClick={() => void refresh()}>{busy ? "Checking…" : "Refresh checks"}</button>
      <button onClick={reconnect} disabled={busy}>Reconnect local service</button>
      <button disabled={!report} onClick={() => { void navigator.clipboard.writeText(JSON.stringify(report, null, 2)).then(() => setNote("Diagnostic report copied. It contains no conversation text, credentials or personal file paths."), () => setNote("Copy the report manually from Technical details below.")); }}>Copy safe report</button>
    </div>
    {!report && !busy && <div className="diagnostic-issue"><h3>Local service unavailable</h3><p>The desktop could not obtain a report. Reconnect once. If it still fails, keep the diagnostic code shown above; repeated restarts will not repair a configuration problem.</p></div>}
    {report && <>
      <div className="health-grid">
        <article><span>Available memory</span><strong>{gib(report.resources.ram_available_bytes)}</strong><small>{typeof report.resources.ram_used_percent === "number" ? `${report.resources.ram_used_percent.toFixed(1)}% of system RAM in use` : "Usage unavailable"}</small>{report.resources.limits && <small>Minimum free: {report.resources.limits.min_free_ram_mib} MB · Usage ceiling: {report.resources.limits.ram_pressure_percent}%</small>}</article>
        <article><span>Free storage</span><strong>{gib(report.resources.disk_free_bytes)}</strong><small>Drive containing your ADAM profile</small></article>
        <article><span>Model state</span><strong>{String(report.model.lifecycle).replaceAll("_", " ")}</strong><small>{report.model.id}</small></article>
      </div>
      {report.issues.length === 0 ? <div className="diagnostic-good">Resource and startup checks passed. Model readiness is shown separately above.</div> : report.issues.map((item: any) => <article className="diagnostic-issue" key={item.code}><code>{item.code}</code><h3>{item.title}</h3><p>{item.next_step}</p></article>)}
      {report.storage?.stores && <div className="hint-card"><h3>Profile database checks</h3><p>These are ADAM’s standard database names. Missing databases are normal before the feature is first used. A healthy older version is upgraded automatically during startup.</p><ul>{Object.entries(report.storage.stores).map(([name, status]) => <li key={name}><code>{name}</code>: {String(status).replaceAll("_", " ")}{report.storage.schemas?.[name] !== undefined ? ` · schema ${report.storage.schemas[name]}` : ""}</li>)}</ul></div>}
      <h3>How should ADAM share your PC?</h3>
      <p>Both modes retain memory and storage safety checks. They change only ADAM’s own inference process; other applications are never closed or reprioritized.</p>
      <div className="performance-grid">
        <article className={report.performance_mode === "eco" ? "active" : ""}><h3>Eco</h3><p>Leave more CPU time for your other apps. Uses fewer inference threads and below-normal process priority.</p><button disabled={!owner || busy || report.performance_mode === "eco"} onClick={() => void change("/performance", { mode: "eco" })}>{report.performance_mode === "eco" ? "Eco is active" : "Use Eco"}</button></article>
        <article className={report.performance_mode === "priority" ? "active" : ""}><h3>Priority</h3><p>Give ADAM more CPU time and a larger memory-use allowance. This cannot create free RAM or make an oversized model fit.</p><button disabled={!owner || busy || report.performance_mode === "priority"} onClick={() => void change("/performance", { mode: "priority" })}>{report.performance_mode === "priority" ? "Priority is active" : "Use Priority"}</button></article>
      </div>
      <p className="fine-print">Changing mode reloads an active ADAM-owned model. Sign into the owner workspace to change settings.</p>
      {owner && <button disabled={busy} onClick={() => void change("/model/reload", {})}>Retry loading model</button>}
      <div className="hint-card"><strong>What is running?</strong><p>{report.model?.process?.running ? `ADAM owns model process ${report.model.process.pid}. Quitting ADAM stops it and frees its RAM.` : "No ADAM-owned model is running. External servers are managed by the application that started them."}</p><p>Model inference has no microphone capture capability. Desktop voice records only when enabled, and stops when hidden.</p></div>
      <details><summary>Technical details · safe to share</summary><pre>{JSON.stringify(report, null, 2)}</pre></details>
    </>}
    {note && <p role="status">{note}</p>}
  </section>;
}
