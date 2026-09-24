const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const root = path.join(__dirname, "..");
const pilot = path.join(root, "artifacts/forgebench/v0.3-pilot1");
const benchmark = JSON.parse(fs.readFileSync(path.join(pilot, "explorer/benchmark.json")));
const catalog = JSON.parse(fs.readFileSync(path.join(pilot, "explorer/tasks.json")));
const script = fs.readFileSync(path.join(root, "static/bench.js"), "utf8");
const html = fs.readFileSync(path.join(root, "static/bench.html"), "utf8");
const response = (body) => ({ ok: true, status: 200, json: async () => body });
const settle = async () => { for (let i = 0; i < 18; i++) await new Promise(resolve => setImmediate(resolve)); };

test("share preview exists in static HTML with accurate scope and the existing logo", () => {
  const dom = new JSDOM(html);
  try {
    const d = dom.window.document;
    assert.equal(d.querySelector('link[rel="canonical"]').href, 'https://forge.stelioszach.com/');
    assert.equal(d.querySelector('meta[property="og:url"]').content, 'https://forge.stelioszach.com/');
    assert.equal(d.querySelector('meta[property="og:type"]').content, 'website');
    assert.match(d.querySelector('meta[property="og:description"]').content, /162 recorded.*separate, capped live trial/);
    assert.equal(d.querySelector('meta[property="og:image"]').content, 'https://forge.stelioszach.com/assets/personal-logo.png');
    assert.equal(d.querySelector('meta[name="twitter:card"]').content, 'summary');
  } finally { dom.window.close(); }
});

function page() {
  const calls = [];
  const dom = new JSDOM(html, { url: "https://forge.stelioszach.com/", runScripts: "outside-only", pretendToBeVisual: true });
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  dom.window.fetch = async (url, options) => {
    calls.push({ url, options });
    const route = new URL(url).pathname;
    const prefix = "/api/forgebench/versions/v0.3-pilot1";
    if (route === prefix) return response(benchmark);
    if (route === prefix + "/tasks") return response(catalog);
    if (route.startsWith(prefix + "/tasks/")) return response(catalog.tasks.find(t => t.id === route.split("/").at(-1)));
    if (route.startsWith(prefix + "/runs/")) {
      const run = JSON.parse(fs.readFileSync(path.join(pilot, "study/runs", route.split("/").at(-1) + ".json")));
      // Existing evidence supplies a final-candidate verification event. The API
      // binds it by source hash; this browser test exercises rendering only.
      run.explorer = { final_verification_event_seq: run.events.filter(e => e.kind === "tests" && e.data.visibility === "public_supplemental").at(-1)?.seq };
      return response(run);
    }
    if (route === "/api/forgebench") return response({ version: "0.2", status: "not_run", runs: [], summary: [], coverage: {completed: 0, planned: 0} });
    if (route === "/api/forgebench/tasks") return response({tasks: []});
    throw new Error(`Unexpected request ${route}`);
  };
  dom.window.eval(script);
  return { dom, d: dom.window.document, calls };
}

test("latest native pilot defaults to six actual policies and separate comparison samples", async () => {
  const {dom,d,calls}=page();
  try {
    await settle();
    assert.equal(d.getElementById("study-select").value,"v0.3-pilot1");
    assert.equal(d.getElementById("episode-count").textContent,"162");
    assert.match(d.getElementById("result-artifact").href,/versions\/v0\.3-pilot1$/);
    assert.doesNotMatch(d.getElementById("coverage-copy").textContent,/0 training/);
    assert.equal(d.querySelectorAll("#policy-table tr").length,6);
    assert.match(d.getElementById("comparison-title").textContent,/Six policies.*Primary/);
    assert.ok(d.getElementById("policy-table").textContent.includes("Supervised return"));
    d.getElementById("comparison-split").value="external";
    d.getElementById("comparison-split").dispatchEvent(new dom.window.Event("change"));
    assert.match(d.getElementById("comparison-title").textContent,/Source-derived/);
    assert.ok([...d.querySelectorAll("#policy-table tr")].every(row=>row.children[1].textContent==="3"));
    assert.ok(calls.every(call=>call.options.method==="GET"));
  } finally {dom.window.close();}
});

test("guided verification miss keeps final failure and shows three distinct check stages", async () => {
  const {dom,d}=page();
  try {
    await settle(); d.getElementById("walkthrough-miss").click(); await settle();
    assert.equal(d.getElementById("run-select").value,benchmark.walkthroughs.verification_miss.run_id);
    assert.equal(d.getElementById("run-status").textContent,"Not solved");
    assert.match(d.getElementById("run-context").textContent,/final hidden grader found a failure/);
    assert.equal(d.querySelectorAll("#run-tests .test-group").length,3);
    assert.match(d.getElementById("run-tests").textContent,/Supplemental public VERIFY/);
    assert.equal(d.getElementById("tab-tests").getAttribute("aria-selected"),"true");
  } finally {dom.window.close();}
});

test("recorded replay reveals actual events without an inference request and can show all again", async () => {
  const {dom,d,calls}=page();
  try {
    await settle(); const requests=calls.length;
    const total=d.querySelectorAll("#trajectory .trace-event").length;
    assert.ok(total>5);
    d.getElementById("replay-next").click();
    assert.equal([...d.querySelectorAll("#trajectory .trace-event")].filter(e=>!e.hidden).length,1);
    assert.match(d.getElementById("replay-status").textContent,/No inference is running/);
    d.getElementById("replay-next").click();
    assert.equal([...d.querySelectorAll("#trajectory .trace-event")].filter(e=>!e.hidden).length,2);
    d.getElementById("replay-all").click();
    assert.equal([...d.querySelectorAll("#trajectory .trace-event")].filter(e=>!e.hidden).length,total);
    assert.equal(calls.length,requests);
  } finally {dom.window.close();}
});

test("version switch cancels playback and preserves a separate v0.2 view", async () => {
  const {dom,d,calls}=page();
  try {
    await settle(); d.getElementById("replay-play").click();
    d.getElementById("study-select").value="v0.2";
    d.getElementById("study-select").dispatchEvent(new dom.window.Event("change")); await settle();
    assert.equal(d.querySelectorAll("#policy-table tr").length,5);
    assert.equal(d.getElementById("walkthrough-entry").hidden,true);
    assert.equal(d.getElementById("comparison-split-control").hidden,true);
    assert.match(d.getElementById("comparison-title").textContent,/Five policies/);
    assert.match(d.getElementById("result-artifact").href,/\/api\/forgebench$/);
    assert.ok(calls.every(call=>call.options.method==="GET"));
  } finally {dom.window.close();}
});
