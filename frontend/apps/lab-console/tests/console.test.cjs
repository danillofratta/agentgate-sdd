// Offline behavioral tests. No packages, browser, network or subprocesses required.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const id = '00000000-0000-4000-8000-000000000001';
const now = Date.parse('2026-10-26T12:00:00Z');
const op = (state='READY', decision='ALLOW', approval=null) => ({id,state,decision,approval,tool:'simulate_transfer',reason:decision==='ALLOW'?'PERMITTED':'APPROVAL_REQUIRED',policy_version:'v1',arguments:{source_account_id:'acct-alice',destination_account_id:'acct-bob',amount_cents:10001,currency:'USD'},result:null});
const approval = state => ({state,expires_at:'2099-10-26T12:05:00Z'});

class Element {
  constructor(tag='div') {this.tagName=tag; this.children=[]; this.attrs={}; this.dataset={}; this.listeners={}; this.hidden=false; this.checked=false; this.value=''; this.disabled=false; this.className=''; this._text='';}
  set textContent(v) {this._text=String(v); this.children=[];}
  get textContent() {return this._text+this.children.map(c=>c.textContent).join('');}
  append(...items) {for(const item of items){if(item.parentElement){const a=item.parentElement.children; a.splice(a.indexOf(item),1);} item.parentElement=this;this.children.push(item);}}
  replaceChildren(...items) {this.children=[];this._text='';this.append(...items);}
  setAttribute(k,v) {this.attrs[k]=v;}
  removeAttribute(k) {delete this.attrs[k];}
  addEventListener(k,fn) {this.listeners[k]=fn;}
  focus() {this.focused=true;}
  showModal() {this.open=true;}
  close() {this.open=false;this.listeners.close?.();}
  querySelector() {return this.children[0] || new Element('summary');}
  get firstElementChild() {return this.children[0];}
  remove() {const a=this.parentElement.children;a.splice(a.indexOf(this),1);}
}
function environment(store = new Map()) {
  const elements=new Map([...html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)].map(m=>{
    const n=new Element(m[1]);if(/\bdata-lock\b/.test(m[2]))n.dataset.lock='';return [m[3],n];
  }));
  const nav=['dashboard','assistant','operations'].map(view=>{const n=new Element('a');n.dataset.view=view;return n;});
  const requests=[];
  const context=vm.createContext({Intl,Date,BigInt,Number,Set,Map,JSON,Error,crypto:{randomUUID:()=>id},location:{hash:'#dashboard'},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},setInterval:()=>{},window:{addEventListener:()=>{}}});
  vm.runInContext(source,context);
  context.document={getElementById:id=>{assert.ok(elements.has(id),'Unknown HTML ID '+id);return elements.get(id);},createElement:t=>new Element(t),createTextNode:t=>new Element('#text'),querySelectorAll:s=>s==='[data-view]'?nav:s==='[data-lock]'?[...elements.values()].filter(n=>'lock' in n.dataset):[]};
  context.document.createTextNode=t=>{const n=new Element('#text');n.textContent=t;return n;};
  context.fetch=async(url,options={})=>{requests.push({url,...options});return {ok:true,status:200,json:async()=>({})};};
  const run=(code,values={})=>{Object.assign(context,values);return vm.runInContext(code,context);};
  run('ready=true; csrf="token";');
  return {run,context,e:id=>elements.get(id),requests,store,nav};
}
test('exact USD conversion rejects malformed, unsafe and sub-cent input',()=>{
  const {run}=environment();
  for(const [raw,expected] of [['100.01',10001],['0.29',29],['1',100],['1000.01',100001],[' 1.50 ',150]]) assert.equal(run('usdToCents(raw)',{raw}),expected);
  for(const raw of ['0','-1','1.001','1e3','NaN','1,000.00','.50','90071992547410.01','<script>']) assert.throws(()=>run('usdToCents(raw)',{raw}));
});
test('maps real approval GRANTED state and denies unknown, expired and unapproved execution',()=>{
  const {run}=environment();
  const present=value=>run('presentation(value, now)',{value,now});
  assert.equal(present(op()).execute,true);
  assert.equal(present(op('PENDING_APPROVAL','REQUIRE_APPROVAL',approval('PENDING'))).review,true);
  assert.equal(present(op('READY','REQUIRE_APPROVAL',approval('GRANTED'))).execute,true);
  assert.equal(present(op('READY','REQUIRE_APPROVAL',approval('PENDING'))).execute,false);
  assert.equal(present(op('READY','REQUIRE_APPROVAL',null)).execute,false);
  for(const state of ['DENIED','REJECTED','EXPIRED','FAILED','TIMED_OUT','EXECUTING','invented']) assert.equal(present(op(state)).execute,false);
  const expired=op('READY','REQUIRE_APPROVAL',{state:'GRANTED',expires_at:'2026-10-26T11:59:59Z'});
  assert.equal(present(expired).elapsed,true); assert.equal(present(expired).execute,false); assert.equal(expired.state,'READY');
});
test('same operation DOM moves between chat and details; navigation remains accessible',()=>{
  const {run,e,nav}=environment();
  run('renderOperation(value); showView("assistant");',{value:op()}); const panel=e('operation-workspace');
  assert.equal(panel.parentElement,e('assistant-operation-slot'));
  run('showView("operations");'); assert.equal(panel.parentElement,e('operations-operation-slot'));
  assert.equal(e('assistant-operation-slot').children.length,0);
  assert.equal(nav[2].attrs['aria-current'],'page'); assert.equal(e('page-title').focused,true);
  run('showView("dashboard");'); assert.equal(panel.hidden,true);
});
test('review, execution, receipt, denied and terminal guidance come from authoritative state',()=>{
  const {run,e}=environment();
  run('renderOperation(value)',{value:op('PENDING_APPROVAL','REQUIRE_APPROVAL',approval('PENDING'))});
  assert.equal(e('review').hidden,false); assert.equal(e('execute').hidden,true);
  assert.equal(e('stepper').children[2].attrs['aria-current'],'step');
  run('renderOperation(value)',{value:op('READY','REQUIRE_APPROVAL',approval('GRANTED'))});
  assert.equal(e('execute').textContent,'Execute approved transfer'); assert.equal(e('review').hidden,true);
  const completed={...op('SUCCEEDED'),result:{amount_cents:10001}};
  run('renderOperation(value)',{value:completed}); assert.equal(e('receipt').hidden,false);assert.match(e('result').textContent,/\$100\.01 transferred/);assert.equal(e('replay').hidden,false);
  run('renderOperation(value)',{value:op('DENIED','DENY')});assert.equal(e('execute').hidden,true);assert.equal(e('receipt').hidden,true);
});
test('safe inline formatting renders text and cannot create HTML or executable links',()=>{
  const {run}=environment();
  const p=run('readableMessage(value)',{value:'**Approved** `100.01` <img src=x onerror=alert(1)> [click](javascript:evil)'});
  assert.equal(p.children[1].tagName,'b');assert.equal(p.children[3].tagName,'code');
  assert.ok(!p.children.some(n=>['img','a','script'].includes(n.tagName)));assert.match(p.textContent,/<img/);assert.ok(!p.textContent.includes('**'));
});
test('inspector allowlist drops credentials, rejected raw input, arbitrary errors and model text',()=>{
  const {run}=environment();
  const value={...op(),authorization:'secret',csrf:'secret',message:'secret',error:'secret',unknown:'secret',arguments:{...op().arguments,authorization:'secret'},result:{amount_cents:100,debug:'secret'}};
  const safe=run('JSON.stringify(safeTechnical(value))',{value});assert.ok(!safe.includes('secret'));assert.match(safe,/10001/);
});
test('duplicate submissions share one lock and disabled controls until completion',async()=>{
  const {run,e}=environment();let finish;const pending=new Promise(r=>finish=r);
  let calls=0;
  const first=run('action(fn)',{fn:async()=>{calls++;await pending;}});
  assert.equal(e('submit').disabled,true);assert.equal(e('content').attrs['aria-busy'],'true');
  await run('action(fn)',{fn:async()=>calls++});assert.equal(calls,1);
  finish();await first;assert.equal(e('submit').disabled,false);
});
test('CSRF renewal never automatically repeats rejected mutation or exposes body',async()=>{
  const {run,context,requests,e}=environment();
  context.fetch=async(url,options={})=>{requests.push({url,...options});const renew=url==='/lab/session';return {ok:renew,status:renew?200:403,json:async()=>renew?{csrf:'new-token'}:{error:'LAB_FORBIDDEN',secret:'must not render'}};};
  await assert.rejects(run('request("POST","/operations",{message:"private"})'),/SESSION/);
  assert.equal(requests.length,2);assert.equal(requests[1].url,'/lab/session');assert.equal(run('csrf'),'new-token');
  assert.ok(!e('request-view').textContent.includes('private'));assert.ok(!e('response-view').textContent.includes('must not render'));
});
test('lost execution response retains ID and blocks further mutations until explicit state refresh',async()=>{
  const {run,context,e}=environment();run('renderOperation(value)',{value:op()});context.fetch=async()=>{throw new Error('sensitive socket failure');};
  await run('action(()=>request("POST","/operations/"+current.id+"/execute"))');
  assert.equal(e('execute').disabled,true);assert.equal(e('reconcile').hidden,false);assert.match(e('notice').textContent,/could not be confirmed/);assert.ok(!e('notice').textContent.includes('sensitive'));
});
test('independent approval requires deliberate checkbox and refreshes exact original ID',async()=>{
  const {run,context,e,requests}=environment();const value=op('PENDING_APPROVAL','REQUIRE_APPROVAL',approval('PENDING'));
  context.fetch=async(url,options={})=>{requests.push({url,...options});return {ok:true,status:200,json:async()=>value};};
  run('renderOperation(value)',{value});await run('openReview()');assert.equal(e('review-dialog').open,true);assert.equal(e('approval-confirm').checked,false);
  await assert.rejects(run('decide("APPROVE")'),/CONFLICT/);assert.ok(requests.every(r=>!r.method||r.method==='GET'));
  assert.match(e('review-transfer').textContent,/\$100\.01/);assert.equal(e('review-reference').textContent,id);
});
test('invalid ID never sends a request',async()=>{const {run,requests}=environment();await assert.rejects(run('loadOperation("bad-id")'),/ID/);assert.equal(requests.length,0);});
test('manual uncertainty preserves stable key and exact payload for explicit reconciliation',async()=>{
  const {run,e,context,requests,store}=environment();e('tool').value='simulate_transfer';e('amount').value='100.01';run('newDraft()');
  context.fetch=async(url,options)=>{requests.push({url,...options});throw Error('offline');};
  await assert.rejects(run('submitDraft()'),/UNCERTAIN/);const saved=JSON.parse(store.get('agentgate-recovery'));assert.equal(saved.payload.arguments.amount_cents,10001);
  assert.throws(()=>run('newDraft()'),/BLOCKED/);
  e('amount').value='999.99';await assert.rejects(run('submitDraft(true)'),/UNCERTAIN/);
  assert.equal(requests[0].body,requests[1].body);assert.equal(requests[0].headers['Idempotency-Key'],requests[1].headers['Idempotency-Key']);
});
test('chat failure keeps recovery available; provider unavailable keeps manual navigation',async()=>{
  const {run,context,e}=environment();context.fetch=async()=>{throw Error('offline');};
  await run('action(()=>chatTurn({message:"Balance?"}))');assert.equal(e('chat-retry').hidden,false);assert.equal(e('chat-send').disabled,true);
  await run('chatStatus()');assert.match(e('chat-status').textContent,/previous chat call is unconfirmed/);
});
test('balance and transfer chat results use one API-inspected operation, never model success',async()=>{
  const {run,context,e}=environment();const value=op('DENIED','DENY');
  context.fetch=async(url)=>({ok:true,status:200,json:async()=>url==='/lab/chat/turn'?{messages:[{role:'assistant',content:'**Success!**'}],operations:[value],events:[],retry_pending:false}:url.includes('/operations/')?value:url==='/lab/accounts'?[]:{events:[],next_after:0}});
  await run('chatTurn({message:"Transfer"})');assert.equal(e('state').textContent,'Denied by policy');assert.equal(e('execute').hidden,true);assert.equal(e('receipt').hidden,true);
  assert.match(e('chat-messages').textContent,/unverified model text/);
});
test('reload restores only a persisted ID and fetches its authoritative state',async()=>{
  const {run,context,store,e,requests}=environment();store.set('agentgate-operation',id);
  const value={...op('SUCCEEDED'),result:{amount_cents:10001}};
  context.fetch=async(url,options={})=>{requests.push({url,...options});return {ok:true,status:200,json:async()=>url==='/lab/session'?{csrf:'new'}:url.includes('/operations/')?value:url==='/lab/accounts'?[]:url==='/lab/chat/status'?{available:false}:{events:[],next_after:0}};};
  await run('start()');assert.equal(e('state').textContent,'Completed');assert.equal(e('operation-id').textContent,id);
  assert.ok(requests.some(r=>r.url==='/lab/operations/'+id));assert.ok(requests.every(r=>!r.method||r.method==='GET'));
});
test('reload keeps an uncertain draft immutable and does not automatically reconcile it',async()=>{
  const {run,context,store,e,requests}=environment();store.set('agentgate-pending-draft',JSON.stringify({key:'lab-'+id,payload:{tool:'simulate_transfer',arguments:op().arguments}}));
  context.fetch=async(url,options={})=>{requests.push({url,...options});return {ok:true,status:200,json:async()=>url==='/lab/session'?{csrf:'new'}:url==='/lab/accounts'?[]:url==='/lab/chat/status'?{available:false}:{events:[],next_after:0}};};
  await run('start()');assert.equal(e('amount').value,'100.01');assert.equal(e('draft-fields').disabled,true);assert.equal(e('recover-draft').hidden,false);assert.ok(requests.every(r=>!r.method||r.method==='GET'));
});
test('chat-associated execution sends an explicit grant for exactly the active ID via MCP',async()=>{
  const {run,context,requests,e}=environment();const value={...op('SUCCEEDED'),result:{amount_cents:10001}};
  context.fetch=async(url,options={})=>{requests.push({url,...options});return {ok:true,status:200,json:async()=>url==='/lab/chat/turn'?{messages:[],operations:[value],events:[],retry_pending:false}:url.includes('/operations/')?(requests.some(r=>r.url==='/lab/chat/turn')?value:op()):url==='/lab/accounts'?[]:{events:[],next_after:0}};};
  run('renderOperation(value);chatAvailable=true;chatIds.add(current.id)',{value:op()});await run('execute()');
  const posts=requests.filter(r=>r.method==='POST');assert.equal(posts.length,1);assert.equal(posts[0].url,'/lab/chat/turn');assert.deepEqual(JSON.parse(posts[0].body),{action:'execute',operation_id:id});assert.equal(e('state').textContent,'Completed');
});
test('confirmed human approval never dispatches execution and returns focus after close',async()=>{
  const {run,context,e,requests}=environment();let granted=false;
  context.fetch=async(url,options={})=>{requests.push({url,...options});if(url.endsWith('/approval')) granted=true;return {ok:true,status:200,json:async()=>url.includes('/operations/')?op(granted?'READY':'PENDING_APPROVAL','REQUIRE_APPROVAL',approval(granted?'GRANTED':'PENDING')):{events:[],next_after:0}};};
  run('renderOperation(value)',{value:op('PENDING_APPROVAL','REQUIRE_APPROVAL',approval('PENDING'))});await run('openReview()');e('approval-confirm').checked=true;await run('decide("APPROVE")');
  assert.equal(requests.filter(r=>r.method==='POST').length,1);assert.equal(requests.find(r=>r.method==='POST').url,'/lab/operations/'+id+'/approval');assert.equal(e('state').textContent,'Approved — awaiting execution');assert.equal(e('review-dialog').open,false);
});
test('missing provider does not leave manual operations locked as financially uncertain',async()=>{
  const {run,context,e}=environment();context.fetch=async()=>({ok:false,status:503,json:async()=>({error:'PROVIDER_NOT_CONFIGURED'})});
  await run('action(()=>chatTurn({message:"Hello"}))');assert.equal(run('recovery'),null);assert.equal(e('submit').disabled,false);
});
test('unconfirmed chat followed by reload requires explicit inspection, with no replay',async()=>{
  const {run,context,store,e,requests}=environment();store.set('agentgate-chat-unconfirmed','1');store.set('agentgate-operation',id);
  context.fetch=async(url,options={})=>{requests.push({url,...options});return {ok:true,status:200,json:async()=>url==='/lab/session'?{csrf:'new'}:url.includes('/operations/')?op():url==='/lab/accounts'?[]:url==='/lab/chat/status'?{available:true}:{events:[],next_after:0}};};
  await run('start()');assert.equal(e('submit').disabled,true);assert.equal(e('chat-retry').hidden,true);assert.match(e('notice').textContent,/previous chat call is unconfirmed/);
  assert.ok(requests.every(r=>!r.method||r.method==='GET'));assert.equal(store.get('agentgate-chat-unconfirmed'),'1');
  await run('loadOperation(value); controls();',{value:id});assert.equal(e('submit').disabled,true);assert.equal(run('recovery.kind'),'chat');
});

// Review regression fixtures: GETs remain deterministic, mutation outcomes are
// explicitly supplied by each scenario. No frontend-generated financial effects.
const ok = data => ({ok:true,status:200,json:async()=>data});
const rejected = (status,error='UNAVAILABLE') => ({ok:false,status,json:async()=>({error})});
const differentId = '00000000-0000-4000-8000-000000000002';
function readService(url, value=op()) {
  if(url==='/lab/session')return ok({csrf:'renewed'});
  if(url.includes('/operations/'))return ok({...value,id:url.split('/').at(-1)});
  if(url==='/lab/accounts')return ok([]);
  if(url==='/lab/chat/status')return ok({available:true});
  return ok({events:[],next_after:0});
}
async function lostDraft(env) {
  env.e('tool').value='simulate_transfer';env.e('amount').value='100.01';env.run('newDraft()');
  env.context.fetch=async()=>{throw Error('response lost');};
  await assert.rejects(env.run('submitDraft()'),/UNCERTAIN/);
  return JSON.parse(env.store.get('agentgate-recovery'));
}
test('lost proposal plus CSRF renewal and reload retains exact original identity across repeated failures',async()=>{
  const env=environment(), original=await lostDraft(env);const posts=[];
  env.context.fetch=async(url,options={})=>{
    if(options.method==='POST'){posts.push(options);return rejected(403,'LAB_FORBIDDEN');}
    return readService(url);
  };
  for(let n=0;n<2;n++)await assert.rejects(env.run('submitDraft(true)'),/SESSION/);
  assert.equal(posts.length,2);assert.deepEqual(JSON.parse(env.store.get('agentgate-recovery')),original);
  const restored=environment(env.store);restored.context.fetch=async(url,options={})=>{assert.notEqual(options.method,'POST');return readService(url);};
  await restored.run('start()');assert.equal(restored.e('amount').value,'100.01');assert.equal(restored.e('submit').disabled,true);
  assert.deepEqual(JSON.parse(restored.store.get('agentgate-recovery')),original);
  assert.equal(restored.e('recovery-panel').hidden,false);assert.equal(restored.e('recover-original').disabled,false);
  restored.context.fetch=async(url,options={})=>{
    if(options.method==='POST'){posts.push(options);return ok({id});}return readService(url);
  };
  await restored.run('submitDraft(true)');assert.equal(restored.run('recovery'),null);
  for(const p of posts){assert.equal(p.headers['Idempotency-Key'],original.key);assert.deepEqual(JSON.parse(p.body),original.payload);}
  assert.equal(restored.e('state').textContent,'Authorized — not executed');
});
test('failed CSRF renewal and repeated network/HTTP reconciliation failures never discard draft',async()=>{
  const env=environment(), original=await lostDraft(env);
  for(const mode of ['renewal','network','http']){
    env.context.fetch=async(url)=>{
      if(mode==='network'||(mode==='renewal'&&url==='/lab/session'))throw Error('offline');
      return mode==='renewal'?rejected(403,'LAB_FORBIDDEN'):rejected(503);
    };
    await assert.rejects(env.run('submitDraft(true)'));
    assert.deepEqual(JSON.parse(env.store.get('agentgate-recovery')),original);
    assert.throws(()=>env.run('newDraft()'),/BLOCKED/);
  }
});
for(const actionName of ['execute','approval'])test(`lost ${actionName} response survives reload; only original ID can reconcile`,async()=>{
  const env=environment();env.context.fetch=async()=>{throw Error('offline');};
  await assert.rejects(env.run('request("POST",path,body)',{path:'/operations/'+id+'/'+actionName,body:actionName==='approval'?{decision:'APPROVE'}:undefined}),/UNCERTAIN/);
  const record=JSON.parse(env.store.get('agentgate-recovery'));assert.equal(record.operationId,id);
  const restored=environment(env.store);const calls=[];
  restored.context.fetch=async(url,options={})=>{calls.push({url,...options});return readService(url);};
  await restored.run('start()');assert.equal(restored.run('recovery.operationId'),id);
  await restored.run('loadOperation(value)',{value:differentId});assert.notEqual(restored.run('recovery'),null);
  await restored.run('reconcileOriginal()');assert.equal(restored.run('recovery'),null);assert.equal(restored.run('current.id'),id);
  assert.ok(calls.every(c=>!c.method||c.method==='GET'));
});
test('uncertainty blocks every command and HTTP mutation even when invoked directly',async()=>{
  const env=environment();env.run('renderOperation(value);beginRecovery({kind:"operation",operationId:current.id});chatAvailable=true;controls()',{value:op()});
  const owner=env.run('recovery.token');let calls=0;env.context.fetch=async()=>{calls++;return readService('/lab/accounts');};
  for(const expression of ['chatTurn({message:"Transfer"})','submitDraft()','execute()','decide("APPROVE")','openReview()','request("POST","/operations",{})'])await assert.rejects(env.run(expression),/BLOCKED/);
  assert.throws(()=>env.run('newDraft()'),/BLOCKED/);
  await assert.rejects(env.run('request("POST","/operations",{},"new-key",true,value)',{value:owner}),/BLOCKED/);
  assert.equal(calls,0);
  for(const name of ['submit','chat-send','execute','approve','reject','new-draft','new-operation'])assert.equal(env.e(name).disabled,true,name);
});
test('unrelated reads and delayed callbacks cannot clear another recovery identity',async()=>{
  const env=environment();env.run('beginRecovery({kind:"operation",operationId:value})',{value:id});const original=env.run('recovery.token');
  let finish;env.context.fetch=()=>new Promise(r=>finish=r);
  const pending=env.run('loadOperation(value,false,owner)',{value:id,owner:original});
  env.run('releaseRecovery(owner);beginRecovery({kind:"operation",operationId:value})',{owner:original,value:differentId});
  const newer=env.run('recovery.token');finish(ok(op()));await assert.rejects(pending,/STALE/);
  assert.equal(env.run('recovery.token'),newer);assert.equal(env.run('current'),null);
  env.context.fetch=async(url)=>readService(url);
  await env.run('loadOperation(value)',{value:id});assert.equal(env.run('recovery.token'),newer);
  assert.equal(env.run('resolveRecovery(value,owner)',{value:op(),owner:original}),false);
});
test('HTTP in-flight lease blocks concurrent mutations including original recovery resends',async()=>{
  const env=environment();let finish;let calls=0;
  env.context.fetch=()=>{calls++;return new Promise(r=>finish=r);};
  const pending=env.run('request("POST","/operations/"+value+"/execute")',{value:id});
  const owner=env.run('recovery.token');
  await assert.rejects(env.run('request("POST","/chat/turn",{message:"New request"})'),/BLOCKED/);
  await assert.rejects(env.run('request("POST","/operations/"+value+"/execute",undefined,undefined,true,owner)',{value:id,owner}),/BLOCKED/);
  assert.equal(calls,1);finish(ok(op()));await pending;
});
for(const failure of ['timeout','http'])test(`audit ${failure} after confirmed submission preserves continuation and independent retry`,async()=>{
  const env=environment();let failing=true;const posts=[];
  env.e('tool').value='simulate_transfer';env.e('amount').value='100.01';env.run('newDraft()');
  env.context.fetch=async(url,options={})=>{
    if(options.method==='POST'){posts.push(url);return ok({id});}
    if(url.includes('/audit')&&failing){if(failure==='timeout')throw Error('timeout');return rejected(503);}
    return readService(url);
  };
  await env.run('action(()=>submitDraft())');assert.equal(env.run('recovery'),null);assert.equal(env.e('execute').disabled,false);assert.equal(env.e('new-operation').disabled,false);
  assert.equal(env.e('manual-entry').hidden,true);assert.match(env.e('audit-status').textContent,/confirmed operation is unchanged/);
  assert.equal(env.e('recovery-panel').hidden,true);
  failing=false;await env.run('auditView(true)');assert.match(env.e('audit-status').textContent,/refreshed/);assert.equal(posts.length,1);
});
for(const failure of ['malformed','missing','unavailable'])test(`saved ID restoration ${failure} remains visible after startup and reload`,async()=>{
  const store=new Map([['agentgate-operation',failure==='malformed'?'not-an-id':id]]);
  for(let reload=0;reload<2;reload++){
    const env=environment(store);env.context.fetch=async(url)=>url.includes('/operations/')?rejected(failure==='missing'?404:503):readService(url);
    await env.run('start()');assert.match(env.e('notice').textContent,/Unable to restore/);assert.ok(!env.e('notice').textContent.includes('Local lab ready'));
    assert.equal(env.e('operations-view').hidden,false);assert.equal(env.e('restore-id').value,store.get('agentgate-operation'));
    assert.match(env.e('notice').textContent,failure==='malformed'?/UUID/:failure==='missing'?/not found/:/unavailable/);
  }
});
for(const failure of ['network','timeout','provider-http'])test(`chat ${failure} finalizes processing and preserves recoverable identity`,async()=>{
  const env=environment();let posts=0;
  env.context.fetch=async()=>{posts++;if(failure==='provider-http')return rejected(502);throw Error(failure);};
  await env.run('action(()=>chatTurn({message:"Transfer"}))');
  assert.ok(!env.e('chat-status').textContent.includes('Processing'));assert.match(env.e('chat-status').textContent,/unconfirmed/);assert.equal(env.run('busy'),false);
  assert.equal(env.run('recovery.kind'),'chat');assert.equal(env.e('chat-send').disabled,true);assert.equal(posts,1);
  assert.equal(JSON.parse(env.store.get('agentgate-recovery')).token,env.run('recovery.token'));
});
test('confirmed provider failure without unfinished calls ends processing and allows safe manual mode',async()=>{
  const env=environment();env.context.fetch=async(url)=>url==='/lab/chat/turn'?ok({messages:[],events:[],operations:[],retry_pending:false,error:'AGENT_UNAVAILABLE'}):readService(url);
  await env.run('action(()=>chatTurn({message:"Hello"}))');assert.equal(env.run('recovery'),null);assert.equal(env.e('submit').disabled,false);assert.match(env.e('chat-status').textContent,/provider is unavailable/);
});
test('recovery storage failure refuses financial I/O and preserves the in-memory original',async()=>{
  const env=environment();let calls=0;env.context.localStorage.setItem=()=>{throw Error('storage disabled');};env.context.fetch=async()=>{calls++;return ok({});};
  await assert.rejects(env.run('request("POST","/operations/"+value+"/execute")',{value:id}),/STORAGE/);assert.equal(calls,0);assert.equal(env.run('recovery.operationId'),id);
});
test('known original execution remains recoverable after CSRF rejection and failed read reconciliation',async()=>{
  const env=environment();env.context.fetch=async()=>{throw Error('lost execute response');};
  await assert.rejects(env.run('request("POST","/operations/"+value+"/execute")',{value:id}),/UNCERTAIN/);
  const original=JSON.parse(env.store.get('agentgate-recovery'));let renewed=0;let posts=0;
  env.context.fetch=async(url,options={})=>{
    if(options.method==='POST')posts++;
    if(url==='/lab/session'){renewed++;return ok({csrf:'renewed'});}
    return rejected(403,'LAB_FORBIDDEN');
  };
  await assert.rejects(env.run('reconcileOriginal()'),/SESSION/);assert.equal(renewed,1);assert.equal(posts,0);assert.deepEqual(JSON.parse(env.store.get('agentgate-recovery')),original);
  env.context.fetch=async()=>rejected(503);await assert.rejects(env.run('reconcileOriginal()'),/UNAVAILABLE/);assert.deepEqual(JSON.parse(env.store.get('agentgate-recovery')),original);
  env.context.fetch=async(url)=>readService(url,{...op('SUCCEEDED'),result:{amount_cents:10001}});
  await env.run('reconcileOriginal()');assert.equal(env.run('recovery'),null);assert.equal(env.e('state').textContent,'Completed');
});
test('first chat rejected before dispatch permits deliberate retry after CSRF renewal',async()=>{
  const env=environment();let posts=0;
  env.context.fetch=async(url,options={})=>{if(options.method==='POST'){posts++;return rejected(403,'LAB_FORBIDDEN');}return readService(url);};
  await env.run('action(()=>chatTurn({message:"Transfer"}))');assert.equal(posts,1);assert.equal(env.run('recovery'),null);assert.ok(!env.e('chat-status').textContent.includes('Processing'));
});
test('CSRF renewal of an older unconfirmed chat call never discards its identity',async()=>{
  const env=environment();env.context.fetch=async()=>{throw Error('offline');};
  await assert.rejects(env.run('chatTurn({message:"Transfer"})'),/UNCERTAIN/);const owner=env.run('recovery.token');
  env.context.fetch=async(url)=>url==='/lab/session'?ok({csrf:'new'}):rejected(403,'LAB_FORBIDDEN');
  await assert.rejects(env.run('reconcileOriginal()'),/SESSION/);
  assert.equal(env.run('recovery.token'),owner);assert.equal(env.run('recovery.sessionLost'),true);
  await assert.rejects(env.run('chatTurn({message:"Another transfer"})'),/BLOCKED/);
});
test('confirmed original inspection remains confirmed if the following audit refresh fails',async()=>{
  const env=environment();env.run('beginRecovery({kind:"operation",operationId:value})',{value:id});
  env.context.fetch=async(url)=>{if(url.includes('/audit'))throw Error('timeout');return readService(url);};
  await env.run('action(refresh)');assert.equal(env.run('recovery'),null);assert.equal(env.run('current.id'),id);assert.equal(env.e('execute').disabled,false);assert.match(env.e('audit-status').textContent,/unavailable/);
});
test('explicit original chat recovery resumes the existing server call and inspects its returned ID',async()=>{
  const env=environment();env.context.fetch=async()=>{throw Error('lost chat response');};
  await assert.rejects(env.run('chatTurn({message:"Transfer $100.01"})'),/UNCERTAIN/);const original=env.run('recovery.token');const sent=[];
  env.context.fetch=async(url,options={})=>{
    sent.push({url,...options});
    if(url==='/lab/chat/turn')return ok({messages:[],operations:[op()],events:[{type:'tool',result:op()}],retry_pending:false});
    return readService(url);
  };
  await env.run('reconcileOriginal()');assert.equal(env.run('recovery'),null);assert.equal(env.run('current.id'),id);
  const posts=sent.filter(c=>c.method==='POST');assert.equal(posts.length,1);assert.deepEqual(JSON.parse(posts[0].body),{action:'retry'});assert.ok(sent.some(c=>c.url==='/lab/operations/'+id));assert.ok(original);
});
test('delayed successful chat response cannot clear or display over a newer recovery owner',async()=>{
  const env=environment();let finish;env.context.fetch=()=>new Promise(r=>finish=r);
  const pending=env.run('chatTurn({message:"Transfer"})');
  // Simulate a newer persisted owner becoming visible before an old callback.
  env.run('recovery={kind:"operation",operationId:value,token:"new-owner"};persistRecovery()',{value:differentId});
  finish(ok({messages:[],operations:[op()],events:[],retry_pending:false}));await assert.rejects(pending,/STALE/);
  assert.equal(env.run('recovery.token'),'new-owner');assert.equal(env.run('current'),null);assert.ok(!env.e('chat-status').textContent.includes('Processing'));
});
