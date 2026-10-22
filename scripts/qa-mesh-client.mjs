// Run the shipped client RPC code with real WebCrypto and trusted loopback TLS.
// DOM/IndexedDB are minimal test doubles; this is not Android/browser acceptance.
import {readFileSync} from 'node:fs';
import {request as httpsRequest} from 'node:https';
import {request as httpRequest} from 'node:http';
import {webcrypto} from 'node:crypto';
import vm from 'node:vm';
const config=JSON.parse(readFileSync(0,'utf8'));
const checks=[];
function check(name,condition){if(!condition)throw new Error(name);checks.push(name);}
function request(url,body,headers={},ca){
  return new Promise((resolve,reject)=>{
    const raw=body===undefined?undefined:JSON.stringify(body), target=new URL(url);
    const req=(target.protocol==='https:'?httpsRequest:httpRequest)(target,{method:raw===undefined?'GET':'POST',ca,rejectUnauthorized:true,headers:{...headers,...(raw?{'Content-Type':'application/json','Content-Length':Buffer.byteLength(raw)}:{})}},res=>{
      let data='';res.on('data',part=>{data+=part;if(data.length>3600000)req.destroy(new Error('oversize'));});
      res.on('end',()=>resolve({ok:res.statusCode===200,status:res.statusCode,text:async()=>data,json:()=>JSON.parse(data)}));
    });req.on('error',reject);req.setTimeout(180000,()=>req.destroy(new Error('timeout')));if(raw)req.write(raw);req.end();
  });
}
const ca=readFileSync(config.ca);
const privateHeaders={'x-adam-desktop':config.nonce};
async function desktop(path,body){return (await request(config.desktop+path,body,privateHeaders)).json();}
await desktop('/desktop/setup',{password:config.password});
const login=await desktop('/auth/login',{password:config.password});
privateHeaders.Authorization='Bearer '+login.token;
await desktop('/auth/elevate',{password:config.password});
const initial=await desktop('/developer/mesh');check('listener defaults off',!initial.listening);
const started=await desktop('/developer/mesh/start',{});check('explicit trusted TLS start',started.listening);
const origin=started.url;
const script=(await request(origin+'/client.js',undefined,{},ca));check('packaged client assets',script.ok);
const clientSource=await script.text();
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,disabled:false,replaceChildren(){},append(){}});return elements.get(id);}
let tamper=false;
const sandbox={crypto:webcrypto,TextEncoder,TextDecoder,Uint8Array,Float32Array,DataView,AbortSignal,
  btoa:value=>Buffer.from(value,'binary').toString('base64'),atob:value=>Buffer.from(value,'base64').toString('binary'),
  document:{hidden:false,getElementById:element,querySelectorAll:()=>[],addEventListener(){},createElement:()=>element('temporary'),createTextNode:text=>text},
  window:{addEventListener(){}},navigator:{onLine:true},isSecureContext:true,
  indexedDB:{open:()=>({})},setInterval:()=>0,clearInterval(){},setTimeout,clearTimeout,
  Option:class {},fetch:async(path,options)=>{
    if(!['/rpc','/pair'].includes(path))throw new Error('unexpected public endpoint');
    const result=await request(origin+path,JSON.parse(options.body),{},ca);
    if(tamper && result.ok){const body=result.json();body.signature=Buffer.alloc(64).toString('base64');return {...result,text:async()=>JSON.stringify(body)};}
    return result;
  },
};
const context=vm.createContext(sandbox);vm.runInContext(clientSource,context);
const pair=await webcrypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},false,['sign','verify']);
check('phone private key nonextractable',pair.privateKey.extractable===false);
const public_key=Buffer.from(await webcrypto.subtle.exportKey('spki',pair.publicKey)).toString('base64');
const ticket=await desktop('/developer/mesh/code',{}),label='Emulated Android WebCrypto';
const signature=Buffer.from(await webcrypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},pair.privateKey,new TextEncoder().encode(`1\n${ticket.code}\n${label}\n${public_key}`))).toString('base64');
const paired=(await request(origin+'/pair',{protocol:1,code:ticket.code,label,public_key,signature},{},ca)).json();
check('key proof enters pending state',paired.status==='PENDING');
sandbox.testIdentity={privateKey:pair.privateKey,public_key,device_id:paired.device_id,node_id:paired.node_id,core:paired.public_key};
sandbox.testCore=await webcrypto.subtle.importKey('spki',Buffer.from(paired.public_key,'base64'),{name:'ECDSA',namedCurve:'P-256'},false,['verify']);
vm.runInContext('identity=testIdentity;coreKey=testCore;',context);
async function rpc(op,payload={}){sandbox.testOp=op;sandbox.testPayload=payload;return vm.runInContext('rpc(testOp,testPayload)',context);}
await rpc('status').then(()=>check('pending must deny',false),e=>check('pending cannot access core',e.message.includes('Pending')));
const approved=await desktop('/developer/mesh/approve',{device_id:paired.device_id,search:true,voice:config.voice});
check('fresh desktop approval required',approved.approved);
const status=await rpc('status');check('shipped client verifies core receipt and node',status.identity==='ADAM'&&status.node_id===paired.node_id);
const session=await rpc('new_session');check('new session primary phone',session.primary===paired.device_id);
const reminder=await desktop('/operations/schedule',{request_id:webcrypto.randomUUID(),text:'Synthetic private appointment',due_at:new Date().toISOString(),route:'ACTIVE',session_id:session.session_id});
check('owner schedules active-device reminder',reminder.state==='SCHEDULED');
let alerts=[];
for(let attempt=0;attempt<15;attempt++) {
  const current=await rpc('status'); alerts=current.notifications;
  if(alerts.length)break;
  await new Promise(resolve=>setTimeout(resolve,200));
}
check('signed mobile update contains only generic content',alerts.length===1 && !JSON.stringify(alerts).includes('private appointment') && !JSON.stringify(alerts).includes(session.session_id));
check('active phone suppresses desktop inbox offer',(await desktop('/operations/inbox')).length===0);
await desktop('/operations/cancel',{identifier:reminder.id});
check('owner cancellation withdraws mobile update',(await rpc('status')).notifications.length===0);
const answer=await rpc('chat',{session_id:session.session_id,text:config.real?'Reply with a short hello from ADAM.':'Hello دنیا from Android'});
check('mobile chat executes on PC',answer.executed_on===paired.node_id&&answer.text.length>0);
check('model answer remains unverified',answer.model_answer==='UNVERIFIED');
const synchronized=await rpc('session',{session_id:session.session_id});check('active session history synchronization',synchronized.history.length===1);
// A late response must not repopulate a cleared/hidden screen.
let release; sandbox.testGate=new Promise(resolve=>{release=resolve;});sandbox.testSnapshot=synchronized;
vm.runInContext(`var savedRpc=rpc, savedDraw=draw, draws=0;
session=testSnapshot.session_id;
rpc=async op=>op==='status'?{sessions:[session],capabilities:{},model_status:'HEALTHY'}:testGate;
draw=()=>{draws++;};`,context);
const stale=vm.runInContext('sync(epoch)',context);await new Promise(resolve=>setTimeout(resolve,0));
vm.runInContext('clearScreen()',context);release(synchronized);await stale;
check('late sync cannot restore cleared private screen',vm.runInContext('session===null && draws===0',context));
vm.runInContext('rpc=savedRpc;draw=savedDraw;',context);
const search=await rpc('search',{query:'mobile-qa'});check('remote search is scoped PC receipt',search.executed_on===paired.node_id&&search.read_only&&JSON.stringify(search.files).includes('mobile-qa.txt'));
await rpc('handoff',{session_id:session.session_id,primary:'desktop'});check('phone to desktop handoff',(await rpc('session',{session_id:session.session_id})).primary==='desktop');
await rpc('chat',{session_id:session.session_id,text:'This should be denied'}).then(()=>check('wrong primary denied',false),e=>check('wrong primary denied',e.message==='MESH.NOT_PRIMARY'));
await desktop('/developer/mesh/handoff',{session_id:session.session_id,primary:paired.device_id});check('desktop to phone handoff',(await rpc('session',{session_id:session.session_id})).primary===paired.device_id);
if(config.voice){
  const speech=await rpc('speak',{session_id:session.session_id,text:'Hello from ADAM on this PC.'});
  check('real PC synthesis returns bounded PCM',speech.sample_rate===24000&&speech.pcm16.length>1000);
  const transcription=await rpc('transcribe',{pcm16:config.audio,sample_rate:16000,partial:false});
  check('real PC STT requires explicit review',transcription.raw_transcript.length>0&&transcription.requires_review===true);
}
tamper=true;await rpc('status').then(()=>check('tampered receipt denied',false),e=>check('tampered core receipt rejected',e.message==='Core signature invalid'));tamper=false;
await desktop('/developer/mesh/revoke',{device_id:paired.device_id});
await rpc('status').then(()=>check('revoked device denied',false),e=>check('revoked key denied',e.message==='MESH.DEVICE_DENIED'));
await desktop('/developer/mesh/stop',{});check('listener explicitly stopped',!(await desktop('/developer/mesh')).listening);
console.log(JSON.stringify({passed:checks.length,checks,kind:'emulated-Android-WebCrypto-TLS',real_model:config.real,real_voice:config.voice,android_human_gate:'NOT_STARTED',answer:answer.text},null,2));
