#!/usr/bin/env node
/* report.js <ttl> -- prints reportNo -> [(sys,dia)...] grouping for probe 3b */
const FS=require("fs"), N3=require("n3"), T="http://target.example/";
const qs=new N3.Parser({baseIRI:"urn:x:"}).parse(FS.readFileSync(process.argv[2],"utf8"));
const o={}; for(const q of qs){const s=q.subject.value;(o[s]=o[s]||{})[q.predicate.value]=(o[s][q.predicate.value]||[]).concat([q.object.value]);}
const out=[];
for(const s in o){ if(!(T+"no" in o[s])) continue;
  const panels=(o[s][T+"panel"]||[]).map(p=>`(${(o[p]||{})[T+"systolic"]},${(o[p]||{})[T+"diastolic"]})`).sort();
  out.push(`${o[s][T+"no"]}: [${panels.join(" ")}]`); }
console.log(out.sort().join("\n") || "(no reports emitted)");
