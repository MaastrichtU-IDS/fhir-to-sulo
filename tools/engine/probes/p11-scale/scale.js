#!/usr/bin/env node
/* Probe 11 (API): how many repetitions survive, and do the options fix it? */
"use strict";
const FS=require("fs"), N3=require("n3"), CP=require("child_process");
const ShExUtil=require("@shexjs/util"), ShExParser=require("@shexjs/parser");
const Mapper=require("@shexjs/extension-map")({rdfjs:N3, Validator:{}});
const MapExt="http://shex.io/extensions/Map/#";
const S="/w/probes/p03-iteration/";
const target=ShExParser.construct("file://"+S+"target.shex",{},{index:true})
  .parse(FS.readFileSync(S+"target.shex","utf8"));

function gen(n){
  const L=["PREFIX : <http://ex.example/>",
    '<http://ex.example/P> :name "Sue" ; :panel '+Array.from({length:n},(_,i)=>`<http://ex.example/p${i}>`).join(", ")+" ."];
  for(let i=0;i<n;i++) L.push(`<http://ex.example/p${i}> :sys ${100+i} ; :dia ${60+i} .`);
  FS.writeFileSync("/tmp/d.ttl", L.join("\n")+"\n");
}
function bindingsFor(n){
  gen(n);
  const val=CP.execSync(`/w/node_modules/.bin/shex-validate -x ${S}source.shex -d /tmp/d.ttl -m '<http://ex.example/P>@START' --extension @shexjs/extension-map`,{maxBuffer:1e9}).toString();
  return ShExUtil.valToExtension(JSON.parse(val), MapExt);
}
function tryN(n, opts, label){
  const b=bindingsFor(n);
  const t0=Date.now();
  const m=new Mapper.ThreadedMaterializer(target, opts||{});
  let quads; try { quads=m.materialize(b,"tag:out/root"); } catch(e){ console.log(`  n=${n} ${label}: THREW ${e.message.slice(0,80)}`); return; }
  const panels=quads.filter(q=>q.predicate.value==="http://target.example/panel").length;
  const ms=Date.now()-t0;
  console.log(`  n=${String(n).padStart(4)} ${label.padEnd(34)} panels=${String(panels).padStart(4)}/${n}`
    +` truncated=${m.lastReport.explorationTruncated} alts=${m.lastReport.alternatives} ${ms}ms`);
}
console.log("### default options -- where does silent truncation start?");
for (const n of [2,5,10,15,20,25,30,40,50,60,100]) tryN(n, {}, "defaults");
console.log("\n### can the documented guards be raised to fix it?");
for (const o of [
  ["maxRepeat 1000",                       {maxRepeat:1000}],
  ["exploreSteps 1e7",                     {exploreSteps:1e7}],
  ["maxRepeat+exploreSteps+maxSteps",      {maxRepeat:1000, exploreSteps:1e7, maxSteps:1e8}],
  ["...+maxAccepts 1",                     {maxRepeat:1000, exploreSteps:1e7, maxSteps:1e8, maxAccepts:1}],
]) for (const n of [60,200]) tryN(n, o[1], o[0]);

console.log("\n### maxAccepts is the real cap (default 20)");
for (const n of [60,200,500]) tryN(n, {maxRepeat:1000, maxAccepts:n+5, maxSteps:1e8, exploreSteps:1e8}, "maxAccepts>n");
