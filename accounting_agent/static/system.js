"use strict";
const $ = (id) => document.getElementById(id);
const state = {token: "", run: null, selected: null, runs: [], busy: false, pending: null, dirty: false, loadVersion: 0};
let exportUrl=null;
let backupUrl=null;
function clearBackup() { if(backupUrl) URL.revokeObjectURL(backupUrl); backupUrl=null; $("download-backup").hidden=true; $("backup-feedback").textContent=""; }
function clearExport() { if(exportUrl) URL.revokeObjectURL(exportUrl); exportUrl=null; $("export-preview").hidden=true; $("export-json").textContent=""; }
const labels = {unreviewed:"To review", not_required:"Prepared", reviewed:"Reviewed locally", needs_changes:"Needs changes", rejected:"Rejected"};
const policies = {draft_only:"Draft only", auto_allowed:"Prepared", approval_required:"Review required", escalation_required:"Senior review required", forbidden:"Blocked"};
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const dateText = (value) => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? String(value || "") : date.toLocaleString(undefined,{dateStyle:"medium",timeStyle:"short"}); };
const pathFor = (runId,caseId) => `/api/runs/${encodeURIComponent(runId)}` + (caseId ? `/cases/${encodeURIComponent(caseId)}` : "");

function feedback(message,error=false) { $("feedback").textContent=message; $("feedback").dataset.error=String(error); }
function busy(value) { state.busy=value; $("sample-run").disabled=value || !state.token; $("bundle-file").disabled=value || !state.token; $("refresh").disabled=value; $("backup-workspace").disabled=value || !state.token; $("workspace").setAttribute("aria-busy",String(value)); }
async function api(url,body) {
  const response=await fetch(url,body===undefined?{cache:"no-store"}:{method:"POST",headers:{"Content-Type":"application/json","X-Accounting-Session":state.token},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || "The request could not complete.");
  return result;
}
function canLeave() { if(state.dirty) { feedback("Save the current review or clear its note before switching cases.",true); $("review-note")?.focus(); return false; } return true; }
function renderHistory() {
  $("run-history").innerHTML=state.runs.length ? state.runs.map(run=>`<button type="button" data-run="${escapeHTML(run.run_id)}" aria-current="${state.run?.run_id===run.run_id}"><span>${escapeHTML(run.name || "Accounting run")}</span><small>${escapeHTML(dateText(run.created_at))} · ${escapeHTML(run.status)}</small></button>`).join("") : '<p class="muted">No runs yet. Start with the sample month.</p>';
  $("run-history").querySelectorAll("[data-run]").forEach(button=>button.addEventListener("click",()=>{ if(!state.busy && canLeave()) loadRun(button.dataset.run); }));
}
async function refreshHistory() { const result=await api("/api/runs"); state.runs=result.runs; renderHistory(); }
async function loadRun(id) {
  const version=++state.loadVersion;
  busy(true); feedback("Loading the saved run…");
  try { const run=await api(pathFor(id)); if(version!==state.loadVersion) return; state.run=run; state.selected=null; state.dirty=false; history.replaceState(null,"",`#run=${encodeURIComponent(id)}`); renderRun(); renderHistory(); feedback("Saved evidence loaded."); }
  catch(error) { feedback(error.message,true); }
  finally { if(version===state.loadVersion) busy(false); }
}
async function startRun(bundle) {
  if(!canLeave() || state.busy) return;
  clearBackup();
  const serialized=JSON.stringify(bundle);
  if(state.pending?.serialized!==serialized) state.pending={serialized,key:crypto.randomUUID()};
  busy(true); feedback("Validating intake and preparing accounting and reconciliation proposals…");
  try {
    const run=await api("/api/runs",{bundle,request_key:state.pending.key});
    state.run=run; state.selected=null; state.pending=null; state.dirty=false;
    history.replaceState(null,"",`#run=${encodeURIComponent(run.run_id)}`);
    $("case-search").value=""; $("case-filter").value="all";
    renderRun(); await refreshHistory();
    feedback(run.status==="failed" ? "The run stopped. Its failure and evidence are saved below." : "Processing complete. Review the cases, then export the evidence package.",run.status==="failed");
  } catch(error) {
    try { await refreshHistory(); } catch (_) { /* Preserve the original intake failure. */ }
    feedback(`${error.message} Check Work history for the saved run status.`,true);
  }
  finally { busy(false); $("bundle-file").value=""; }
}
function casesSorted() {
  const ranks={forbidden:0,escalation_required:1,approval_required:2,draft_only:3,auto_allowed:4};
  return [...(state.run?.cases || [])].sort((a,b)=>(ranks[a.policy_mode]??5)-(ranks[b.policy_mode]??5) || String(a.presentation.reference).localeCompare(String(b.presentation.reference)));
}
function renderRun() {
  clearExport();
  const run=state.run, cases=run.cases || [];
  $("empty-workspace").hidden=true; $("active-run").hidden=false;
  $("run-title").textContent=run.name || "Accounting run";
  $("run-scope").textContent=`${run.client_id} · ${run.entity_id}`;
  $("run-meta").textContent=`${dateText(run.created_at)} · ${run.status} · Saved locally`;
  $("export-run").href=pathFor(run.run_id)+"/export";
  const runError=run.integrity_verified===false?"Saved evidence is inconsistent. Reviews and exports are blocked; restore a verified backup.":run.error;
  $("run-error").hidden=!runError; $("run-error").textContent=runError || "";
  $("stat-total").textContent=cases.length;
  $("stat-pending").textContent=cases.filter(c=>c.review_status==="unreviewed").length;
  $("stat-drafts").textContent=cases.filter(c=>c.policy_mode==="draft_only" || c.policy_mode==="auto_allowed").length;
  $("stat-changes").textContent=cases.filter(c=>c.review_status==="needs_changes").length;
  renderCases(); renderAudit();
  if(!state.selected) $("case-detail").innerHTML='<div class="detail-empty"><h3>Select a case</h3><p>Inspect the proposed accounting and record your local review here.</p></div>';
}
function renderCases() {
  const query=$("case-search").value.trim().toLocaleLowerCase(), filter=$("case-filter").value;
  const cases=casesSorted().filter(c=>{
    const p=c.presentation;
    const match=filter==="all" || (filter==="pending" && c.review_status==="unreviewed") || (filter==="drafts" && ["draft_only","auto_allowed"].includes(c.policy_mode)) || c.review_status===filter;
    return match && `${p.party} ${p.reference} ${p.amount} ${p.title} ${c.case_id}`.toLocaleLowerCase().includes(query);
  });
  $("case-count").textContent=`${cases.length} of ${state.run.cases.length}`;
  $("case-list").innerHTML=cases.length ? cases.map(c=>{
    const p=c.presentation;
    return `<button type="button" class="case-card" data-case="${escapeHTML(c.case_id)}" aria-current="${state.selected===c.case_id}"><span class="case-top"><strong>${escapeHTML(p.party || "Unidentified counterparty")}</strong><span class="case-amount">${escapeHTML(p.amount)}</span></span><span class="case-reference">${escapeHTML(p.reference || c.case_id)}</span><span class="case-reason">${escapeHTML(p.title)}</span><span class="case-tags"><span class="badge" data-severity="${escapeHTML(p.severity)}">${escapeHTML(policies[c.policy_mode] || c.policy_mode)}</span><span class="badge">${escapeHTML(labels[c.review_status] || c.review_status)}</span></span></button>`;
  }).join("") : '<div class="no-cases">No cases match these filters. <button id="clear-cases" type="button" class="text-button">Clear filters</button></div>';
  $("case-list").querySelectorAll("[data-case]").forEach(button=>button.addEventListener("click",()=>{ if(!state.busy && (state.selected===button.dataset.case || canLeave())) selectCase(button.dataset.case); }));
  $("clear-cases")?.addEventListener("click",()=>{$("case-search").value="";$("case-filter").value="all";renderCases();$("case-search").focus();});
}
async function selectCase(id) {
  if(state.dirty) return;
  const runId=state.run.run_id; const version=++state.loadVersion;
  try { const item=await api(pathFor(runId,id)); if(version!==state.loadVersion || state.run.run_id!==runId) return; state.selected=id; renderCases(); renderDetail(item); $("case-detail").focus({preventScroll:true}); feedback(`Case ${item.presentation.reference || item.case_id} loaded.`); if(innerWidth<1100) $("case-detail").scrollIntoView({block:"start"}); }
  catch(error) { feedback(error.message,true); }
}
function renderDetail(item) {
  const p=item.presentation;
  const reviews=item.reviews || item.review_history || [];
  const candidateTable=p.candidates.length ? `<table class="candidate-table"><caption>Tied candidates · none selected</caption><thead><tr><th scope="col">Reference</th><th scope="col">Score</th></tr></thead><tbody>${p.candidates.map(c=>`<tr><td>${escapeHTML(c.reference)}</td><td>${escapeHTML(c.score)}</td></tr>`).join("")}</tbody></table>` : "";
  const rawRisks=item.packet?.risk?.flags || [];
  const riskMessages=[...new Set(rawRisks.filter(r=>r && typeof r==="object" && r.message).map(r=>r.message))];
  $("case-detail").innerHTML=`<div class="detail-heading"><span class="badge" data-severity="${escapeHTML(p.severity)}">${escapeHTML(policies[item.policy_mode] || item.policy_mode)}</span><h3>${escapeHTML(p.party || "Case evidence")}</h3><p class="muted">${escapeHTML(p.reference || item.case_id)} · ${item.kind==="bank_reconciliation"?"Bank transaction":"Supplier invoice"}</p>${p.amount?`<div class="detail-amount">${escapeHTML(p.amount)}</div>`:""}</div><div class="detail-body"><div class="decision"><strong>${escapeHTML(p.title)}</strong>${escapeHTML(p.reason)}</div><dl class="facts">${p.facts.map(f=>`<div><dt>${escapeHTML(f.label)}</dt><dd>${escapeHTML(f.value)}</dd></div>`).join("")}</dl>${candidateTable}${riskMessages.length?`<details><summary>All risk findings (${riskMessages.length})</summary><ul>${riskMessages.map(message=>`<li>${escapeHTML(message)}</li>`).join("")}</ul></details>`:""}<form id="review-form" class="review-form"><h4>Record a local review</h4><p>This records your assessment. Original policy gates remain in force; this does not approve an invoice or authorize execution.</p><label for="review-outcome">Outcome<select id="review-outcome">${item.policy_mode!=="forbidden"?'<option value="reviewed">Reviewed locally</option>':""}<option value="needs_changes">Needs changes</option><option value="rejected">Reject proposal</option></select></label><label for="review-note">Review note<textarea id="review-note" maxlength="2000" required placeholder="What did you verify, or what needs to change?"></textarea></label><button class="primary" id="save-review" type="submit">Save review</button><p>Recorded as local operator · revision ${escapeHTML(item.review_revision)}</p></form><div class="review-history"><h4>Saved review history</h4>${reviews.length?`<ul>${reviews.map(r=>`<li><strong>${escapeHTML(labels[r.outcome] || r.outcome)}</strong> · ${escapeHTML(dateText(r.decided_at || r.created_at))}<p>${escapeHTML(r.note)}</p></li>`).join("")}</ul>`:'<p>No review recorded for this case.</p>'}</div><details><summary>Source packet and accounting proposal</summary><pre>${escapeHTML(JSON.stringify(item.packet,null,2))}</pre></details><details><summary>Evidence identity</summary><p class="muted">SHA-256 of this saved case packet</p><pre>${escapeHTML(item.evidence_hash)}</pre></details></div>`;
  if(item.integrity_verified===false) {
    $("save-review").disabled=true;
    feedback("Saved evidence is inconsistent. Review is blocked; restore a verified backup.",true);
  }
  if(["reviewed","needs_changes","rejected"].includes(item.review_status)) $("review-outcome").value=item.review_status;
  $("review-note").addEventListener("input",()=>{state.dirty=!!$("review-note").value.trim();});
  $("review-form").addEventListener("submit",async event=>{
    event.preventDefault(); if(state.busy) return;
    const note=$("review-note").value.trim(); if(!note) { feedback("Add a review note before saving.",true); $("review-note").focus(); return; }
    const runId=state.run.run_id;
    clearBackup();
    busy(true); $("save-review").disabled=true; feedback("Saving review and audit event…");
    try {
      const updated=await api(pathFor(runId,item.case_id)+"/review",{outcome:$("review-outcome").value,note,expected_revision:item.review_revision});
      state.dirty=false;
      state.run.cases=state.run.cases.map(c=>c.case_id===updated.case_id?updated:c);
      renderRun(); renderDetail(updated); $("save-review").focus();
      feedback("Review saved with its evidence and audit record. Financial policy is unchanged.");
      try { state.run=await api(pathFor(runId)); renderRun(); await refreshHistory(); }
      catch (_) { feedback("Review saved. The overview could not refresh; use Refresh to reload it.",true); }
    } catch(error) { feedback(error.message,true); $("save-review").disabled=false; }
    finally { busy(false); }
  });
}
function renderAudit() {
  const events=state.run.audit || state.run.audit_events || [];
  $("audit-list").innerHTML=events.length ? `<ol class="audit-events">${events.map(event=>`<li><span>${escapeHTML(String(event.event_type || event.type || event.action || "Audit event").replaceAll("_"," "))}${event.case_id?` · ${escapeHTML(event.case_id)}`:""}</span><time>${escapeHTML(dateText(event.created_at || event.timestamp))}</time></li>`).join("")}</ol>` : '<p class="muted">The complete run audit is included in the evidence export.</p>';
}
$("sample-run").addEventListener("click",async()=>{if(state.busy||!canLeave()) return;busy(true);try{const bundle=await api("/api/sample");busy(false);await startRun(bundle);}catch(error){busy(false);feedback(error.message,true);}});
$("bundle-file").addEventListener("change",async event=>{const file=event.target.files[0];if(!file)return;if(file.size>1800000){feedback("Use a synthetic JSON bundle smaller than 1.8 MB.",true);event.target.value="";return;}try{await startRun(JSON.parse(await file.text()));}catch(error){feedback(`Could not import the bundle: ${error.message}`,true);event.target.value="";}});
$("case-search").addEventListener("input",()=>{if(state.run)renderCases();});
$("case-filter").addEventListener("change",()=>{if(state.run)renderCases();});
$("refresh").addEventListener("click",async()=>{if(!canLeave())return;try{await refreshHistory();if(state.run)await loadRun(state.run.run_id);}catch(error){feedback(error.message,true);}});
$("export-run").addEventListener("click",async event=>{
  event.preventDefault();
  if(state.dirty || state.busy){feedback(state.dirty?"Save or clear your review note before exporting the saved evidence.":"Wait for the current operation before exporting.",true);return;}
  busy(true);feedback("Verifying saved evidence before preparing the export…");
  try {
    const exported=await api(pathFor(state.run.run_id)+"/export");
    if(!exported.integrity_verified)throw new Error("Evidence checks failed; export is blocked.");
    clearExport(); const json=JSON.stringify(exported,null,2);
    exportUrl=URL.createObjectURL(new Blob([json],{type:"application/json"}));
    $("download-export").href=exportUrl;$("download-export").download=`accounting-evidence-${state.run.run_id}.json`;
    $("export-summary").textContent=`${exported.cases.length} cases · ${exported.reviews.length} review record${exported.reviews.length===1?"":"s"} · ${exported.audit.length} audit events · Evidence checks passed`;
    $("export-json").textContent=json;$("export-preview").hidden=false;$("export-title").focus();
    feedback("Evidence package prepared from saved records. Inspect it here or download the JSON.");
  }catch(error){feedback(error.message,true);}finally{busy(false);}
});
window.addEventListener("beforeunload",event=>{if(state.dirty){event.preventDefault();event.returnValue="";}});
$("backup-workspace").addEventListener("click",async()=>{
  if(state.busy || !canLeave())return;
  busy(true); clearBackup(); $("backup-feedback").textContent="Checking and packaging saved work…";
  try {
    const response=await fetch("/api/workspace/backup",{cache:"no-store"});
    if(!response.ok) {const result=await response.json();throw new Error(result.error || "Backup could not complete.");}
    backupUrl=URL.createObjectURL(await response.blob());
    $("download-backup").href=backupUrl; $("download-backup").download="accounting-workspace.zip"; $("download-backup").hidden=false;
    $("backup-feedback").textContent="Verified backup ready. Save the ZIP to keep a recovery copy.";
    $("download-backup").focus();
  }catch(error){$("backup-feedback").textContent=error.message;}finally{busy(false);}
});
(async()=>{try{const session=await api("/api/session");state.token=session.csrf_token;await refreshHistory();busy(false);const id=new URLSearchParams(location.hash.slice(1)).get("run");if(id)await loadRun(id);else if(state.runs.length)await loadRun(state.runs[0].run_id);}catch(error){feedback(`Workspace could not load: ${error.message}`,true);}})();
