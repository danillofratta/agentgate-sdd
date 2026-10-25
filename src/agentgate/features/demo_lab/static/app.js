"use strict";
const el = id => document.getElementById(id);
let csrf = "", current = null, auditAfter = 0, auditEvents = [], busy = false;
const money = cents => new Intl.NumberFormat("en-US", {style:"currency",currency:"USD"}).format(cents/100);
const pretty = value => JSON.stringify(value, null, 2);
function notice(message, error=false) { el("notice").textContent=message; el("notice").className=error?"error":""; }
function newKey() { el("key").value="lab-"+crypto.randomUUID(); }
async function request(method,path,body,key,inspect=true) {
  const headers={}; if(method!=="GET") {headers["X-Lab-CSRF"]=csrf;}
  if(body!==undefined) headers["Content-Type"]="application/json";
  if(key) headers["Idempotency-Key"]=key;
  const response=await fetch("/lab"+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),credentials:"same-origin"});
  const data=await response.json();
  if(inspect) {el("request-view").textContent=pretty({method,path:"/lab"+path,...(key?{idempotency_key:key}:{}),...(body!==undefined?{body}:{})}); el("response-view").textContent=pretty(data);el("response-status").textContent=response.status;}
  if(!response.ok) throw new Error(`${response.status} · ${data.error||"REQUEST_FAILED"}`);
  return data;
}
function renderOperation(op) {
  current=op; localStorage.setItem("agentgate-operation",op.id);
  el("empty").hidden=true;el("restore").hidden=true;el("operation-detail").hidden=false;
  el("state").textContent=op.state;
  const tone=op.state==="SUCCEEDED"?"allowed":["DENIED","REJECTED","FAILED","TIMED_OUT","EXPIRED"].includes(op.state)?"denied":"pending";
  el("state").className="badge "+tone;el("decision").textContent=op.decision;
  el("decision").style.color=op.decision==="DENY"?"#a65b4d":op.decision==="ALLOW"?"#22724c":"#9b7227";
  el("reason").textContent=op.reason+" · policy "+op.policy_version;
  el("operation-id").value=op.id;el("detail-tool").textContent=op.tool;
  el("intent").textContent=pretty(op.arguments);
  el("approval-state").textContent=op.approval?op.approval.state+" · expires "+new Date(op.approval.expires_at).toLocaleTimeString():"Not required";
  el("effective").textContent=op.effective_decision?op.effective_decision+" / "+op.effective_reason:"Awaiting execution";
  el("approve").disabled=el("reject").disabled=busy||op.state!=="PENDING_APPROVAL";
  el("execute").disabled=busy||op.state!=="READY";
  el("replay").disabled=busy||!["SUCCEEDED","FAILED","TIMED_OUT"].includes(op.state);
  el("result").textContent=op.result?pretty(op.result):"No committed result yet.";
  renderAudit();
}
async function loadOperation(id,inspect=true) {
  if(!id) return; const op=await request("GET","/operations/"+encodeURIComponent(id),undefined,undefined,inspect);renderOperation(op);return op;
}
async function balances() {const data=await request("GET","/accounts",undefined,undefined,false);for(const account of data){if(account.id==="acct-alice")el("alice").textContent=money(account.balance_cents);if(account.id==="acct-bob")el("bob").textContent=money(account.balance_cents);}}
function renderAudit() {
  const events=el("filter-operation").checked&&current?auditEvents.filter(e=>e.operation_id===current.id):auditEvents;
  el("events").replaceChildren();
  if(!events.length){const p=document.createElement("p");p.className="muted";p.textContent="No matching events in loaded pages. Use Load more to inspect older pages.";el("events").append(p);return;}
  for(const event of [...events].reverse()){
    const row=document.createElement("div");row.className="event";
    const dot=document.createElement("span");dot.className="event-dot";
    const text=document.createElement("div"),title=document.createElement("strong"),detail=document.createElement("small"),time=document.createElement("time");
    title.textContent=event.event_type+" · "+event.decision;
    detail.textContent=`#${event.id} · ${event.reason} · ${event.approver_id||event.principal_id}\n${event.operation_id}${event.attempt?" · attempt "+event.attempt:""}`;
    time.dateTime=event.occurred_at;time.textContent=new Date(event.occurred_at).toLocaleTimeString();text.append(title,detail);row.append(dot,text,time);el("events").append(row);
  }
}
async function audit(inspect=false,reset=false) {
  if(reset){auditAfter=0;auditEvents=[];}
  const data=await request("GET","/audit?after="+auditAfter,undefined,undefined,inspect);
  for(const e of data.events)if(!auditEvents.some(old=>old.id===e.id))auditEvents.push(e);
  auditAfter=data.next_after;renderAudit();
}
async function action(fn) {
  if(busy)return;busy=true;el("submit").disabled=true;if(current)renderOperation(current);
  try{await fn();notice("State verified against the local API. No real money moved.");}
  catch(error){notice(error.message,true);}
  finally{busy=false;el("submit").disabled=false;if(current)renderOperation(current);}
}
el("operation-form").addEventListener("submit",event=>{event.preventDefault();action(async()=>{
  const tool=el("tool").value;
  const amount=Number(el("amount").value);if(tool==="simulate_transfer"&&!Number.isSafeInteger(amount))throw new Error("Enter a safe integer number of cents.");
  const payload={tool,arguments:tool==="get_balance"?{account_id:"acct-alice"}:{source_account_id:"acct-alice",destination_account_id:"acct-bob",amount_cents:amount,currency:"USD"}};
  const op=await request("POST","/operations",payload,el("key").value);await loadOperation(op.id,false);await audit(false,true);await balances();
});});
for(const button of document.querySelectorAll("[data-amount]"))button.addEventListener("click",()=>{el("amount").value=button.dataset.amount;newKey();});
el("tool").addEventListener("change",()=>{const transfer=el("tool").value==="simulate_transfer";el("transfer-fields").hidden=!transfer;el("amount").required=transfer;newKey();});
el("new-key").addEventListener("click",newKey);
for(const decision of ["approve","reject"])el(decision).addEventListener("click",()=>action(async()=>{await request("POST","/operations/"+current.id+"/approval",{decision:decision.toUpperCase()});await loadOperation(current.id,false);await audit(false,true);}));
for(const name of ["execute","replay"])el(name).addEventListener("click",()=>action(async()=>{await request("POST","/operations/"+current.id+"/execute");await loadOperation(current.id,false);await balances();await audit(false,true);}));
el("load").addEventListener("click",()=>action(()=>loadOperation(el("operation-id").value)));
el("restore-load").addEventListener("click",()=>action(()=>loadOperation(el("restore-id").value)));
el("refresh").addEventListener("click",()=>action(async()=>{await balances();if(current)await loadOperation(current.id,false);await audit(false,true);}));
el("more-audit").addEventListener("click",()=>action(()=>audit(true)));
el("filter-operation").addEventListener("change",renderAudit);
async function start(){newKey();try{const response=await fetch("/lab/session",{credentials:"same-origin"});if(!response.ok)throw new Error("Unable to establish local session.");csrf=(await response.json()).csrf;await balances();await audit();const saved=localStorage.getItem("agentgate-operation");if(saved){el("restore-id").value=saved;await loadOperation(saved,false);}notice("Local lab ready. Choose an amount, then submit an intent.");}catch(error){notice(error.message,true);}}
start();

let chatAvailable=false, chatBusy=false, chatPending=false, chatData=null, chatTimeline=[];
function chatControls() {
  el("chat-input").disabled=el("chat-send").disabled=!chatAvailable||chatBusy||chatPending;
  el("chat-retry").hidden=!chatPending;
  el("chat-retry").disabled=chatBusy;
  for(const button of document.querySelectorAll("[data-prompt],#chat-operations button"))button.disabled=chatBusy||!chatAvailable;
}
function chatText(tag,text,className) {const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;return node;}
function renderChat(data) {
  chatData=data;chatPending=data.retry_pending;
  el("chat-messages").replaceChildren();
  for(const message of data.messages){const row=chatText("article","","chat-message "+message.role);row.append(chatText("strong",message.role==="user"?"You":"Assistant · model text, unverified"),chatText("p",message.content));el("chat-messages").append(row);}
  el("chat-messages").scrollTop=el("chat-messages").scrollHeight;
  el("chat-operations").replaceChildren();
  for(const op of [...data.operations].reverse()){
    const card=chatText("article","","chat-card");card.append(chatText("strong",op.decision+" · "+op.state),chatText("small",op.id),chatText("p",op.tool+" · HTTP "+op.http_status),chatText("pre",pretty(op.arguments)));
    if(op.state==="PENDING_APPROVAL")card.append(chatText("p","Pending independent human approval. Review exact arguments using the human controls below.","pending-note"));
    if(op.result)card.append(chatText("pre",pretty(op.result)));
    const actions=chatText("div","","actions");
    const review=chatText("button","Inspect / human review","secondary");review.type="button";review.addEventListener("click",()=>action(async()=>{await loadOperation(op.id);el("operation-detail").scrollIntoView({behavior:"smooth",block:"center"});}));
    const refresh=chatText("button","Continue / refresh","secondary");refresh.type="button";refresh.addEventListener("click",()=>chatTurn({action:"refresh",operation_id:op.id}));
    actions.append(review,refresh);
    if(["READY","SUCCEEDED","FAILED","TIMED_OUT"].includes(op.state)){
      const execute=chatText("button",op.state==="READY"?"Execute via MCP →":"Replay via MCP","primary");execute.type="button";execute.addEventListener("click",()=>chatTurn({action:"execute",operation_id:op.id}));actions.append(execute);
    }
    card.append(actions);
    const technical=chatText("details","");technical.append(chatText("summary","Sanitized AgentGate result"),chatText("pre",pretty(op)));card.append(technical);el("chat-operations").append(card);
  }
  chatTimeline.push(...data.events);chatTimeline=chatTimeline.slice(-60);el("chat-tools").replaceChildren();
  for(const event of chatTimeline){const detail=chatText("details","");detail.append(chatText("summary",event.type+" · "+(event.tool||"MCP discovery / limit")+(event.result?" · HTTP "+event.result.http_status:"")),chatText("pre",pretty(event)));el("chat-tools").append(detail);}
  chatControls();
}
async function chatTurn(payload) {
  if(chatBusy)return;chatBusy=true;chatControls();el("chat-status").textContent="Agent working · waiting for provider / MCP…";
  try {
    const data=await request("POST","/chat/turn",payload);renderChat(data);
    el("chat-status").textContent=data.error?data.error+(data.retry_pending?" · Resume the original call; do not submit it again.":" · You may retry the conversation."):"Turn complete. Review authoritative state before executing.";
    if(payload.action==="message")el("chat-input").value="";
    await balances();await audit(false,true);
  } catch(error){el("chat-status").textContent=error.message+" · Outcome may be uncertain. Use Resume original MCP call after reconnecting.";chatPending=true;}
  finally{chatBusy=false;chatControls();}
}
el("chat-form").addEventListener("submit",event=>{event.preventDefault();chatTurn({message:el("chat-input").value});});
el("chat-retry").addEventListener("click",()=>chatTurn({action:"retry"}));
for(const button of document.querySelectorAll("[data-prompt]"))button.addEventListener("click",()=>{el("chat-input").value=button.dataset.prompt;el("chat-input").focus();});
async function startChat(){try{const data=await request("GET","/chat/status",undefined,undefined,false);chatAvailable=data.available;el("chat-status").textContent=data.message;}catch(error){el("chat-status").textContent="AI chat unavailable. The manual lab remains available.";}chatControls();}
startChat();
