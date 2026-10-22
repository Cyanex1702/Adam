import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";
export function DistributionPanel({ issue }: { issue:(e:unknown)=>void }) {
  const [status,setStatus]=useState<any>(null),[setup,setSetup]=useState<any>(null),[result,setResult]=useState<any>(null);
  const [password,setPassword]=useState(""),[backupPassword,setBackupPassword]=useState(""),[path,setPath]=useState(""),[hash,setHash]=useState("");
  const [channel,setChannel]=useState("stable"),[model,setModel]=useState("qwen3-4b-instruct"),[staged,setStaged]=useState<any>(null),[busy,setBusy]=useState(false);
  const alive=useRef(true),epoch=useRef(0);
  useEffect(()=>{alive.current=true;void refresh();const hidden=()=>{if(document.hidden){epoch.current++;setPassword("");setBackupPassword("");setResult(null);setStaged(null);void bridge.api("/distribution/cancel",{}).catch(()=>{});}};document.addEventListener("visibilitychange",hidden);return()=>{alive.current=false;epoch.current++;document.removeEventListener("visibilitychange",hidden);void bridge.api("/distribution/cancel",{}).catch(()=>{});};},[]);
  async function refresh(){try{const [a,b]=await Promise.all([bridge.api("/distribution"),bridge.api("/distribution/setup")]);if(alive.current){setStatus(a);setSetup(b);}}catch(e){if(alive.current)issue(e);}}
  async function run(work:(current:()=>boolean)=>Promise<void>){const n=epoch.current;setBusy(true);try{await work(()=>alive.current&&epoch.current===n&&!document.hidden);}catch(e){if(alive.current&&epoch.current===n)issue(e);}finally{if(alive.current)setBusy(false);}}
  async function reauth(){const secret=password;setPassword("");await bridge.api("/auth/elevate",{password:secret});}
  async function activate(mode:string,id:string){await run(async current=>{await reauth();if(!current())return;const ticket=await bridge.api("/distribution/authorize",{id,mode});if(!current())return;await bridge.applyRelease(ticket.ticket,ticket.token);});}
  return <section className="panel"><h2>Setup, updates and recovery</h2>
    <p>Data folder: {status?.data_dir}. Managed home: {status?.home}. Active release: {status?.active?.release||"Installed version"}.</p>
    <label>Owner passphrase<input type="password" autoComplete="off" value={password} disabled={busy} onChange={e=>setPassword(e.target.value)}/></label>
    <button disabled={busy} onClick={()=>void refresh()}>Refresh checks</button>
    <h3>Guided model setup</h3><p>{setup?.recommendation}</p><p role="status">Setup: {setup?.progress?.status || "IDLE"}; downloaded {Math.round((setup?.progress?.bytes || 0)/1024/1024)} MiB. Keep ADAM open and use Refresh checks for progress. {setup?.progress?.error || ""}</p><p>RAM: {setup?Math.round(setup.hardware.ram_total_bytes/1024**3):"?"} GiB. Runtime installed: {String(setup?.hardware.runtime.llama_executable_present??false)}.</p>
    <p>The app includes Python and dependencies. A cancellable background job downloads pinned, checksum-verified public files (about 3 GB plus runtime), installs a CPU profile, and requires a service restart. No model is started by this button.</p>
    <select value={model} disabled={busy} onChange={e=>setModel(e.target.value)}><option value="qwen3-4b-instruct">Qwen3 4B Q4 - normal</option><option value="qwen3-4b-abliterated">Qwen3 4B Q4 - abliterated, output unverified</option></select>
    <button disabled={busy||!password} onClick={()=>void run(async current=>{await reauth();if(!current())return;const next=await bridge.api("/distribution/model",{model_id:model});if(current())setResult(next);})}>Download / verify selected model and runtime</button>
    <button onClick={()=>void bridge.api("/distribution/cancel",{}).catch(issue)}>Cancel model setup</button>
    <h3>Update or restore</h3><p>Paste the full path to a local ADAM release package or encrypted portable backup. Release packages must have a SHA-256 obtained from a trusted source. This is explicit approval to run the selected release code.</p>
    <label>Local file path<input value={path} disabled={busy} onChange={e=>setPath(e.target.value)}/></label>
    <label>Release package SHA-256<input value={hash} maxLength={64} disabled={busy} onChange={e=>setHash(e.target.value.trim().toLowerCase())}/></label>
    <select value={channel} disabled={busy} onChange={e=>setChannel(e.target.value)}><option>stable</option><option>beta</option><option>dev</option></select>
    <button disabled={busy||!password||!path||hash.length!==64} onClick={()=>void run(async current=>{await reauth();if(!current())return;const next=await bridge.api("/distribution/stage",{path,sha256:hash,channel});if(current()){setStaged({...next,mode:"update"});setResult(next);}})}>Verify and stage release</button>
    <label>Portable backup passphrase (at least 12 characters)<input type="password" autoComplete="off" value={backupPassword} disabled={busy} onChange={e=>setBackupPassword(e.target.value)}/></label>
    <button disabled={busy||!password||backupPassword.length<12} onClick={()=>void run(async current=>{const secret=backupPassword;setBackupPassword("");await reauth();if(!current())return;const next=await bridge.api("/distribution/backup",{password:secret});if(current())setResult(next);})}>Create encrypted portable backup</button>
    <button disabled={busy||!password||!path||backupPassword.length<12} onClick={()=>void run(async current=>{const secret=backupPassword;setBackupPassword("");await reauth();if(!current())return;const next=await bridge.api("/distribution/restore",{path,password:secret});if(current()){setStaged({...next,mode:"restore"});setResult(next);}})}>Stage restore into a fresh profile</button>
    {staged&&<><p>Staged {staged.release||"portable restore"}, ID {staged.id}. Activation closes ADAM, takes an encrypted local snapshot, tests a cloned profile, then restarts. Failed health checks retain the prior active version and profile.</p><button disabled={busy||!password} onClick={()=>void activate(staged.mode,staged.id)}>Approve activation and restart ADAM</button></>}
    <p>Rollback returns to the pre-update profile. Newer changes remain in the current generation and encrypted snapshot, but will not appear in the restored profile.</p>
    <button disabled={busy||!password||!status?.previous} onClick={()=>void activate("rollback",status.previous.id)}>Approve rollback and restart ADAM</button>
    <button disabled={busy||!password} onClick={()=>void run(async current=>{await reauth();if(!current())return;const next=await bridge.api("/distribution/reindex",{});if(current())setResult(next);})}>Rebuild local knowledge indexes</button>
    <p>On a different PC: select a compatible model, re-pair phones in Devices, re-enroll speakers and re-enter vault secrets. Public weights, device keys and derived indexes are excluded from portable backups. Human testing on a clean secondary PC is still required.</p>
    {result&&<pre role="status">{JSON.stringify(result,null,2)}</pre>}
  </section>;
}
