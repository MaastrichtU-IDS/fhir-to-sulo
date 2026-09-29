#!/usr/bin/env node
/* merge.js <out.ttl> <in1.ttl> ... -- union of independently materialized
 * graphs.  Each materialization restarts its bnode counter at _:tm0, so the
 * labels collide on concatenation; bnode labels are document-scoped in RDF,
 * so relabelling per input is a no-op semantically and mandatory in practice. */
const FS=require("fs"), N3=require("n3");
const [out, ...ins]=process.argv.slice(2);
const all=[]; const DF=N3.DataFactory;
ins.forEach((f,i)=>{
  const qs=new N3.Parser({baseIRI:"urn:x:"}).parse(FS.readFileSync(f,"utf8"));
  const r=t=>t.termType==="BlankNode"?DF.blankNode("g"+i+"_"+t.value):t;
  qs.forEach(q=>all.push(DF.quad(r(q.subject),q.predicate,r(q.object))));
});
const w=new N3.Writer({prefixes:{}}); w.addQuads(all);
w.end((e,res)=>FS.writeFileSync(out,res));
console.log("merged "+ins.length+" graphs, "+all.length+" quads -> "+out);
