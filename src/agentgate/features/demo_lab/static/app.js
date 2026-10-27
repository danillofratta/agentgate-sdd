"use strict";

const el = id => document.getElementById(id);
const money = cents => new Intl.NumberFormat("en-US", {style:"currency", currency:"USD"}).format(cents / 100);
const pretty = value => JSON.stringify(value, null, 2);
const validId = id => typeof id === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
const accountName = id => ({"acct-alice":"Alice", "acct-bob":"Bob"}[id] || "Account");
const policyNames = {ALLOW:"Allowed", REQUIRE_APPROVAL:"Human approval required", DENY:"Denied"};
const reasons = {PERMITTED:"Within the policy limit and account permissions.", APPROVAL_REQUIRED:"Transfers above $100 need independent human approval.", LIMIT_EXCEEDED:"This amount exceeds the $1,000 transfer limit.", INSUFFICIENT_FUNDS:"The source account has insufficient funds.", SOURCE_NOT_ALLOWED:"The agent cannot use this source account.", TOOL_NOT_ALLOWED:"The agent cannot request this operation.", UNKNOWN_ACCOUNT:"An account is unavailable.", POLICY_UNCERTAIN:"Authorization could not be established safely."};
let csrf = "", current = null, busy = false, ready = false, view = "dashboard";
let auditAfter = 0, auditEvents = [], recent = new Map(), recentIds = [];
let chatAvailable = false, chatIds = new Set();
let draft = null, draftKey = "", reviewId = null;
let recovery = null, mutationInFlight = false, recoverySequence = 0;

function storageGet(key) {try {return localStorage.getItem(key);} catch {return null;}}
function storageSet(key, value) {try {localStorage.setItem(key, value); return true;} catch {return false;}}
function storageRemove(key) {try {localStorage.removeItem(key);} catch { /* Storage is optional. */ }}
const sameIntent = (a, b) => pretty(Object.entries(a || {}).sort()) === pretty(Object.entries(b || {}).sort());
function assertMutationAllowed(owner = null) {
  if (mutationInFlight || (recovery && owner !== recovery.token)) throw new Error("BLOCKED");
  if (owner && owner !== recovery?.token) throw new Error("STALE");
}
function persistRecovery() {
  if (!storageSet("agentgate-recovery", pretty(recovery))) throw new Error("STORAGE");
}
function beginRecovery(intent) {
  assertMutationAllowed();
  recovery = {...intent, token:crypto.randomUUID() + ":" + (++recoverySequence)};
  persistRecovery(); return recovery.token;
}
function releaseRecovery(owner) {
  if (recovery?.token !== owner) throw new Error("STALE");
  // Persist the resolution before removing legacy markers. Failure stays closed.
  if (!storageSet("agentgate-recovery", "null")) throw new Error("STORAGE");
  recovery = null; storageRemove("agentgate-pending-draft"); storageRemove("agentgate-chat-unconfirmed");
}
function bindRecoveryId(owner, id) {
  if (recovery?.token !== owner || !validId(id)) throw new Error("STALE");
  if (recovery.operationId && recovery.operationId !== id) throw new Error("RECOVERY");
  recovery.operationId = id; persistRecovery();
}
function resolveRecovery(op, owner) {
  if (!owner || recovery?.token !== owner || recovery.operationId !== op.id) return false;
  if (!["READY","PENDING_APPROVAL","SUCCEEDED","DENIED","REJECTED","EXPIRED","FAILED","TIMED_OUT"].includes(op.state)) return false;
  if (recovery.kind === "draft" && (op.tool !== recovery.payload.tool || !sameIntent(op.arguments, recovery.payload.arguments))) throw new Error("RECOVERY");
  releaseRecovery(owner); return true;
}
function recoveryGuidance() {
  if (!recovery) return "";
  if (recovery.operationId) return "The outcome needs verification. Check the original operation " + recovery.operationId + ". New actions are blocked until its persisted state is reconciled.";
  if (recovery.kind === "draft") return "The original request is unconfirmed. Its exact amount, accounts and idempotency key are retained. Reconcile the original request; do not create another.";
  if (recovery.sessionLost) return "The previous chat call is unconfirmed and its session memory is unavailable. No original operation reference was recovered. New actions remain blocked; an unrelated operation cannot prove this call's outcome. Recover the original server context/reference before continuing.";
  return "The previous chat call is unconfirmed. Resume the original call with its retained server-side identity. No new request will be created automatically.";
}
function renderRecovery() {
  el("recovery-panel").hidden = !recovery;
  el("recovery-message").textContent = recoveryGuidance();
  el("recover-original").textContent = recovery?.operationId ? "Check original operation" : recovery?.kind === "draft" ? "Reconcile original request" : "Resume original call";
  el("recover-original").disabled = busy || !ready || (recovery?.kind === "chat" && recovery.sessionLost && !recovery.operationId);
}
function node(tag, text = "", className = "") {const n = document.createElement(tag); n.textContent = text; n.className = className; return n;}
function notice(text, error = false) {el("notice").textContent = text; el("notice").className = error ? "error" : "";}
function usdToCents(raw) {
  if (!/^(0|[1-9]\d*)(\.\d{1,2})?$/.test(raw.trim())) throw new Error("AMOUNT");
  const [whole, fraction = ""] = raw.trim().split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (cents < 1n || cents > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("AMOUNT");
  return Number(cents);
}
function presentation(op, now = Date.now()) {
  const requires = op.decision === "REQUIRE_APPROVAL";
  const expiry = op.approval && Date.parse(op.approval.expires_at);
  const elapsed = requires && ["READY", "PENDING_APPROVAL"].includes(op.state) && (!Number.isFinite(expiry) || expiry <= now);
  const states = {
    READY:[requires ? "Approved — awaiting execution" : "Authorized — not executed", "The request is authorized. Nothing has moved. Execute when you are ready.", 3, "allowed"],
    PENDING_APPROVAL:["Awaiting human approval", "Review the exact amount and accounts as the independent human reviewer. Approval does not execute the transfer.", 2, "pending"],
    SUCCEEDED:["Completed", "The operation completed. The stored receipt below is authoritative. Replay returns the same result without another debit.", 4, "allowed"],
    DENIED:["Denied by policy", "This request cannot execute. Review the policy explanation or start a new operation.", 1, "denied"],
    REJECTED:["Rejected by reviewer", "The human reviewer rejected this request. It cannot execute. Start a new operation if needed.", 2, "denied"],
    EXPIRED:["Approval expired", "The approval window ended. This approval cannot be reused. Start a new operation.", 2, "denied"],
    FAILED:["Execution failed", "No successful result was recorded. Inspect the audit before deciding to create a new operation. Viewing the stored outcome does not retry execution.", 4, "denied"],
    TIMED_OUT:["Execution timed out", "The execution deadline was reached. Inspect the stored outcome and audit. No automatic retry will occur.", 4, "denied"],
    EXECUTING:["Execution in progress", "Check persisted state before taking another action. Do not resubmit the transfer.", 3, "pending"]
  };
  const [title, guidance, stage, tone] = states[op.state] || ["State unavailable", "Refresh persisted state before proceeding.", 1, "pending"];
  return {title:elapsed ? "Approval deadline passed" : title, guidance:elapsed ? "The local clock indicates that approval has expired. Refresh for the persisted state or start a new operation; this approval cannot be used." : guidance,
    stage:elapsed ? 2 : stage, tone:elapsed ? "denied" : tone, elapsed,
    execute:op.state === "READY" && !elapsed && (op.decision === "ALLOW" || (requires && op.approval?.state === "GRANTED")),
    review:op.state === "PENDING_APPROVAL" && op.approval?.state === "PENDING" && !elapsed,
    replay:["SUCCEEDED", "FAILED", "TIMED_OUT"].includes(op.state)};
}
// Only project fields that belong to known API contracts. Never dump raw responses or errors.
function safeTechnical(value, depth = 0) {
  if (depth > 8 || value == null) return value == null ? null : undefined;
  if (Array.isArray(value)) return value.slice(-100).map(v => safeTechnical(v, depth + 1));
  if (typeof value !== "object") return undefined;
  const out = {};
  const enums = {state:["READY","PENDING_APPROVAL","DENIED","REJECTED","EXPIRED","SUCCEEDED","FAILED","TIMED_OUT","EXECUTING","PENDING","APPROVED","CONSUMED"], decision:["ALLOW","DENY","REQUIRE_APPROVAL","APPROVE","REJECT"], effective_decision:["ALLOW","DENY","REQUIRE_APPROVAL"], reason:Object.keys(reasons).concat("HUMAN_APPROVED"), effective_reason:Object.keys(reasons).concat("HUMAN_APPROVED"), tool:["simulate_transfer","get_balance","request_operation","get_operation","execute_operation"], tool_name:["simulate_transfer","get_balance"], type:["discovery","tool","blocked","limit"], action:["message","execute","refresh","retry"], currency:["USD"], policy_version:["v1"]};
  const nested = new Set(["arguments","result","approval","events","operations","payload","parameters"]);
  for (const [key, v] of Object.entries(value)) {
    if (nested.has(key) && v && typeof v === "object") out[key] = safeTechnical(v, depth + 1);
    else if (key === "state" && v === "GRANTED") out[key] = v;
    else if (enums[key]?.includes(v)) out[key] = v;
    else if (["id","operation_id","correlation_id"].includes(key) && validId(v)) out[key] = v;
    else if (key === "id" && Number.isSafeInteger(v) && v >= 0) out[key] = v;
    else if (key === "event_type" && ["OPERATION_REQUESTED","APPROVAL_DECIDED","APPROVAL_EXPIRED","OPERATION_ATTEMPTED","OPERATION_DISPATCHED","OPERATION_EXECUTED","OPERATION_FAILED"].includes(v)) out[key] = v;
    else if (["principal_id","approver_id"].includes(key) && typeof v === "string" && /^principal-[a-z0-9_-]{1,64}$/.test(v)) out[key] = v;
    else if (["account_id","source_account_id","destination_account_id"].includes(key) && /^acct-[a-z0-9]{1,32}$/.test(v)) out[key] = v;
    else if (["amount_cents","balance_cents","source_balance_cents","destination_balance_cents","attempt","next_after","http_status"].includes(key) && Number.isSafeInteger(v) && v >= 0) out[key] = v;
    else if (["created_at","expires_at","occurred_at"].includes(key) && typeof v === "string" && /^\d{4}-\d\d-\d\dT[\d:.+Z-]+$/.test(v)) out[key] = v;
    else if (key === "simulation" && v === true) out[key] = true;
  }
  return out;
}
async function session() {
  const r = await fetch("/lab/session", {credentials:"same-origin"});
  if (!r.ok) throw new Error("CONNECTION");
  csrf = (await r.json()).csrf;
}
async function request(method, path, body, key, inspect = true, owner = null) {
  const mutating = method !== "GET", startedNew = mutating && !recovery;
  if (mutating) {
    assertMutationAllowed(owner);
    if (!startedNew) {
      const originalDraft = recovery.kind === "draft" && path === "/operations" && key === recovery.key && body?.tool === recovery.payload.tool && sameIntent(body.arguments, recovery.payload.arguments);
      const originalChat = recovery.kind === "chat" && !recovery.sessionLost && path === "/chat/turn" && body?.action === "retry" && !body.message && !body.operation_id;
      if (!originalDraft && !originalChat) throw new Error("BLOCKED");
      persistRecovery();
    }
    if (startedNew) {
      const match = path.match(/^\/operations\/([^/]+)\/(execute|approval)$/);
      const intent = path === "/operations" ? {kind:"draft", payload:body, key} : match ? {kind:"operation", operationId:match[1], action:match[2]} : {kind:"chat", operationId:body?.operation_id || null, knownIds:[...chatIds], sessionLost:false};
      owner = beginRecovery(intent);
    }
    mutationInFlight = true;
  }
  const headers = {};
  if (method !== "GET") headers["X-Lab-CSRF"] = csrf;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = key;
  try {
  let response, data;
  try {response = await fetch("/lab" + path, {method, headers, credentials:"same-origin", body:body === undefined ? undefined : JSON.stringify(body)}); data = await response.json();}
  catch {throw new Error(mutating ? "UNCERTAIN" : "CONNECTION");}
  if (mutating && recovery?.token !== owner) throw new Error("STALE");
  if (inspect) {
    el("request-view").textContent = pretty({method, path, ...(response.ok && body ? {body:safeTechnical(body)} : {}), ...(key ? {idempotency:"Original stable key retained"} : {})});
    el("response-status").textContent = String(response.status);
    el("response-view").textContent = pretty(response.ok ? safeTechnical(data) : {error:"Request rejected; raw input and details omitted."});
  }
  if (!response.ok) {
    if (response.status === 403 && data.error === "LAB_FORBIDDEN") {
      if (recovery?.kind === "chat") {recovery.sessionLost = true; persistRecovery();}
      chatIds.clear(); await session();
      // A first chat attempt explicitly rejected by CSRF never reached a tool.
      // An older unresolved call being reconciled keeps its original identity.
      if (startedNew && recovery?.kind === "chat") releaseRecovery(owner);
      el("chat-messages").replaceChildren(node("p", "Session renewed. Previous chat memory is unavailable. Resume your persisted operation before starting another request."));
      throw new Error("SESSION");
    }
    if (mutating && startedNew && (response.status < 500 || data.error === "PROVIDER_NOT_CONFIGURED")) releaseRecovery(owner);
    if (data.error === "PROVIDER_NOT_CONFIGURED") chatAvailable = false;
    throw new Error(response.status === 404 ? "NOT_FOUND" : response.status === 422 ? "INVALID" : response.status === 409 ? "CONFLICT" : response.status >= 500 ? "UNAVAILABLE" : "FORBIDDEN");
  }
  return data;
  } finally {if (mutating) mutationInFlight = false;}
}
const errorText = code => ({AMOUNT:"Enter a positive USD amount with up to two decimals (for example 100.01).", ID:"Enter a valid operation ID in UUID format.", NOT_FOUND:"Operation not found. Check the saved ID and try again.", INVALID:"The request is invalid. Check the operation ID or draft values.", CONFLICT:"The operation cannot take that action. Refresh its persisted state before continuing.", FORBIDDEN:"This action is not permitted. Review the policy and operation state.", SESSION:"Session renewed after a restart or session change. No action was repeated. Review the persisted operation, then choose the action again.", UNCERTAIN:"The outcome could not be confirmed. No request was retried. Check the original operation before proceeding.", UNAVAILABLE:"A service is unavailable. Check persisted state before repeating any action.", CONNECTION:"Unable to connect. Check the local services, then refresh.", BLOCKED:"Reconcile the previous request before starting another operation."}[code] || "Unable to complete this action. Refresh persisted state before continuing.");
function recoveryError(code) {
  return {RECOVERY:"The original outcome cannot yet be verified. Keep the recovery record and recover the original operation reference/server context; unrelated operations cannot unlock it.", STORAGE:"Recovery data could not be saved. No new financial request was sent. Restore browser storage and reconcile the original request.", STALE:"An outdated response was ignored. Reconcile the current original request."}[code];
}
function controls() {
  const blocked = !!recovery;
  for (const b of document.querySelectorAll("[data-lock]")) b.disabled = busy || !ready;
  for (const b of document.querySelectorAll("[data-prompt]")) b.disabled = busy || !ready || !chatAvailable || blocked;
  el("chat-input").disabled = el("chat-send").disabled = busy || !ready || !chatAvailable || blocked;
  el("chat-retry").hidden = recovery?.kind !== "chat" || recovery.sessionLost;
  el("chat-retry").disabled = busy || !ready;
  el("draft-fields").disabled = busy || !!draft || blocked;
  el("submit").disabled = busy || !ready || !!draft || blocked;
  el("recover-draft").hidden = recovery?.kind !== "draft";
  el("new-draft").disabled = el("new-operation").disabled = busy || !ready || blocked;
  for (const b of document.querySelectorAll("[data-start]")) b.disabled = busy || !ready || blocked;
  if (current) {
    const p = presentation(current);
    el("review").disabled = busy || blocked || !p.review;
    el("execute").disabled = busy || blocked || !p.execute;
    el("replay").disabled = busy || blocked || !p.replay;
  }
  el("approve").disabled = busy || blocked || !el("approval-confirm").checked || !current || !presentation(current).review || current.id !== reviewId;
  el("reject").disabled = busy || blocked || !current || !presentation(current).review || current.id !== reviewId;
  el("review-cancel").disabled = busy;
  el("content").setAttribute("aria-busy", String(busy));
  renderRecovery();
}
async function action(fn) {
  if (busy || !ready) return;
  busy = true; controls();
  try {await fn();}
  catch (error) {notice(recoveryError(error.message) || errorText(error.message), true);}
  finally {busy = false; if (current) renderOperation(current); controls();}
}
function showView(name, focus = true) {
  view = ["dashboard","assistant","operations"].includes(name) ? name : "dashboard";
  const titles = {dashboard:["Dashboard","Your workspace, at a glance.","Move simulated money with a clear decision at every step."], assistant:["AI Assistant","What would you like to do?","Describe an intent. Review the decision. Stay in control."], operations:["Operations","Every step, in one place.","Review the exact request and follow its next action."]};
  for (const id of ["dashboard","assistant","operations"]) el(id + "-view").hidden = id !== view;
  for (const a of document.querySelectorAll("[data-view]")) {if (a.dataset.view === view) a.setAttribute("aria-current","page"); else a.removeAttribute("aria-current");}
  [el("view-name").textContent, el("page-title").textContent, el("page-description").textContent] = titles[view];
  el("operation-workspace").hidden = view === "dashboard";
  el(view === "assistant" ? "assistant-operation-slot" : "operations-operation-slot").append(el("operation-workspace"));
  if (focus) el("page-title").focus();
}
function navigate(name) {if (location.hash === "#" + name) showView(name); else location.hash = name;}
function remember(op) {
  recent.set(op.id, op); recentIds = [op.id, ...recentIds.filter(id => id !== op.id)].slice(0, 20);
  storageSet("agentgate-operation", op.id); storageSet("agentgate-recent", pretty(recentIds)); renderRecent();
}
function renderRecent() {
  el("recent-operations").replaceChildren();
  if (!recentIds.length) {el("recent-operations").append(node("p","No operations yet. Start with a small transfer.")); return;}
  for (const id of recentIds.slice(0, 12)) {
    const op = recent.get(id), row = node("button", "", "recent-row"); row.type = "button"; row.dataset.lock = ""; row.disabled = busy || !ready;
    const label = node("span", op ? operationTitle(op) : "Saved operation"); label.append(node("small", op ? operationRoute(op) : id));
    row.append(label, node("span", op ? presentation(op).title : "Load state →", "badge neutral"));
    row.addEventListener("click", () => action(async () => {await loadOperation(id); el("manual-entry").hidden = true; navigate("operations"); notice(recovery ? recoveryGuidance() : "Persisted operation restored. Review its exact request before any further action.");}));
    el("recent-operations").append(row);
  }
}
function operationTitle(op) {return op.tool === "get_balance" ? "Balance inquiry" : "Transfer " + money(op.arguments.amount_cents);}
function operationRoute(op) {return op.tool === "get_balance" ? accountName(op.arguments.account_id) + " · USD balance" : accountName(op.arguments.source_account_id) + " → " + accountName(op.arguments.destination_account_id);}
function renderOperation(op) {
  current = op; const p = presentation(op);
  el("empty").hidden = true; el("operation-detail").hidden = false;
  el("operation-title").textContent = operationTitle(op); el("operation-route").textContent = operationRoute(op);
  el("state").textContent = p.title; el("state").className = "badge " + p.tone;
  el("guidance-title").textContent = recovery ? "Outcome needs verification" : p.title;
  el("guidance").textContent = recovery ? recoveryGuidance() : p.guidance;
  el("guidance-box").className = "guidance " + (recovery ? "pending" : p.tone);
  el("deadline").textContent = op.approval ? "Approval deadline: " + new Date(op.approval.expires_at).toLocaleString() + (p.elapsed ? " · Local deadline guard; persisted status: " + op.state : "") : "";
  el("decision").textContent = policyNames[op.decision] || "Unavailable";
  el("reason").textContent = reasons[op.reason] || "Inspect policy evidence in the developer details.";
  el("approval-state").textContent = op.approval ? ({PENDING:"Pending independent review",GRANTED:"Approved for this exact request",REJECTED:"Rejected",EXPIRED:"Expired",CONSUMED:"Used by this execution"}[op.approval.state] || "Unavailable") : "Not required";
  el("execution-state").textContent = op.state === "SUCCEEDED" ? "Completed · stored result" : ["FAILED","TIMED_OUT"].includes(op.state) ? p.title : "No successful result recorded";
  el("review").hidden = !p.review; el("execute").hidden = !p.execute; el("replay").hidden = !p.replay;
  el("execute").textContent = op.decision === "REQUIRE_APPROVAL" ? "Execute approved transfer" : "Execute operation";
  el("replay").textContent = op.state === "SUCCEEDED" ? "Replay safely" : "View stored outcome";
  el("reconcile").hidden = !recovery && op.state !== "EXECUTING" && !p.elapsed;
  el("receipt").hidden = op.state !== "SUCCEEDED" || !op.result;
  el("result").textContent = op.result ? op.tool === "get_balance" ? accountName(op.result.account_id) + " balance: " + money(op.result.balance_cents) : money(op.result.amount_cents) + " transferred · " + operationRoute(op) + ". View current balances on Dashboard." : "No stored successful result.";
  el("operation-id").textContent = op.id; el("intent").textContent = pretty(safeTechnical({tool:op.tool, arguments:op.arguments}));
  el("stepper").replaceChildren();
  const labels = ["Request received","Policy evaluated","Human approval","Execution","Final result"];
  labels.forEach((text, i) => {
    let state = i < p.stage ? "done" : i === p.stage ? "current" : "pending";
    if (["DENIED","REJECTED","EXPIRED","FAILED","TIMED_OUT"].includes(op.state) || p.elapsed) {if (i === p.stage) state = "stopped";}
    if (op.state === "SUCCEEDED") state = "done";
    if (i === 2 && op.decision === "ALLOW") state = p.stage >= 3 ? "done" : "pending";
    const li = node("li", text, state); const note = i === 2 && op.decision === "ALLOW" ? "Not required" : state === "done" ? "Complete" : state === "current" ? "Current step" : state === "stopped" ? "Stopped" : "Pending";
    li.append(node("span", note, "stage-note")); if (state === "current") li.setAttribute("aria-current","step"); el("stepper").append(li);
  });
  renderAudit(); controls();
}
async function loadOperation(id, inspect = true, owner = null) {
  if (!validId(id)) throw new Error("ID");
  const op = await request("GET", "/operations/" + id, undefined, undefined, inspect);
  if (owner && recovery?.token !== owner) throw new Error("STALE");
  if (op.id !== id) throw new Error("RECOVERY");
  if (owner) resolveRecovery(op, owner);
  renderOperation(op); remember(op); return op;
}
async function balances() {const accounts = await request("GET", "/accounts", undefined, undefined, false); for (const a of accounts) if (["acct-alice","acct-bob"].includes(a.id)) el(a.id.slice(5)).textContent = money(a.balance_cents);}
function renderAudit() {
  el("events").replaceChildren(); const list = el("filter-operation").checked && current ? auditEvents.filter(e => e.operation_id === current.id) : auditEvents;
  if (!list.length) el("events").append(node("p", "No matching events in loaded pages. Load more to continue searching."));
  for (const e of [...list].reverse()) {
    const row = node("div", "", "event");
    const labels = {OPERATION_REQUESTED:"Request evaluated",APPROVAL_DECIDED:"Human review recorded",APPROVAL_EXPIRED:"Approval expired",OPERATION_ATTEMPTED:"Execution requested",OPERATION_DISPATCHED:"Execution started",OPERATION_EXECUTED:"Operation completed",OPERATION_FAILED:"Execution failed"};
    const identity = safeTechnical({principal_id:e.principal_id, approver_id:e.approver_id});
    row.append(node("strong", labels[e.event_type] || "Operation evidence recorded"), node("small", (reasons[e.reason] || (e.reason === "HUMAN_APPROVED" ? "Independent human approval" : "")) + " · " + e.operation_id), node("small", identity.approver_id || identity.principal_id || ""), node("time", new Date(e.occurred_at).toLocaleString())); el("events").append(row);
  }
  el("audit-evidence").textContent = pretty(list.map(e => safeTechnical(e)));
}
async function audit(reset = false) {
  const data = await request("GET", "/audit?after=" + (reset ? 0 : auditAfter), undefined, undefined, false);
  if (reset) {auditAfter = 0; auditEvents = [];}
  for (const e of data.events) {if (!auditEvents.some(old => old.id === e.id)) auditEvents.push(e); if (validId(e.operation_id) && !recentIds.includes(e.operation_id)) recentIds.push(e.operation_id);}
  recentIds = recentIds.slice(0, 20); auditAfter = data.next_after; renderAudit(); renderRecent();
}
async function auditView(reset = false) {
  try {await audit(reset); el("audit-status").textContent = "Audit evidence refreshed.";}
  catch {el("audit-status").textContent = "Audit evidence is unavailable. The confirmed operation is unchanged. Retry audit retrieval independently.";}
}
async function reconcileOriginal() {
  const original = recovery;
  if (!original) {if (current) await loadOperation(current.id); return;}
  if (original.operationId) {
    await loadOperation(original.operationId, true, original.token);
    notice(recovery ? recoveryGuidance() : "Original operation reconciled against persisted state. No financial action was repeated.");
  } else if (original.kind === "draft") await submitDraft(true);
  else if (!original.sessionLost) await chatTurn({action:"retry"}, original.token);
  else throw new Error("RECOVERY");
}
async function refresh() {
  if (!csrf) await session();
  // Refresh is read-only; unknown proposals require the separate explicit recovery action.
  if (recovery?.operationId) await loadOperation(recovery.operationId, true, recovery.token);
  else if (current) await loadOperation(current.id);
  await balances(); await auditView(true); await chatStatus();
  notice(recovery ? recoveryGuidance() : "State refreshed from AgentGate. No real money moves.");
}
function newDraft() {
  assertMutationAllowed();
  draft = null; draftKey = "lab-" + crypto.randomUUID(); storageRemove("agentgate-pending-draft");
  current = null; el("operation-detail").hidden = true; el("empty").hidden = false;
  el("state").textContent = "New draft"; el("state").className = "badge neutral";
  el("operation-title").textContent = "Your next operation";
  el("draft-status").textContent = "New draft. Submission only evaluates policy; it does not execute.";
  el("manual-entry").hidden = false; controls();
}
async function submitDraft(recover = false) {
  const original = recover ? recovery : null;
  assertMutationAllowed(original?.token);
  if (recover && original?.kind !== "draft") throw new Error("BLOCKED");
  if (original?.operationId) return reconcileOriginal();
  if (original) {draft = original.payload; draftKey = original.key;}
  if (!draft) {
    const tool = el("tool").value;
    draft = {tool, arguments:tool === "get_balance" ? {account_id:"acct-alice"} : {source_account_id:"acct-alice", destination_account_id:"acct-bob", amount_cents:usdToCents(el("amount").value), currency:"USD"}};
  }
  const pending = request("POST", "/operations", draft, draftKey, true, original?.token);
  const owner = recovery?.token;
  try {
    const op = await pending;
    bindRecoveryId(owner, op.id);
    storageSet("agentgate-operation", op.id);
    await loadOperation(op.id, false, owner); el("manual-entry").hidden = true;
    el("draft-status").textContent = "Submitted. This exact request is immutable. Choose New draft to change the amount.";
  } catch (error) {
    if (!recovery) draft = null;
    throw error;
  }
  await auditView(true); notice("Request evaluated. Follow the next action below; nothing has executed.");
}
function readableMessage(text) {
  const p = node("p");
  for (const part of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)) {
    if (part.startsWith("**") && part.endsWith("**")) p.append(node("b", part.slice(2,-2)));
    else if (part.startsWith("`") && part.endsWith("`")) p.append(node("code", part.slice(1,-1)));
    else p.append(document.createTextNode(part));
  }
  return p;
}
async function chatStatus() {
  try {const d = await request("GET", "/chat/status", undefined, undefined, false); chatAvailable = d.available === true; el("chat-status").textContent = chatAvailable ? "Assistant ready. Provider capability is verified on the first message." : "Assistant unavailable. Use manual mode to continue the same guided workflow.";}
  catch {chatAvailable = false; el("chat-status").textContent = "Assistant unavailable. Manual mode remains available.";}
  if (recovery) el("chat-status").textContent = recoveryGuidance();
}
async function chatTurn(payload, originalOwner = null) {
  assertMutationAllowed(originalOwner);
  if (originalOwner && (recovery.kind !== "chat" || recovery.sessionLost || payload.action !== "retry")) throw new Error("BLOCKED");
  el("chat-status").textContent = "Processing · waiting for the assistant and operation service…";
  const pending = request("POST", "/chat/turn", payload, undefined, true, originalOwner);
  const owner = recovery?.token;
  try {
  const data = await pending;
  if (recovery?.token !== owner || typeof data.retry_pending !== "boolean" || !Array.isArray(data.operations)) throw new Error("RECOVERY");
  const ops = data.operations;
  const lastResult = [...(data.events || [])].reverse().find(event => validId(event.result?.id));
  const newlyKnown = ops.filter(op => !recovery.knownIds?.includes(op.id));
  const active = recovery.operationId || lastResult?.result.id || newlyKnown.at(-1)?.id;
  // Retain the original ID before any auxiliary read can fail. An unrelated old
  // conversation snapshot is never accepted as evidence for an uncertain call.
  if (active && !data.retry_pending) bindRecoveryId(owner, active);
  for (const op of ops) {if (validId(op.id)) {chatIds.add(op.id); remember(op);}}
  el("chat-messages").replaceChildren();
  for (const m of data.messages || []) {const row = node("article", "", "chat-message " + (m.role === "user" ? "user" : "assistant")); row.append(node("strong", m.role === "user" ? "You" : "Assistant · unverified model text"), readableMessage(String(m.content))); el("chat-messages").append(row);}
  el("chat-messages").scrollTop = el("chat-messages").scrollHeight;
  for (const event of data.events || []) {const d = node("details"); d.append(node("summary", "Tool evidence · " + (["tool","discovery","blocked","limit"].includes(event.type) ? event.type : "service event")), node("pre", pretty(safeTechnical(event)))); el("chat-tools").append(d);}
  while (el("chat-tools").children.length > 60) el("chat-tools").firstElementChild.remove();
  if (!data.retry_pending) {
    if (active) await loadOperation(active, false, owner);
    // A confirmed server response with no unfinished MCP call and no new
    // operation proves this turn did not leave an unknown financial mutation.
    else releaseRecovery(owner);
  }
  const errors = {AGENT_UNAVAILABLE:"The assistant provider is unavailable. Inspect any persisted operation before trying again.", MCP_UNAVAILABLE:"The operation service is unavailable. Resume the original call or inspect the persisted operation.", INVALID_AGENT_OUTPUT:"The assistant returned an invalid proposal. No authority was granted.", TOOL_LIMIT:"The assistant reached its call limit. Review the persisted operation."};
  el("chat-status").textContent = recovery ? recoveryGuidance() : data.error ? (errors[data.error] || "The assistant could not finish. Review persisted state before continuing.") : "Turn complete. Follow the next action in the verified operation panel.";
  if (payload.message) el("chat-input").value = "";
  } catch (error) {
    el("chat-status").textContent = recoveryError(error.message) || (recovery ? recoveryGuidance() : "The chat request failed. No uncertain financial outcome remains. " + errorText(error.message));
    throw error;
  }
  // Auxiliary reads cannot change financial recovery or leave Processing visible.
  try {await balances();} catch {notice("Current balances are unavailable. Refresh them independently.", true);}
  await auditView(true);
  notice(recovery ? recoveryGuidance() : "AgentGate state loaded. Assistant prose does not authorize execution.");
}
async function openReview() {
  assertMutationAllowed();
  const id = current.id; await loadOperation(id);
  if (!presentation(current).review) throw new Error("CONFLICT");
  reviewId = id; el("approval-confirm").checked = false;
  el("review-transfer").textContent = operationTitle(current) + " · " + operationRoute(current);
  el("review-policy").textContent = policyNames[current.decision];
  el("review-deadline").textContent = new Date(current.approval.expires_at).toLocaleString();
  el("review-reference").textContent = current.id; el("review-dialog").showModal();
}
async function decide(decision) {
  assertMutationAllowed();
  const id = reviewId;
  if (!id || current?.id !== id || (decision === "APPROVE" && !el("approval-confirm").checked)) throw new Error("CONFLICT");
  await loadOperation(id);
  if (!presentation(current).review) {el("review-dialog").close(); throw new Error("CONFLICT");}
  let owner;
  try {const pending = request("POST", "/operations/" + id + "/approval", {decision}); owner = recovery?.token; await pending;}
  finally {el("review-dialog").close();}
  await loadOperation(id, false, owner); await auditView(true); el("guidance-title").tabIndex = -1; el("guidance-title").focus(); notice(decision === "APPROVE" ? "Approved. No transfer has executed. Choose Execute approved transfer when ready." : "Request rejected. No money moved.");
}
async function execute() {
  assertMutationAllowed();
  const id = current.id, replay = presentation(current).replay;
  await loadOperation(id, false);
  if (!presentation(current)[replay ? "replay" : "execute"]) throw new Error("CONFLICT");
  if (replay && current.state !== "SUCCEEDED") {await auditView(true); notice("Stored terminal outcome retrieved. Execution was not retried."); return;}
  if (chatIds.has(id) && chatAvailable) await chatTurn({action:"execute", operation_id:id});
  else {
    const pending = request("POST", "/operations/" + id + "/execute"); const owner = recovery?.token; await pending;
    await loadOperation(id, false, owner); await balances(); await auditView(true);
    notice(replay ? "Stored outcome retrieved. Replay creates no duplicate debit." : "Execution response verified. View the stored outcome and audit below.");
  }
}
function bind() {
  window.addEventListener("hashchange", () => {if (location.hash === "#inspector") {el("inspector").open = true; el("inspector").querySelector("summary").focus();} else showView(location.hash.slice(1));});
  for (const b of document.querySelectorAll("[data-start]")) b.addEventListener("click", () => action(async () => {assertMutationAllowed(); if (b.dataset.start === "manual") {newDraft(); navigate("operations");} else navigate("assistant");}));
  for (const b of document.querySelectorAll("[data-prompt]")) b.addEventListener("click", () => {el("chat-input").value = b.dataset.prompt; el("chat-input").focus();});
  for (const b of document.querySelectorAll("[data-amount]")) b.addEventListener("click", () => {el("amount").value = b.dataset.amount;});
  el("operation-form").addEventListener("submit", e => {e.preventDefault(); action(() => submitDraft());});
  el("tool").addEventListener("change", () => {const transfer = el("tool").value === "simulate_transfer"; el("transfer-fields").hidden = !transfer; el("amount").required = transfer;});
  el("new-draft").addEventListener("click", () => action(async () => newDraft()));
  el("recover-draft").addEventListener("click", () => action(reconcileOriginal));
  el("recover-original").addEventListener("click", () => action(reconcileOriginal));
  el("new-operation").addEventListener("click", () => action(async () => {newDraft(); navigate("operations"); el("amount").focus();}));
  el("chat-form").addEventListener("submit", e => {e.preventDefault(); if (chatAvailable) action(() => chatTurn({message:el("chat-input").value}));});
  el("chat-retry").addEventListener("click", () => action(reconcileOriginal));
  el("review").addEventListener("click", () => action(openReview));
  el("approval-confirm").addEventListener("change", controls);
  for (const name of ["approve","reject"]) el(name).addEventListener("click", () => action(() => decide(name.toUpperCase())));
  el("review-dialog").addEventListener("close", () => {reviewId = null; (el("review").hidden ? el("page-title") : el("review")).focus();});
  for (const name of ["execute","replay"]) el(name).addEventListener("click", () => action(execute));
  el("restore-form").addEventListener("submit", e => {e.preventDefault(); action(async () => {await loadOperation(el("restore-id").value.trim()); el("manual-entry").hidden = true; notice(recovery ? recoveryGuidance() : "Operation restored from persisted state. Review its exact request before any further action.");});});
  el("refresh").addEventListener("click", () => action(refresh));
  el("reconcile").addEventListener("click", () => action(reconcileOriginal));
  el("more-audit").addEventListener("click", () => action(() => auditView()));
  el("retry-audit").addEventListener("click", () => action(() => auditView(true)));
  el("filter-operation").addEventListener("change", renderAudit);
  el("review-dialog").addEventListener("cancel", e => {if (busy) e.preventDefault();});
}
async function start() {
  bind(); showView(location.hash.slice(1), false); controls();
  try {
    recentIds = JSON.parse(storageGet("agentgate-recent") || "[]").filter(validId).slice(0, 20);
  } catch {recentIds = [];}
  try {
    recovery = JSON.parse(storageGet("agentgate-recovery") || "null");
    if (recovery && (!['draft','operation','chat'].includes(recovery.kind) || typeof recovery.token !== "string" || (recovery.operationId && !validId(recovery.operationId)))) throw new Error("RECOVERY");
    const savedDraft = JSON.parse(storageGet("agentgate-pending-draft") || "null");
    if (!recovery && savedDraft) {
      if (!/^lab-[a-f0-9-]{36}$/.test(savedDraft.key) || !["get_balance","simulate_transfer"].includes(savedDraft.payload?.tool)) throw new Error("RECOVERY");
      recovery = {kind:"draft", payload:savedDraft.payload, key:savedDraft.key, token:crypto.randomUUID() + ":legacy"};
      persistRecovery();
    }
    if (!recovery && storageGet("agentgate-chat-unconfirmed")) {recovery = {kind:"chat", token:crypto.randomUUID() + ":legacy", sessionLost:true}; persistRecovery();}
    if (recovery?.kind === "chat") {recovery.sessionLost = true; persistRecovery();}
    if (recovery?.kind === "draft") {
      draft = recovery.payload; draftKey = recovery.key; el("manual-entry").hidden = false;
      el("tool").value = draft.tool; el("amount").value = draft.tool === "simulate_transfer" ? (draft.arguments.amount_cents / 100).toFixed(2) : "";
      el("transfer-fields").hidden = draft.tool !== "simulate_transfer"; el("amount").required = draft.tool === "simulate_transfer";
      el("draft-status").textContent = "A previous submission needs reconciliation. The original key and exact request were retained.";
    }
    if (!recovery) draftKey = "lab-" + crypto.randomUUID();
  } catch {
    // Corrupt/unavailable recovery storage is never permission to create another intent.
    recovery = {kind:"chat", token:"unavailable", sessionLost:true};
  }
  let restorationError = null;
  try {
    await session(); ready = true;
    const saved = recovery?.operationId || storageGet("agentgate-operation");
    if (saved) {el("restore-id").value = saved; try {await loadOperation(saved, false);} catch (e) {restorationError = "Unable to restore the saved operation. " + errorText(e.message);}}
    try {await balances();} catch {notice("Current balances are unavailable. Refresh when the service is ready.", true);}
    await auditView();
    await chatStatus();
    notice(restorationError || (recovery ? recoveryGuidance() : "Local lab ready. Start a request or resume an existing operation."), !!restorationError);
    if (restorationError) showView("operations", false);
  } catch (e) {ready = true; notice(restorationError || errorText(e.message), true);}
  controls();
  setInterval(() => {if (current && !busy) renderOperation(current);}, 1000);
}
if (typeof document !== "undefined") start();
