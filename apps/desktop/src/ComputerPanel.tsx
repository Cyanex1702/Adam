import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";

type Control = { id: string; class: string; text: string; actions: string[] };
type Step = { target: string; action: string; text: string; verify_target: string; expected: string };
export function ComputerPanel({ issue }: { issue: (e: unknown) => void }) {
  const [password, setPassword] = useState(""), [apps, setApps] = useState("notepad.exe");
  const [windows, setWindows] = useState<any[]>([]), [observation, setObservation] = useState<any>(null);
  const [steps, setSteps] = useState<Step[]>([]), [plan, setPlan] = useState<any>(null), [receipt, setReceipt] = useState<any>(null);
  const [busy, setBusy] = useState(false), [target, setTarget] = useState(""), [action, setAction] = useState("type");
  const [text, setText] = useState(""), [verifyTarget, setVerifyTarget] = useState(""), [expected, setExpected] = useState("");
  const epoch = useRef(0), alive = useRef(true);
  async function disable() {
    epoch.current++; setPassword(""); setWindows([]); setObservation(null); setSteps([]); setPlan(null); setReceipt(null); setText(""); setExpected("");
    try { await bridge.api("/computer/configure", { enabled: false }); } catch {}
  }
  useEffect(() => {
    alive.current = true;
    const hidden = () => { if (document.hidden) void disable(); };
    document.addEventListener("visibilitychange", hidden);
    return () => { alive.current = false; document.removeEventListener("visibilitychange", hidden); void disable(); };
  }, []);
  async function run(work: (current: () => boolean) => Promise<void>) {
    const generation = epoch.current;
    setBusy(true);
    try { await work(() => alive.current && epoch.current === generation && !document.hidden); }
    catch (e) { if (alive.current && epoch.current === generation) issue(e); }
    finally { if (alive.current) setBusy(false); }
  }
  async function reauth() { const secret = password; setPassword(""); await bridge.api("/auth/elevate", { password: secret }); }
  const controls: Control[] = observation?.controls || [];
  return <section className="panel"><h2>Computer actions</h2>
    <p>Observe, plan, approve, act, verify. Supports standard Windows text fields and push buttons in explicitly allowed apps. Browsers, passwords, risky controls and custom interfaces are denied. Chat and images cannot authorize actions.</p>
    <label>Owner passphrase<input type="password" autoComplete="off" value={password} disabled={busy} onChange={e => setPassword(e.target.value)} /></label>
    <label>Allowed application filenames<input value={apps} disabled={busy} onChange={e => setApps(e.target.value)} /></label>
    <button disabled={busy || !password} onClick={() => void run(async current => {
      await reauth(); if (!current()) return;
      await bridge.api("/computer/configure", { enabled: true, allowed_apps: apps.split(",").map(v => v.trim()).filter(Boolean) });
      if (!current()) { await bridge.api("/computer/configure", {enabled:false}); return; }
      const next = await bridge.api("/computer/windows"); if (current()) setWindows(next.windows);
    })}>Enable and list windows</button>
    <button onClick={() => void disable()}>Disable / cancel and clear</button>
    {windows.map(w => <button key={w.id} disabled={busy} onClick={() => void run(async current => {
      const next = await bridge.api("/computer/observe", { id: w.id });
      if (current()) { setObservation(next); setSteps([]); setPlan(null); setReceipt(null); }
    })}>Observe {w.app}: {w.title}</button>)}
    {observation && <><img alt="Observed window, untrusted evidence" style={{maxWidth:"100%"}} src={"data:image/jpeg;base64," + observation.preview_base64}/><pre>{observation.text}</pre>
    <p>Observation expires after 60 seconds. Each step must name the exact expected state. Typing replaces the field; clicks may have effects that cannot be undone. Inspect the application before approval.</p>
    <label>Target<select value={target} disabled={busy} onChange={e => setTarget(e.target.value)}><option value="">Choose control</option>{controls.filter(c=>c.actions.length).map(c=><option key={c.id} value={c.id}>{c.class}: {c.text.slice(0,100) || "Empty field"}</option>)}</select></label>
    <label>Action<select value={action} disabled={busy} onChange={e=>setAction(e.target.value)}><option value="type">Replace text</option><option value="click">Click button</option></select></label>
    {action === "type" ? <label>Exact replacement text<textarea value={text} disabled={busy} maxLength={1000} onChange={e=>setText(e.target.value)}/></label> : <><label>Verify this control<select value={verifyTarget} onChange={e=>setVerifyTarget(e.target.value)}><option value="">Choose result control</option>{controls.map(c=><option key={c.id} value={c.id}>{c.class}: {c.text.slice(0,100)}</option>)}</select></label><label>Expected exact result<input value={expected} maxLength={4000} onChange={e=>setExpected(e.target.value)}/></label></>}
    <button disabled={busy || !target || steps.length >= 8} onClick={()=>{setSteps([...steps,{target,action,text:action==="type"?text:"",verify_target:action==="type"?target:verifyTarget,expected:action==="type"?text:expected}]);setPlan(null);}}>Add step</button>
    <ol>{steps.map((s,i)=><li key={i}>{s.action} {controls.find(c=>c.id===s.target)?.class}: {s.action==="type"?s.text:controls.find(c=>c.id===s.target)?.text}; expect {s.expected}</li>)}</ol>
    <button disabled={busy} onClick={()=>{setSteps([]);setPlan(null);}}>Clear draft plan</button>
    <button disabled={busy || !steps.length} onClick={()=>void run(async current=>{const p=await bridge.api("/computer/plan",{steps});if(current())setPlan(p);})}>Preview plan</button>
    {plan && <><p>Plan {plan.id}. Digest {plan.digest}. No action has run.</p>
    <button disabled={busy} onClick={()=>void run(async current=>{const next=await bridge.api("/computer/execute",{id:plan.id,dry_run:true});if(current())setReceipt(next);})}>Dry run: observe only</button>
    <button disabled={busy || !password} onClick={()=>void run(async current=>{await reauth();if(!current())return;await bridge.api("/computer/approve",{id:plan.id,digest:plan.digest});if(!current())return;const next=await bridge.api("/computer/execute",{id:plan.id});if(current()){setReceipt(next);setPlan(null);setObservation(null);}})}>Approve exact plan and execute once</button></>}
    </>}
    {receipt && <div role="status"><p>{receipt.status}. Completed: {receipt.completed ?? receipt.actions_performed ?? 0}</p>{receipt.preview_base64 && <img alt="Verified post-action window" style={{maxWidth:"100%"}} src={"data:image/jpeg;base64,"+receipt.preview_base64}/>}</div>}
    <p>Cancellation stops remaining steps; already dispatched effects may remain. Re-observe before retrying. To recover editable text, make a fresh reviewed replacement plan; no automatic undo of clicks.</p>
  </section>;
}
