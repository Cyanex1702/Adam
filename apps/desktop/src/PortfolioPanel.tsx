import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";

export function PortfolioPanel({ mode, issue }: { mode: string; issue: (error: unknown) => void }) {
  const [status, setStatus] = useState<any>(null), [benchmarks, setBenchmarks] = useState<any>(null);
  const [tool, setTool] = useState<any>(null), [text, setText] = useState("Fictional Cedar demonstration note.");
  const [busy, setBusy] = useState(false), epoch = useRef(0), alive = useRef(true);
  useEffect(() => {
    alive.current = true; void run(async () => {
      const stamp = epoch.current;
      const [info, report] = await Promise.all([bridge.api("/portfolio"), bridge.api("/portfolio/benchmarks")]);
      if (alive.current && stamp === epoch.current && !document.hidden) { setStatus(info); setBenchmarks(report); }
    });
    function hidden() { if (document.hidden) { epoch.current++; setTool(null); setText(""); setBusy(false); } }
    document.addEventListener("visibilitychange", hidden);
    return () => { alive.current = false; epoch.current++; document.removeEventListener("visibilitychange", hidden); };
  }, []);
  async function run(work: () => Promise<void>) {
    setBusy(true); try { await work(); } catch (error) { if (alive.current) issue(error); }
    finally { if (alive.current) setBusy(false); }
  }
  async function demoTool(action: string) {
    const stamp = epoch.current;
    const value = await bridge.api("/portfolio/demo-tool", { action, text });
    if (alive.current && stamp === epoch.current && !document.hidden) setTool(value);
  }
  return <section className="settings-panel">
    <h2>Demo and benchmarks</h2>
    <p>{mode === "demo" ? "You are using a separate fictional profile. No owner files or conversations were copied." : "Switch to the fictional demo in Settings to try the sandbox. Benchmark evidence is sanitized and available here."}</p>
    <h3>Try ADAM</h3>
    <ol>{status?.walkthrough?.map((step: string) => <li key={step}>{step}</li>)}</ol>
    {mode === "demo" && <>
      <h3>Fictional note sandbox</h3>
      <label>Demo note <textarea maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} /></label>
      <button disabled={busy} onClick={() => void run(() => demoTool("inspect"))}>Inspect sandbox</button>
      <button disabled={busy || !text} onClick={() => void run(() => demoTool("write_note"))}>Write and verify note</button>
      <button disabled={busy} onClick={() => void run(() => demoTool("undo_note"))}>Undo note</button>
      {tool && <pre>{JSON.stringify(tool, null, 2)}</pre>}
    </>}
    <h3>Measured framework evidence</h3>
    {benchmarks?.status === "MEASURED" ? <>
      <p>{benchmarks.model.display_name || benchmarks.model.model_id} · {benchmarks.execution} · {benchmarks.suite} · Release {benchmarks.release}</p>
      <p>{benchmarks.note}</p>
      <table><thead><tr><th>Category</th><th>Passed / cases</th><th>Rate</th></tr></thead><tbody>{Object.entries(benchmarks.categories).map(([name, value]: [string, any]) => <tr key={name}><td>{name}</td><td>{value.passed} / {value.total}</td><td>{(value.rate * 100).toFixed(1)}%</td></tr>)}</tbody></table>
      <p>{benchmarks.critical_failures} critical failures. {benchmarks.latency_scope}</p>
      <details><summary>Individual measurements</summary><table><thead><tr><th>Scenario</th><th>Result</th><th>ms</th></tr></thead><tbody>{benchmarks.cases.map((item: any) => <tr key={item.name}><td>{item.name}</td><td>{item.passed ? "Passed" : "Failed"}</td><td>{item.duration_ms}</td></tr>)}</tbody></table></details>
      <p>VRAM: unavailable. Voice benchmarks: unavailable.</p><small>Dataset: {benchmarks.dataset_digest}<br />Report SHA-256: {benchmarks.report_sha256}</small>
    </> : <p>No bundled benchmark measurement is available.</p>}
    <h3>Release limits</h3><ul>{status?.limits?.map((limit: string) => <li key={limit}>{limit}</li>)}</ul>
  </section>;
}
