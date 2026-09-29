#!/usr/bin/env node
/* Probe 9: conformance against the ShExMap fixtures shipped in
 * @shexjs/extension-map/examples -- materialize each entry's stored bindings
 * against its target schema and compare (up to bnode isomorphism) with the
 * stored expected output. */
"use strict";
const FS = require("fs"), PATH = require("path"), N3 = require("n3");
const YAML = require("js-yaml");
const ShExParser = require("@shexjs/parser");
const Mapper = require("@shexjs/extension-map")({rdfjs: N3, Validator: {}});
const EX = "/w/node_modules/@shexjs/extension-map/examples/";
const manifest = YAML.safeLoad ? YAML.safeLoad(FS.readFileSync(EX + "manifest.yaml", "utf8"))
                               : YAML.load(FS.readFileSync(EX + "manifest.yaml", "utf8"));

/** canon - bnode-blind canonical form: iterative colour refinement. */
function canon (ttl) {
  const quads = new N3.Parser({baseIRI: "urn:x:"}).parse(ttl);
  const isB = t => t.termType === "BlankNode";
  let colour = new Map();
  const nodes = new Set();
  quads.forEach(q => [q.subject, q.object].forEach(t => { nodes.add(t.value + "|" + t.termType); }));
  for (const n of nodes) colour.set(n, n.endsWith("|BlankNode") ? "B" : n);
  for (let i = 0; i < 6; ++i) {
    const next = new Map();
    for (const n of nodes) {
      const out = quads.filter(q => (q.subject.value + "|" + q.subject.termType) === n)
        .map(q => "+" + q.predicate.value + ">" + colour.get(q.object.value + "|" + q.object.termType)).sort();
      const inn = quads.filter(q => (q.object.value + "|" + q.object.termType) === n)
        .map(q => "-" + q.predicate.value + "<" + colour.get(q.subject.value + "|" + q.subject.termType)).sort();
      next.set(n, colour.get(n) + "{" + out.join(",") + inn.join(",") + "}");
    }
    colour = next;
  }
  return quads.map(q => colour.get(q.subject.value + "|" + q.subject.termType) + " " + q.predicate.value
                      + " " + colour.get(q.object.value + "|" + q.object.termType)).sort().join("\n");
}

let pass = 0, fail = 0;
for (const e of manifest) {
  const name = e.schemaLabel + " / " + e.dataLabel;
  if (!e.expectedBindingsURL || !e.expectedOutputDataURL) { console.log("SKIP  " + name); continue; }
  const targetText = e.outputSchema || FS.readFileSync(EX + e.outputSchemaURL, "utf8");
  const bindings = JSON.parse(FS.readFileSync(EX + e.expectedBindingsURL, "utf8"));
  const expected = FS.readFileSync(EX + e.expectedOutputDataURL, "utf8");
  const root = (e.outputShapeMap || "").split("@")[0].replace(/^<|>$/g, "");
  const shapeLbl = (e.outputShapeMap || "").split("@")[1];
  const base = "file://" + EX + (e.outputSchemaURL || "inline.shex");
  let got, err = null;
  try {
    const schema = ShExParser.construct(base, {}, {index: true}).parse(targetText);
    const statics = {};
    for (const [k, v] of Object.entries(e.staticVars || {})) statics[k] = v;
    const m = new Mapper.ThreadedMaterializer(schema, {staticVars: statics});
    const lbl = shapeLbl && shapeLbl !== "START" ? shapeLbl.replace(/^<|>$/g, "") : undefined;
    const quads = m.materialize(bindings, root, lbl && (lbl.startsWith("http") ? lbl : base.replace(/[^/]*$/, "") + lbl));
    const w = new N3.Writer({prefixes: {}});
    w.addQuads(quads);
    got = await0(w);
  } catch (ex) { err = ex.message; }
  if (err) { console.log("ERROR " + name + ": " + err); fail++; continue; }
  const ok = canon(got) === canon(expected);
  console.log((ok ? "PASS  " : "FAIL  ") + name);
  if (!ok) {
    console.log("  ---- got ----\n" + got.split("\n").map(l => "  " + l).join("\n"));
    console.log("  ---- expected ----\n" + expected.split("\n").filter(l=>!/^\s*(#|PREFIX)/.test(l)).map(l => "  " + l).join("\n"));
  }
  ok ? pass++ : fail++;
}
console.log(`\nfixtures: ${pass} pass, ${fail} fail`);
function await0 (w) { let r; w.end((e, res) => { r = res; }); return r; }
