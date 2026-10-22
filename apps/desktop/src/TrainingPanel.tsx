import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";

export function TrainingPanel({ issue }: { issue: (error: unknown) => void }) {
  const [password, setPassword] = useState(""), [status, setStatus] = useState<any>(null);
  const [prompt, setPrompt] = useState(""), [response, setResponse] = useState("");
  const [category, setCategory] = useState("response_behavior"), [approved, setApproved] = useState(false);
  const [dataset, setDataset] = useState<any>(null), [recipe, setRecipe] = useState("");
  const [base, setBase] = useState(""), [candidate, setCandidate] = useState(""), [target, setTarget] = useState("formatting");
  const [assessment, setAssessment] = useState<any>(null), [busy, setBusy] = useState(false);
  const alive = useRef(true), epoch = useRef(0);
  useEffect(() => {
    alive.current = true;
    function hidden() { if (document.hidden) {
      epoch.current++; setPassword(""); setStatus(null); setDataset(null); setRecipe("");
      setPrompt(""); setResponse(""); setApproved(false); setBase(""); setCandidate(""); setAssessment(null);
    } }
    document.addEventListener("visibilitychange", hidden);
    return () => { alive.current = false; epoch.current++; document.removeEventListener("visibilitychange", hidden); };
  }, []);
  async function run(work: (stamp: number) => Promise<void>) {
    const stamp = epoch.current; setBusy(true);
    try { await work(stamp); } catch (error) { if (alive.current && stamp === epoch.current) issue(error); }
    finally { if (alive.current && stamp === epoch.current) setBusy(false); }
  }
  function current(stamp: number) { return alive.current && stamp === epoch.current && !document.hidden; }
  return <section className="settings-panel">
    <h2>Behavior training experiment</h2>
    <p>Optional and off by default. No validated adapter is included or active. Personal facts stay in memory, outside model weights.</p>
    <form onSubmit={(e) => { e.preventDefault(); void run(async (stamp) => {
      const secret = password; setPassword("");
      await bridge.api("/auth/elevate", { password: secret });
      const result = await bridge.api("/training"); if (current(stamp)) setStatus(result);
    }); }}>
      <label>Owner passphrase <input type="password" required autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      <button disabled={busy}>Unlock experiment controls</button>
    </form>
    {status && <>
      <p>{status.enabled ? "Experiment enabled" : "Experiment disabled"} · {status.approved_examples} approved examples · {status.experiment}</p>
      <button disabled={busy} onClick={() => void run(async (stamp) => { const value = await bridge.api("/training/configure", { enabled: !status.enabled }); if (current(stamp)) { setStatus(value); setDataset(null); setRecipe(""); } })}>{status.enabled ? "Disable experiment" : "Enable experiment"}</button>
      {status.enabled && <>
        <form onSubmit={(e) => { e.preventDefault(); void run(async (stamp) => {
          await bridge.api("/training/example", { category, prompt, response, approved, synthetic_behavior_only: approved, permission_to_export: approved });
          const result = await bridge.api("/training"); if (current(stamp)) { setStatus(result); setPrompt(""); setResponse(""); setApproved(false); setDataset(null); }
        }); }}>
          <h3>Review one synthetic behavior example</h3>
          <label>Behavior <select value={category} onChange={(e) => setCategory(e.target.value)}>{["response_behavior", "tool_selection", "structured_output", "formatting"].map((c) => <option key={c}>{c}</option>)}</select></label>
          <label>Fictional prompt <textarea required maxLength={2000} value={prompt} onChange={(e) => setPrompt(e.target.value)} /></label>
          <label>Preferred behavior <textarea required maxLength={2000} value={response} onChange={(e) => setResponse(e.target.value)} /></label>
          <label><input type="checkbox" required checked={approved} onChange={(e) => setApproved(e.target.checked)} /> I reviewed both texts: they contain only synthetic behavior examples, no personal facts or credentials, and I approve export for training.</label>
          <button disabled={busy || !approved}>Approve this example</button>
        </form>
        <h3>Review dataset and recipe</h3>
        <p>Review the complete text before copying it to a separate GPU environment. Nothing uploads automatically. The recipe requires at least 20 distinct prompts and a pinned base-model revision.</p>
        <button disabled={busy} onClick={() => void run(async (stamp) => { const value = await bridge.api("/training/dataset", {}); if (current(stamp)) setDataset(value); })}>Review dataset JSONL</button>
        <button disabled={busy} onClick={() => void run(async (stamp) => { const value = await bridge.api("/training/recipe"); if (current(stamp)) setRecipe(value.script); })}>Show GPU training recipe</button>
        {dataset && <><p>{dataset.examples} examples · SHA-256: {dataset.sha256}</p><label>Copy as dataset.jsonl <textarea readOnly value={dataset.jsonl} rows={10} /></label><p>{dataset.warning}</p></>}
        {recipe && <label>Experimental train-adapter.py — no training run has been verified <textarea readOnly value={recipe} rows={14} /></label>}
        <h3>Compare base and candidate</h3>
        <p>Paste matching full-suite real-model reports. Scripted probes, different fixtures, regressions and absent improvement cannot qualify. Passing this check still requires human review and does not activate an adapter.</p>
        <label>Base report JSON <textarea maxLength={28000} value={base} onChange={(e) => setBase(e.target.value)} /></label>
        <label>Candidate report JSON <textarea maxLength={28000} value={candidate} onChange={(e) => setCandidate(e.target.value)} /></label>
        <label>Target evaluation category <input maxLength={80} value={target} onChange={(e) => setTarget(e.target.value)} /></label>
        <button disabled={busy || !base || !candidate} onClick={() => void run(async (stamp) => { const value = await bridge.api("/training/compare", { base: JSON.parse(base), candidate: JSON.parse(candidate), target }); if (current(stamp)) setAssessment(value); })}>Assess evidence</button>
        {assessment && <pre>{JSON.stringify(assessment, null, 2)}</pre>}
      </>}
    </>}
  </section>;
}
