#!/usr/bin/env node
/* Probe 11b: does the "perfect accept" short circuit ever fire, and how does
 * the fixed configuration scale? */
"use strict";
const FS=require("fs"), N3=require("n3"), CP=require("child_process");
const ShExUtil=require("@shexjs/util"), ShExParser=require("@shexjs/parser");
const Mapper=require("@shexjs/extension-map")({rdfjs:N3, Validator:{}});
const MapExt="http://shex.io/extensions/Map/#", S="/w/probes/p03-iteration/";
FS.writeFileSync("/tmp/t-nopatient.shex", `
PREFIX t: <http://target.example/>
PREFIX v: <http://ex.example/var#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX Map: <http://shex.io/extensions/Map/#>
start = @<Coll>
<Coll> { t:panel @<TPanel>* }
<TPanel> { t:systolic xsd:integer %Map:{ v:sys %}; t:diastolic xsd:integer %Map:{ v:dia %} }
`);
const targets = {
  "with a shared outer var": [S+"target.shex", FS.readFileSync(S+"target.shex","utf8")],
  "no shared outer var":     ["/tmp/t-nopatient.shex", FS.readFileSync("/tmp/t-nopatient.shex","utf8")],
};
function bindingsFor(n){
  const L=["PREFIX : <http://ex.example/>",
    '<http://ex.example/P> :name "Sue" ; :panel '+Array.from({length:n},(_,i)=>`<http://ex.example/p${i}>`).join(", ")+" ."];
  for(let i=0;i<n;i++) L.push(`<http://ex.example/p${i}> :sys ${100+i} ; :dia ${60+i} .`);
  FS.writeFileSync("/tmp/d.ttl", L.join("\n")+"\n");
  const val=CP.execSync(`/w/node_modules/.bin/shex-validate -x ${S}source.shex -d /tmp/d.ttl -m '<http://ex.example/P>@START' --extension @shexjs/extension-map`,{maxBuffer:1e9}).toString();
  return ShExUtil.valToExtension(JSON.parse(val), MapExt);
}
for (const [label,[f,txt]] of Object.entries(targets)) {
  const target=ShExParser.construct("file://"+f,{},{index:true}).parse(txt);
  console.log("\n### "+label);
  for (const n of [20,100]) {
    const b=bindingsFor(n);
    const m=new Mapper.ThreadedMaterializer(target,{});
    const q=m.materialize(b,"tag:out/root");
    console.log(`  DEFAULT options   n=${n}: panels=${q.filter(x=>x.predicate.value==="http://target.example/panel").length}/${n} alts=${m.lastReport.alternatives}`);
  }
}
console.log("\n### fixed configuration (maxAccepts raised), scaling");
const target=ShExParser.construct("file://"+S+"target.shex",{},{index:true}).parse(FS.readFileSync(S+"target.shex","utf8"));
for (const n of [100,500,1000,2000]) {
  const b=bindingsFor(n); const t0=Date.now();
  const m=new Mapper.ThreadedMaterializer(target,{maxRepeat:1e6,maxAccepts:1e6,maxSteps:1e9,exploreSteps:1e9});
  const q=m.materialize(b,"tag:out/root");
  console.log(`  n=${String(n).padStart(4)} panels=${q.filter(x=>x.predicate.value==="http://target.example/panel").length}/${n}  ${Date.now()-t0}ms`);
}
