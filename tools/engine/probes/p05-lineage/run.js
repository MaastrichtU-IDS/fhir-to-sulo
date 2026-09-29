#!/usr/bin/env node
/* Probe 5/7/8 (API): per-quad lineage, static-ish diagnostics, error shape.
 * Uses the programmatic API rather than the CLI, because bin/materialize
 * throws away materializer.provenance and materializer.lastReport. */
"use strict";
const FS = require("fs"), N3 = require("n3");
const ShExUtil = require("@shexjs/util");
const ShExParser = require("@shexjs/parser");
const Mapper = require("@shexjs/extension-map")({rdfjs: N3, Validator: {}});
const MapExt = "http://shex.io/extensions/Map/#";
const here = __dirname + "/";

function parse (f) {
  return ShExParser.construct("file://" + f, {}, {index: true})
    .parse(FS.readFileSync(f, "utf8"));
}
const bindings = ShExUtil.valToExtension(
  JSON.parse(FS.readFileSync(here + "../p03-iteration/outA.val", "utf8")), MapExt);

function run (label, targetFile, opts) {
  console.log("\n===== " + label + " =====");
  const schema = parse(targetFile);
  const m = new Mapper.ThreadedMaterializer(schema, opts || {});
  let quads;
  try {
    quads = m.materialize(bindings, "tag:out/root");
  } catch (e) {
    console.log("THREW " + e.constructor.name + ": " + e.message);
    console.log("error.report = " + JSON.stringify(e.report, null, 1));
    return;
  }
  console.log("-- frames (normalized binding tape) --");
  console.log(JSON.stringify(m.frames));
  console.log("-- frameOrigins (path back into the binding tree) --");
  console.log(JSON.stringify(m.frameOrigins));
  console.log("-- quads + provenance --");
  m.provenance.forEach(p => {
    const q = p.quad;
    console.log("  " + q.subject.value + " | " + q.predicate.value + " | " + q.object.value
                + "\n      src=" + JSON.stringify(p.src)
                + "  tcPredicate=" + p.tc.predicate);
  });
  console.log("-- lastReport --");
  console.log(JSON.stringify(Object.assign({}, m.lastReport, {
    unboundVariables: (m.lastReport.unboundVariables || [])
      .map(f => ({variable: f.variable, predicate: f.predicate, code: f.code, error: f.error}))
  }), null, 1));
  console.log("-- accepts (alternative materializations) = " + m.accepts.length);
}

run("5: lineage for a good target", here + "../p03-iteration/target.shex");
run("7: target referencing a variable the source never binds", here + "target-typo.shex");
run("8a: target with an unknown Map function id()", here + "../p04-identity/target-id.shex");
run("8b: target requiring an unbindable variable at top level", here + "target-hard-fail.shex");
