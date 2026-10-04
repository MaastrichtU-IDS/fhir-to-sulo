#!/usr/bin/env node
/* pairs.js <ttl-file> <predA> <predB>
 * Parses a Turtle graph and prints, one per line, the sorted set of
 * (predA-object, predB-object) pairs grouped by their common subject.
 * Used to test whether ShExMap preserves within-group association. */
const FS = require("fs"), N3 = require("n3");
const [file, pa, pb] = process.argv.slice(2);
const quads = new N3.Parser({baseIRI: "urn:x:"}).parse(FS.readFileSync(file, "utf8"));
const bySubj = new Map();
for (const q of quads) {
  const s = q.subject.value;
  if (!bySubj.has(s)) bySubj.set(s, {});
  if (q.predicate.value === pa) bySubj.get(s).a = q.object.value;
  if (q.predicate.value === pb) bySubj.get(s).b = q.object.value;
}
const pairs = [...bySubj.values()].filter(o => o.a !== undefined || o.b !== undefined)
  .map(o => `(${o.a ?? "MISSING"},${o.b ?? "MISSING"})`).sort();
console.log(pairs.join(" "));
