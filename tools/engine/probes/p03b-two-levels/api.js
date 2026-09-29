#!/usr/bin/env node
/* Does raising the search guards fix the TWO-LEVEL case?  (Probe 3b via API.) */
"use strict";
const FS=require("fs"), N3=require("n3");
const ShExUtil=require("@shexjs/util"), ShExParser=require("@shexjs/parser");
const Mapper=require("@shexjs/extension-map")({rdfjs:N3,Validator:{}});
const MapExt="http://shex.io/extensions/Map/#", H=__dirname+"/";
const target=ShExParser.construct("file://"+H+"target.shex",{},{index:true})
  .parse(FS.readFileSync(H+"target.shex","utf8"));
const b=ShExUtil.valToExtension(JSON.parse(FS.readFileSync(H+"out.val","utf8")),MapExt);
for (const [label,opts] of [["defaults",{}],
                            ["guards raised",{maxRepeat:1e6,maxAccepts:1e6,maxSteps:1e9,exploreSteps:1e9}]]) {
  const m=new Mapper.ThreadedMaterializer(target,opts);
  const q=m.materialize(b,"tag:out/root");
  const w=new N3.Writer({prefixes:{}}); w.addQuads(q);
  let ttl; w.end((e,r)=>{ttl=r;});
  FS.writeFileSync("/tmp/api-"+label.replace(/\W/g,"")+".ttl", ttl);
  console.log("### "+label+"  (alts="+m.lastReport.alternatives+")");
  console.log(require("child_process").execSync("node "+H+"report.js /tmp/api-"+label.replace(/\W/g,"")+".ttl").toString().trim().split("\n").map(l=>"  "+l).join("\n"));
}
console.log("### expected\n  one: [(100,60) (101,61)]\n  two: [(110,70) (111,71)]");
