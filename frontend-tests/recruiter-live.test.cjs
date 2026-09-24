const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {JSDOM}=require("jsdom");
const html=fs.readFileSync(path.join(__dirname,"../static/bench.html"),"utf8");
const script=fs.readFileSync(path.join(__dirname,"../static/recruiter-live.js"),"utf8");
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
const reply=(body,status=200)=>({ok:status>=200&&status<300,status,json:async()=>body});
function page(handler){
  const calls=[];
  const dom=new JSDOM(html,{url:"https://forge.stelioszach.com/",runScripts:"outside-only",pretendToBeVisual:true});
  dom.window.fetch=async(url,options)=>{calls.push({url,options});return handler(new URL(url).pathname,options);};
  dom.window.eval(script);
  return {dom,d:dom.window.document,calls};
}
test("default recorded mode makes no session or model admission request",async()=>{
  const {dom,d,calls}=page(()=>reply({available:false,reason:"recorded_only"}));
  try{await settle();assert.equal(d.getElementById("live-trial").hidden,true);assert.equal(calls.length,1);assert.equal(calls[0].options.method,"GET");}finally{dom.window.close();}
});
test("fresh trial requires explicit click and preserves actual failure without fake replacement",async()=>{
  const id="a".repeat(32);
  const {dom,d,calls}=page((route,options)=>{
    if(route.endsWith("/state"))return reply({available:true,message:"One fixed live trial."});
    if(route.endsWith("/session"))return reply({csrf:"fixture-csrf"});
    if(route.endsWith("/runs")){assert.equal(options.headers["X-CSRF-Token"],"fixture-csrf");assert.deepEqual(JSON.parse(options.body),{task_id:"binary_protocol-repair-1",policy:"cheap_only"});return reply({id},202);}
    return reply({id,mode:"live_curated",is_benchmark:false,status:"failed",events:[{title:"Provider request failed"}],result:{status:"failed",solved:false,cost_usd:0.001,tokens:null,attempts:1,heldout_passed:null,heldout_total:5,diff:"<script>unsafe()</script>"}});
  });
  try{
    await settle();assert.equal(calls.length,1);assert.equal(d.getElementById("live-start").disabled,false);
    d.getElementById("live-start").click();await settle();
    assert.equal(calls.filter(c=>c.options.method==="POST").length,2);
    assert.match(d.getElementById("live-status").textContent,/failed/);
    assert.match(d.getElementById("live-progress").textContent,/separate previously recorded/);
    assert.ok(d.getElementById("live-metrics").textContent.includes("—"));
    assert.equal(d.getElementById("live-patch").textContent,"<script>unsafe()</script>");
    assert.equal(d.getElementById("live-patch").querySelector("script"),null);
  }finally{dom.window.close();}
});
test("failed admission never automatically retries a possibly accepted POST",async()=>{
  const {dom,d,calls}=page(route=>route.endsWith("/state")?reply({available:true}):route.endsWith("/session")?reply({csrf:"fixture"}):reply({detail:{message:"Connection paused."}},503));
  try{await settle();d.getElementById("live-start").click();await settle();assert.equal(calls.filter(c=>c.url.endsWith("/runs")).length,1);assert.equal(d.getElementById("live-start").disabled,true);assert.match(d.getElementById("live-progress").textContent,/Connection paused/);}finally{dom.window.close();}
});
