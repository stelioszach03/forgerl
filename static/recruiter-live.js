/* Optional new trial. Default recorded replay is independent and costs nothing. */
(() => {
  "use strict";
  if (typeof document === "undefined") return;
  const $ = id => document.getElementById(id);
  if (!$("live-trial")) return;
  const base = new URL("./", window.location.href);
  const route = suffix => new URL(`api/recruiter-live${suffix}`, base).href;
  const numeric = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const ratio = (a,b) => numeric(a) && numeric(b) && b > 0 ? `${a} / ${b}` : "—";
  const node = (tag,text) => { const element=document.createElement(tag); element.textContent=text; return element; };
  let liveId=null, timer=null, observingSince=0;
  function remember(value) { try { if(value) sessionStorage.setItem("forgerl-curated-run",value); else sessionStorage.removeItem("forgerl-curated-run"); } catch {} }
  function stopPolling() { if(timer) clearTimeout(timer); timer=null; }
  async function request(suffix, options={}) {
    const response=await fetch(route(suffix), {credentials:"same-origin", method:"GET", ...options});
    let data;
    try {data=await response.json();} catch {throw new Error("The live worker could not be reached. Recorded replay remains available.");}
    if(!response.ok) throw new Error(data?.detail?.message || data?.message || "The live trial could not complete. Recorded replay remains available.");
    return data;
  }
  async function availability() {
    try {
      const state=await request("/state");
      $("live-trial").hidden=state.reason === "recorded_only";
      $("live-availability").textContent=state.message || "Recorded replay remains available.";
      $("live-start").disabled=state.available !== true || !!liveId;
      if(!liveId) $("live-status").textContent=state.available === true ? "Available · explicit request only" : "Live trial paused";
    } catch(error) {
      // Optional live transport failure never blocks the evidence explorer.
      $("live-start").disabled=true;
      $("live-availability").textContent=error.message;
    }
  }
  function show(snapshot) {
    const labels={queued:"Queued",running:"New trial in progress",completed:"Fresh trial finished",failed:"Fresh trial failed",interrupted:"Fresh trial interrupted",budget_exhausted:"Live allowance reached",expired:"Queued trial expired"};
    $("live-status").textContent=labels[snapshot.status] || "Live trial status unavailable";
    const terminal=!["queued","running"].includes(snapshot.status);
    const result=snapshot.result;
    $("live-progress").textContent=snapshot.status === "queued" ? "Waiting for the private worker. No new candidate has been generated yet."
      : snapshot.status === "running" ? "The isolated worker is processing this one fixed trial. Refreshing its status does not submit another request."
      : result?.status === "completed" ? (result.solved ? "This fresh candidate passed the recorded visible and final checks." : "This fresh candidate did not pass all required checks. Its measured result is retained.")
      : "This fresh trial did not finish successfully. You can inspect a separate previously recorded repair.";
    $("live-events").replaceChildren(...(Array.isArray(snapshot.events) ? snapshot.events : []).slice(-6).map(event=>node("li",event.title || event.kind || "Recorded worker event")));
    $("live-metrics").hidden=!result;
    if(result) {
      const values=[["Final hidden checks",ratio(result.heldout_passed,result.heldout_total)],
        ["Accounted cost",numeric(result.cost_usd)?`$${result.cost_usd.toFixed(6)}`:"—"],
        ["Tokens",numeric(result.tokens)?result.tokens.toLocaleString("en-US"):"—"],
        ["New provider attempts",numeric(result.attempts)?String(result.attempts):"—"]];
      $("live-metrics").replaceChildren(...values.map(([label,value])=>{const item=node("div","");item.append(node("dt",label),node("dd",value));return item;}));
      $("live-availability").textContent="This is a newly requested demonstration, separate from all benchmark scores. Accounted costs may include retained uncertain reservations; missing usage stays unmeasured.";
      $("live-patch-section").hidden=typeof result.diff !== "string" || !result.diff;
      $("live-patch").textContent=result.diff || "";
    }
    $("live-refresh").hidden=terminal;
    if(terminal) stopPolling();
    return terminal;
  }
  async function poll() {
    if(!liveId) return;
    stopPolling();
    try {
      const snapshot=await request(`/runs/${encodeURIComponent(liveId)}`);
      if(snapshot.id !== liveId || snapshot.mode !== "live_curated" || snapshot.is_benchmark !== false) throw new Error("The live result could not be verified.");
      if(!show(snapshot) && Date.now()-observingSince < 320000) timer=setTimeout(poll,2000);
      else if(["queued","running"].includes(snapshot.status)) $("live-progress").textContent="Automatic status refresh paused. Refresh this same trial below; no additional inference is submitted.";
    } catch(error) {
      $("live-status").textContent="Status connection paused";
      $("live-progress").textContent=error.message;
      $("live-refresh").hidden=false;
    }
  }
  $("live-start").addEventListener("click",async()=>{
    if(liveId) return;
    $("live-start").disabled=true;
    $("live-status").textContent="Preparing one live request";
    try {
      const session=await request("/session",{method:"POST"});
      const result=await request("/runs",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":session.csrf},body:JSON.stringify({task_id:"binary_protocol-repair-1",policy:"cheap_only"})});
      if(typeof result.id !== "string" || !/^[a-f0-9]{32}$/.test(result.id)) throw new Error("The live-trial admission could not be confirmed.");
      liveId=result.id;remember(liveId);observingSince=Date.now();await poll();
    } catch(error) {
      $("live-status").textContent="Live request unavailable";
      $("live-progress").textContent=error.message;
      // No automatic retry of a potentially accepted POST. Server admission is
      // single-use and recorded replay is an explicit, separate action.
    }
  });
  $("live-refresh").addEventListener("click",()=>{observingSince=Date.now();poll();});
  $("live-recorded").addEventListener("click",()=>{
    const recorded=$("walkthrough-repair");
    if(recorded && !$("walkthrough-entry").hidden) recorded.click();
    else window.location.href=new URL("?version=v0.3-pilot1#explorer",base).href;
  });
  window.addEventListener("pagehide",stopPolling);
  try {const prior=sessionStorage.getItem("forgerl-curated-run");if(/^[a-f0-9]{32}$/.test(prior || ""))liveId=prior;} catch {}
  availability().then(()=>{if(liveId && !$("live-trial").hidden){observingSince=Date.now();poll();}});
})();
