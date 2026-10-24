import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";

export function ModelLibraryPanel({ issue }: { issue: (error: unknown) => void }) {
  const [status, setStatus] = useState<any>(null), [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false), [note, setNote] = useState("");
  const [roles, setRoles] = useState<Record<string, string>>({});
  const alive = useRef(true);
  useEffect(() => { alive.current = true; void refresh(); return () => { alive.current = false; }; }, []);
  async function refresh() { try { const next = await bridge.api("/models/library"); if (alive.current) setStatus(next); } catch (error) { if (alive.current) issue(error); } }
  async function run(path: string, body: unknown) {
    setBusy(true); setNote("");
    try { const result = await bridge.api(path, body); if (alive.current) { setNote(result.switched ? "Model loaded for this run. The saved startup default is unchanged; automatic selection can choose again for the next task. Your history and memory stay in the framework." : "Done. Review the model list below."); await refresh(); } }
    catch (error) { if (alive.current) issue(error); }
    finally { if (alive.current) setBusy(false); }
  }
  const approved = status?.entries?.filter((item: any) => item.approved).length ?? 0;
  return <section className="page model-library">
    <span className="section-number">YOUR LOCAL MODELS</span>
    <h2>Choose the brain. Keep the context.</h2>
    <p>Find GGUF models already on this PC. Scanning reads names, file sizes and the GGUF header; it never loads or approves a model automatically.</p>
    <div className="diagnostic-good"><strong>Start here</strong><p>1. Scan common folders or add your model folder. 2. Approve the models you trust and choose their roles. 3. Turn on automatic selection if you want ADAM to switch between them.</p></div>
    <label>Optional model folder<input value={folder} onChange={event => setFolder(event.target.value)} placeholder="For example: D:\Models" disabled={busy} /></label>
    <p className="fine-print">An empty field searches ADAM’s models, Downloads, Models, LM Studio and the Hugging Face cache. Searches are bounded; add a specific folder to look elsewhere. Linked folders and network shares are skipped.</p>
    <div className="diagnostic-toolbar"><button disabled={busy} onClick={() => void run("/models/scan", { folder: folder.trim() || null })}>{busy ? "Working…" : "Scan for local models"}</button><button disabled={busy} onClick={() => void refresh()}>Refresh</button></div>
    <div className="setting-row"><div><strong>Automatic model selection</strong><p>Uses approved roles, task-complexity estimates and available RAM. Eco prefers smaller models; Priority prefers the requested role. A switch unloads the previous owned model first and can take time. Role labels do not prove model quality.</p></div><input type="checkbox" aria-label="Automatic model selection" checked={status?.automatic ?? false} disabled={busy || (!approved && !status?.automatic)} onChange={event => void run("/models/automatic", { enabled: event.target.checked })} /></div>
    {!status?.entries?.length && <p>No models discovered yet. If you have none installed, use Setup and recovery to download a supported preset.</p>}
    {status?.entries?.map((item: any) => <article className="local-model-card" key={item.id}>
      <h3>{item.path.split(/[\\/]/).at(-1)}</h3><p className="model-path">{item.path}</p>
      <p>{(item.bytes / 1024 ** 3).toFixed(2)} GB · {item.approved ? "Approved and checksummed" : "Discovered, not approved"}{status.active_profile === item.profile_id && item.approved ? " · Active" : ""}</p>
      <label>Preferred role<select value={roles[item.id] ?? item.role} disabled={busy} onChange={event => setRoles(old => ({ ...old, [item.id]: event.target.value }))}><option value="quick">Quick chat</option><option value="balanced">Balanced</option><option value="reasoning">Reasoning / complex tasks</option></select></label>
      <div className="diagnostic-toolbar"><button disabled={busy} onClick={() => void run("/models/approve", { id: item.id, role: roles[item.id] ?? item.role })}>Approve file &amp; verify checksum</button><button disabled={busy || !item.approved || status.active_profile === item.profile_id} onClick={() => void run("/models/select", { id: item.id })}>Use now</button></div>
    </article>)}
    {status?.last_route && <div className="diagnostic-good"><strong>Last selection</strong><p>{status.last_route.reason}</p>{status.last_route.task_estimate && <p>Estimated task: {status.last_route.task_estimate}</p>}{status.last_route.error && <code>{status.last_route.error}</code>}</div>}
    <p className="fine-print">Local CPU GGUF models only. Other formats such as Ollama manifests need a separate compatible adapter. Scanning does not download weights. Automatic choices remain subject to runtime resource checks.</p>
    {note && <p role="status">{note}</p>}
  </section>;
}
