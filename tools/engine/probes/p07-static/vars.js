#!/usr/bin/env node
/* vars.js <schema.shex> -- list the Map variables/codes a schema declares.
 * NOTE: this is OUR code.  The engine ships no equivalent static checker;
 * this exists to show what a host-side `shexmap-check` would have to do. */
const FS=require("fs"), ShExParser=require("@shexjs/parser");
const MapExt="http://shex.io/extensions/Map/#";
const f=process.argv[2];
const schema=ShExParser.construct("file://"+f,{},{index:true}).parse(FS.readFileSync(f,"utf8"));
const out=[];
(function walk(o){ if(o===null||typeof o!=="object") return;
  if(Array.isArray(o)) return o.forEach(walk);
  if(o.type==="TripleConstraint"&&o.semActs)
    o.semActs.filter(a=>a.name===MapExt).forEach(a=>out.push({predicate:o.predicate,code:a.code.trim()}));
  Object.values(o).forEach(walk); })(schema);
console.log(JSON.stringify(out,null,1));
