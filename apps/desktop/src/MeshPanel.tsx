import { useEffect, useState } from "react";
import * as bridge from "./bridge";
import { friendlyError } from "./state";

type Device = { id: string; label: string; fingerprint: string; status: string; search: boolean; voice: boolean };
type State = { listening: boolean; url: string; certificate: string; devices: Device[]; node_id: string; error?: string };
export function MeshPanel({ sessionId, stopVoice }: { sessionId: string | null; stopVoice: () => void }) {
  const [state, setState] = useState<State | null>(null), [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false), [code, setCode] = useState("");
  const [search, setSearch] = useState(false), [voice, setVoice] = useState(false), [consent, setConsent] = useState(false);
  useEffect(() => setConsent(false), [sessionId]);
  async function refresh() { setState(await bridge.api<State>("/developer/mesh")); }
  useEffect(() => {
    let active = true;
    const load = () => bridge.api<State>("/developer/mesh").then(v => { if (active) setState(v); }).catch(e => { if (active) setNotice(friendlyError(e)); });
    void load(); const timer = setInterval(load, 5000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  async function action(path: string, body: unknown = {}) {
    if (busy) return; setBusy(true); setNotice("");
    try {
      stopVoice();
      const value = await bridge.api<any>("/developer/mesh/" + path, body);
      setCode(path === "code" ? value.code : ""); await refresh();
      setNotice(path === "share" ? "Shared this session's history and working state. Approvals stay on the PC." : "Updated.");
    } catch (e) { setNotice(friendlyError(e)); } finally { setBusy(false); }
  }
  return <section aria-label="Mobile device mesh" style={{overflowWrap:"anywhere"}}>
    <h2>Android connection</h2>
    <p>Prepare trusted HTTPS with scripts/setup-mesh.ps1. The listener starts only when you press Start. Internet access is unavailable.</p>
    <p>{state?.listening ? "Listening · " + state.url : "Listener off"}</p>
    {state?.error && <p role="alert">{state.error}. Local chat remains available. Preserve the mesh directory and follow the recovery instructions before re-pairing.</p>}
    <button disabled={busy || !state} onClick={() => void action(state?.listening ? "stop" : "start")}>{state?.listening ? "Stop listener" : "Start listener"}</button>{" "}
    <button disabled={busy || !state?.listening} onClick={() => void action("code")}>Create five-minute pairing code</button>
    {code && <p>Enter on your phone: <code>{code}</code>. Compare the pending device fingerprint before approving.</p>}
    <p>Certificate to transfer to Android: {state?.certificate}</p>
    <p>Selected session: {sessionId ?? "Open a conversation on the PC to share it."}</p>
    <label><input type="checkbox" checked={search} onChange={e => setSearch(e.target.checked)} /> Allow read-only search of PC tool-sandbox filenames</label><br />
    <label><input type="checkbox" checked={voice} onChange={e => setVoice(e.target.checked)} /> Allow local speech recognition and synthesis</label><br />
    <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /> Share the selected session's entire retained history and working state</label>
    {state?.devices.map(d => <article key={d.id}>
      <strong>{d.label} · {d.status}</strong><p>Fingerprint: <code>{d.fingerprint}</code></p>
      {d.status === "PENDING" && <button disabled={busy} onClick={() => void action("approve", {device_id:d.id,search,voice})}>Approve this device</button>}
      {d.status === "APPROVED" && <>
        <button disabled={busy || !consent || !sessionId} onClick={() => void action("share", {device_id:d.id,session_id:sessionId,consent:true})}>Share selected session</button>{" "}
        <button disabled={busy || !sessionId} onClick={() => void action("handoff", {session_id:sessionId,primary:d.id})}>Hand session to phone</button>{" "}
      </>}
      {d.status !== "REVOKED" && <button disabled={busy} onClick={() => void action("revoke", {device_id:d.id})}>Revoke</button>}
    </article>)}
    <button disabled={busy || !sessionId} onClick={() => void action("handoff", {session_id:sessionId,primary:"desktop"})}>Return selected session to PC</button>
    <p role="status">{notice}</p>
  </section>;
}
