// Only keys, device ID and the pinned core public key persist. No private transcript cache.
const $ = id => document.getElementById(id);
const enc = new TextEncoder(), dec = new TextDecoder();
const algorithm = {name:"ECDSA",hash:"SHA-256"};
const b64 = bytes => { let text=""; for(const b of new Uint8Array(bytes)) text+=String.fromCharCode(b); return btoa(text); };
const bytes = value => Uint8Array.from(atob(value), c=>c.charCodeAt(0));
let identity=null, coreKey=null, session=null, health=null, busy=false, lastReply="", epoch=0;
let context=null, source=null, stream=null, processor=null, recording=[], count=0, timer=null;
const database = new Promise((resolve,reject) => {
  const req=indexedDB.open("adam.mesh.keys.v1",1);
  req.onupgradeneeded=()=>req.result.createObjectStore("keys");
  req.onsuccess=()=>resolve(req.result); req.onerror=()=>reject(new Error("Key storage unavailable"));
});
async function storage(value) {
  const db=await database;
  return new Promise((resolve,reject)=> {
    const tx=db.transaction("keys",value===undefined?"readonly":"readwrite"), s=tx.objectStore("keys");
    const req=value===undefined?s.get("identity"):value===null?s.delete("identity"):s.put(value,"identity");
    tx.oncomplete=()=>resolve(req.result); tx.onerror=()=>reject(new Error("Key storage failed"));
  });
}
function notice(text) { $("notice").textContent=text; }
function stopAudio() {
  source?.stop(); source=null; processor?.disconnect(); processor=null;
  stream?.getTracks().forEach(t=>t.stop()); stream=null; recording=[]; count=0;
  clearTimeout(timer); $("record").textContent="Record voice";
  void context?.close(); context=null;
}
function clearScreen() {
  epoch++; stopAudio(); session=null; lastReply="";
  $("history").replaceChildren(); $("working").textContent=""; $("files").textContent="";
  $("text").value=""; $("query").value=""; $("primary").textContent=""; $("updates").textContent="";
}
async function send(path, body) {
  const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),cache:"no-store",credentials:"omit",signal:AbortSignal.timeout(180000)});
  const raw=await response.text();
  if(raw.length>3600000) throw new Error("Result too large");
  let value; try {value=JSON.parse(raw);} catch {throw new Error("Core unavailable");}
  if(!response.ok) throw new Error(value.error || "Core unavailable");
  return value;
}
async function rpc(operation,payload={}) {
  if(!identity?.device_id || !coreKey) throw new Error("Pair this phone first");
  const request_id=crypto.randomUUID();
  // One controlled retry uses the same idempotency key; ambiguous execution is never redispatched.
  let response;
  for(let attempt=0;attempt<2;attempt++) {
    const raw=enc.encode(JSON.stringify({protocol:1,device_id:identity.device_id,request_id,issued_at:Math.floor(Date.now()/1000),operation,payload}));
    const signature=await crypto.subtle.sign(algorithm,identity.privateKey,raw);
    try {response=await send("/rpc",{message:b64(raw),signature:b64(signature)}); break;}
    catch(error) {if(attempt || !navigator.onLine || !(error instanceof TypeError || error.name==="TimeoutError")) throw error;}
  }
  if(!response || !await crypto.subtle.verify(algorithm,coreKey,bytes(response.signature),bytes(response.message))) throw new Error("Core signature invalid");
  const result=JSON.parse(dec.decode(bytes(response.message)));
  if(result.protocol!==1 || result.request_id!==request_id || result.node_id!==identity.node_id) throw new Error("Core receipt mismatch");
  if(result.status==="PENDING") throw new Error("Pending desktop approval. Compare the fingerprint, then approve and reconnect.");
  if(result.status!=="VERIFIED") throw new Error(result.error || "Request denied");
  if(result.operation!==operation) throw new Error("Core operation mismatch");
  return result.payload;
}
async function action(fn) {
  if(busy) return; busy=true; const expected=epoch;
  document.querySelectorAll("button").forEach(b=>b.disabled=!["stop","lock"].includes(b.id));
  try {await fn(expected);} catch(error) {clearScreen(); notice(error.message+". Reconnect to refresh; no offline commands are queued.");}
  finally {busy=false; document.querySelectorAll("button").forEach(b=>b.disabled=false);}
}
function draw(value) {
  session=value.session_id; $("history").replaceChildren(); lastReply="";
  for(const turn of value.history) for(const [role,text] of [["You",turn.user_text],["ADAM · unverified",turn.assistant_text]]) {
    const li=document.createElement("li"), title=document.createElement("strong");
    title.textContent=role; li.append(title,document.createTextNode(text)); $("history").append(li);
    if(role.startsWith("ADAM")) lastReply=text;
  }
  $("working").textContent=JSON.stringify(value.working,null,2);
  $("primary").textContent=value.primary===identity.device_id?"This phone is primary":"PC or another device is primary. Use phone to chat or speak.";
  $("sessions").value=session;
}
async function sync(expected=epoch) {
  const status=await rpc("status"); if(expected!==epoch) return;
  health=status; $("pairing").hidden=true; $("workspace").hidden=false;
  $("voice").hidden=!status.capabilities.voice; $("search").hidden=!status.capabilities["filesystem.search"];
  $("sessions").replaceChildren(new Option("Choose a session",""));
  for(const sid of status.sessions) $("sessions").append(new Option(sid,sid));
  if(session && status.sessions.includes(session)) {
    const value=await rpc("session",{session_id:session});
    if(expected!==epoch)return;
    draw(value);
  }
  notice("PC online · signed connection verified · model "+status.model_status);
}
$("pair").onsubmit=e=> {e.preventDefault(); void action(async()=> {
  if(identity?.device_id) throw new Error("This key is already registered. Reconnect or explicitly forget it");
  const code=$("code").value.trim(), label=$("label").value.trim(); $("code").value="";
  const pair=await crypto.subtle.generateKey({name:"ECDSA",namedCurve:"P-256"},false,["sign","verify"]);
  const public_key=b64(await crypto.subtle.exportKey("spki",pair.publicKey));
  const signature=b64(await crypto.subtle.sign(algorithm,pair.privateKey,enc.encode(`1\n${code}\n${label}\n${public_key}`)));
  const value=await send("/pair",{protocol:1,code,label,public_key,signature});
  identity={privateKey:pair.privateKey,public_key,device_id:value.device_id,node_id:value.node_id,core:value.public_key};
  coreKey=await crypto.subtle.importKey("spki",bytes(identity.core),{name:"ECDSA",namedCurve:"P-256"},false,["verify"]);
  await storage(identity);
  $("fingerprint").textContent="Device fingerprint: "+Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes(public_key))),b=>b.toString(16).padStart(2,"0")).join("");
  $("workspace").hidden=false; notice("Compare this fingerprint on the PC and approve. Then press Reconnect / sync.");
});};
$("refresh").onclick=()=>void action(sync);
$("new").onclick=()=>void action(async expected=>{const value=await rpc("new_session"); if(expected!==epoch)return; session=value.session_id; await sync(expected);});
$("sessions").onchange=()=>void action(async expected=>{stopAudio(); const value=await rpc("session",{session_id:$("sessions").value}); if(expected===epoch)draw(value);});
$("chat").onsubmit=e=>{e.preventDefault(); void action(async expected=>{
  if(!session) throw new Error("Choose or create a session");
  const text=$("text").value.trim(); if(!text) return;
  notice("PC is thinking…"); await rpc("chat",{session_id:session,text});
  if(expected!==epoch)return; $("text").value=""; await sync(expected);
});};
for(const [id,primary] of [["take",()=>identity.device_id],["return",()=>"desktop"]]) $(id).onclick=()=>void action(async expected=>{stopAudio(); if(!session)throw new Error("Choose a session"); await rpc("handoff",{session_id:session,primary:primary()}); await sync(expected);});
$("search").onsubmit=e=>{e.preventDefault();void action(async expected=>{const result=await rpc("search",{query:$("query").value}); if(expected===epoch)$("files").textContent=JSON.stringify(result.files,null,2);});};
$("lock").onclick=()=>{clearScreen();notice("Screen cleared. Reconnect to reload shared sessions.");};
$("stop").onclick=()=>{epoch++;stopAudio();};
$("repair").onclick=()=>void action(async()=>{clearScreen();await storage(null);identity=null;coreKey=null;$("workspace").hidden=true;$("pairing").hidden=false;$("fingerprint").textContent="";notice("Phone key forgotten. Revoke the old device on your PC; then create a new code.");});
function resample(samples, rate) {
  const output=new Float32Array(Math.floor(samples.length*16000/rate));
  for(let i=0;i<output.length;i++){const at=i*rate/16000,left=Math.floor(at),fraction=at-left;output[i]=samples[left]*(1-fraction)+(samples[Math.min(left+1,samples.length-1)]||0)*fraction;}
  return output;
}
$("record").onclick=()=>void action(async expected=>{
  if(stream) {
    const joined=new Float32Array(count); let at=0; for(const frame of recording){joined.set(frame,at);at+=frame.length;}
    const rate=context.sampleRate; stopAudio(); const data=resample(joined,rate), raw=new Uint8Array(data.length*2), view=new DataView(raw.buffer);
    for(let i=0;i<data.length;i++)view.setInt16(i*2,Math.max(-1,Math.min(1,data[i]))*32767,true);
    if(!data.length) throw new Error("No audio recorded");
    notice("Transcribing on the PC…"); const result=await rpc("transcribe",{pcm16:b64(raw),sample_rate:16000,mode:"push_to_talk",partial:false});
    if(expected===epoch){$("text").value=result.raw_transcript;notice("Review the transcript, then press Send. It has not been sent.");}
  } else {
    stopAudio(); const acquired=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});
    if(expected!==epoch){acquired.getTracks().forEach(t=>t.stop());return;}
    stream=acquired; context=new AudioContext(); await context.resume();
    const input=context.createMediaStreamSource(stream); processor=context.createScriptProcessor(4096,1,1);
    const silence=context.createGain(); silence.gain.value=0;
    processor.onaudioprocess=e=>{if(count>context.sampleRate*55)return;const frame=new Float32Array(e.inputBuffer.getChannelData(0));recording.push(frame);count+=frame.length;};
    input.connect(processor);processor.connect(silence);silence.connect(context.destination);
    $("record").textContent="Finish recording";notice("Microphone on · finish to review");
    timer=setTimeout(()=>{stopAudio();notice("55-second limit reached. Record a shorter message.");},55000);
  }
});
$("speak").onclick=()=>void action(async expected=>{
  if(!lastReply||!session)throw new Error("No reply to read"); stopAudio();
  context=new AudioContext();await context.resume();
  const value=await rpc("speak",{session_id:session,text:lastReply.slice(0,240)});
  if(expected!==epoch||!context)return;
  const state=await rpc("session",{session_id:session});
  if(expected!==epoch||!context)return;
  if(state.primary!==identity.device_id)throw new Error("Phone is no longer primary");
  const raw=bytes(value.pcm16);if(raw.length%2||raw.length>2160000||value.sample_rate!==24000)throw new Error("Invalid audio");
  const audio=context.createBuffer(1,raw.length/2,24000), samples=audio.getChannelData(0),view=new DataView(raw.buffer);
  for(let i=0;i<samples.length;i++)samples[i]=view.getInt16(i*2,true)/32768;
  source=context.createBufferSource();source.buffer=audio;source.connect(context.destination);source.start();notice("Reading the first 240 characters · Stop ends audio");
});
document.addEventListener("visibilitychange",()=>{if(document.hidden){clearScreen();notice("Screen cleared while hidden. Reconnect to reload.");}});
window.addEventListener("offline",()=>{clearScreen();notice("PC connection offline. No commands are queued.");});
window.addEventListener("pagehide",clearScreen);
async function boot() {
  if(!isSecureContext||!crypto.subtle)throw new Error("Trusted HTTPS is required. Install your PC's CA on Android; do not bypass certificate warnings");
  identity=await storage();
  if(identity){$("workspace").hidden=false;coreKey=await crypto.subtle.importKey("spki",bytes(identity.core),{name:"ECDSA",namedCurve:"P-256"},false,["verify"]);await sync();}
  else notice("Enter a desktop pairing code to begin");
}
void boot().catch(error=>notice(error.message));
// Recheck grants and primary ownership even when the user is idle.
setInterval(()=>{
  if(!identity?.device_id || document.hidden)return;
  const expected=epoch;
  void rpc("status").then(async status=>{
    if(expected===epoch)$("updates").textContent=status.notifications?.length?"ADAM update available. Review on your PC.":"";
    if(!busy && session && source){const state=await rpc("session",{session_id:session});if(expected===epoch && state.primary!==identity.device_id)stopAudio();}
  }).catch(error=>{clearScreen();notice(error.message+". Reconnect when the PC is available.");});
},5000);
