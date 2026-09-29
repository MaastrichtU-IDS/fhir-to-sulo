#!/usr/bin/env node
/* run-pass.js -- ONE materialization pass, driven through the programmatic API.
 *
 * CD-2 bans `shexmap-materialize`: it truncates every repetition to 19 items
 * (maxAccepts defaults to 20 and the CLI cannot set it), and it exits 0 both on
 * a fatal error and on a silently partial graph. This bridge is the supported
 * entry point. Every guard is set explicitly by the caller -- nothing inherits
 * an engine default, so a future default change cannot quietly alter output.
 *
 * Validation also runs through the API rather than `shex-validate`, which keeps
 * the whole pass to one process with no temp files (and so no bind mounts: see
 * the Dockerfile).
 *
 * stdin: {
 *   source: {schema, baseIRI?, data, dataBaseIRI?, node, shapeLabel?},
 *   target: {schema, baseIRI?, shapeLabel?},
 *   root: "<iri>", staticVars: {...},
 *   options: {maxAccepts, maxRepeat, maxSteps, exploreSteps, maxCallDepth}
 * }
 * stdout: see `emit` calls below; always JSON, always with an `ok` flag.
 */
"use strict";
const N3 = require("n3");
const ShExParser = require("@shexjs/parser");
const ShExTerm = require("@shexjs/term");
const ShExUtil = require("@shexjs/util");
const {ShExValidator, resultMapToShapeExprTest} = require("@shexjs/validator");
const {rdfjsDB} = require("@shexjs/neighborhood-rdfjs");
const MapModule = require("@shexjs/extension-map")({rdfjs: N3, Validator: ShExValidator});

const MAP_EXT = "http://shex.io/extensions/Map/#";
const REQUIRED_OPTIONS = ["maxAccepts", "maxRepeat", "maxSteps", "exploreSteps", "maxCallDepth"];

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => { raw += c; });
process.stdin.on("end", () => { try { main(JSON.parse(raw)); } catch (e) { crash(e); } });

function main (req) {
  for (const k of REQUIRED_OPTIONS)
    if (typeof (req.options || {})[k] !== "number")
      return emit({ok: false, stage: "request", error:
        `option ${k} must be set explicitly (CD-2: no engine default may be inherited)`});

  // ---- parse both schemas ------------------------------------------------
  let sourceSchema, targetSchema, targetPrefixes;
  try {
    sourceSchema = ShExParser
      .construct(req.source.baseIRI || "urn:fhir-sulo:source", {}, {index: true})
      .parse(req.source.schema);
  } catch (e) { return emit({ok: false, stage: "parse-source", error: e.message}); }
  try {
    const p = ShExParser.construct(req.target.baseIRI || "urn:fhir-sulo:target", {}, {index: true});
    targetSchema = p.parse(req.target.schema);
    targetPrefixes = targetSchema._prefixes || {};
  } catch (e) { return emit({ok: false, stage: "parse-target", error: e.message}); }

  // Number every TripleConstraint in the target schema. The driver asserts
  // that each emitted quad names one of these, which is the mechanical form of
  // "the host emits no triple of its own" (DR-302).
  const {ids: tcIds, table: constraintTable} = indexConstraints(targetSchema);

  // ---- validate the source graph and lift the bindings -------------------
  let bindings, validation;
  try {
    const store = new N3.Store();
    store.addQuads(new N3.Parser({baseIRI: req.source.dataBaseIRI || "urn:fhir-sulo:data"})
                   .parse(req.source.data));
    const validator = new ShExValidator(sourceSchema, rdfjsDB(store), {results: "api"});
    MapModule.register(validator, {ShExTerm});
    const shape = req.source.shapeLabel || ShExValidator.Start;
    validation = resultMapToShapeExprTest(
      validator.validateShapeMap([{node: req.source.node, shape}]));
    if (validation.type === "Failure" || validation.type === "FailureList")
      return emit({ok: false, stage: "validate", validation});
    bindings = ShExUtil.valToExtension(validation, MAP_EXT);
  } catch (e) { return emit({ok: false, stage: "validate", error: e.message}); }

  // ---- materialize -------------------------------------------------------
  const materializer = new MapModule.ThreadedMaterializer(targetSchema, {
    staticVars: req.staticVars || {},
    maxAccepts: req.options.maxAccepts,
    maxRepeat: req.options.maxRepeat,
    maxSteps: req.options.maxSteps,
    exploreSteps: req.options.exploreSteps,
    maxCallDepth: req.options.maxCallDepth,
  });
  let quads;
  try {
    quads = materializer.materialize(bindings, req.root, req.target.shapeLabel || undefined);
  } catch (e) {
    return emit({ok: false, stage: "materialize", error: e.message,
                 report: cleanReport(e.report), bindings,
                 frames: materializer.frames || null});
  }

  const origins = originIndex(materializer.frames || [], materializer.frameOrigins || []);
  const chosen = materializer.chosen || null;
  emit({
    ok: true,
    bindings,
    frames: materializer.frames || [],
    frameOrigins: materializer.frameOrigins || [],
    quads: quads.map(termsOf),
    provenance: (materializer.provenance || []).map((p, i) => ({
      quadIndex: i,
      predicate: p.predicate,
      constraintId: tcIds.get(p.tc) || null,
      kind: p.src && p.src.constant ? "constant"
          : p.src && p.src.structural ? "structural"
          : p.src && p.src.statics ? "static"
          : "binding",
      variables: (p.src && p.src.variables) || [],
      frame: p.src && typeof p.src.frame === "number" ? p.src.frame : null,
    })),
    constraints: constraintTable,
    lastReport: cleanReport(materializer.lastReport),
    accepts: (materializer.accepts || []).map((a) => ({
      consumed: a.consumed, skipped: a.skipped, quads: a.quads.length,
    })),
    coverage: coverageOf(origins, chosen),
  });
}

/** Walk the target schema and give every TripleConstraint a stable id.
 *  Identity is by object, because that is what `provenance[].tc` carries. */
function indexConstraints (schema) {
  const ids = new Map();
  const table = [];
  const seen = new Set();
  let n = 0;
  (function walk (node, shapeId) {
    if (node === null || typeof node !== "object" || seen.has(node)) return;
    seen.add(node);
    if (Array.isArray(node)) return node.forEach((x) => walk(x, shapeId));
    if (node.type === "ShapeDecl" && node.id) shapeId = node.id;
    if (node.type === "TripleConstraint") {
      const id = "tc:" + (n++);
      ids.set(node, id);
      table.push({id, predicate: node.predicate, shape: shapeId,
                  inverse: node.inverse === true,
                  mapCodes: (node.semActs || [])
                    .filter((a) => a.name === MAP_EXT).map((a) => a.code)});
    }
    for (const k of Object.keys(node)) if (!k.startsWith("_")) walk(node[k], shapeId);
  })(schema, null);
  return {ids, table};
}

/** RDF/JS term -> a shape Python can relabel and serialize without re-parsing
 *  Turtle. Blank nodes must survive as blank nodes across the union step. */
function termsOf (q) {
  return {s: term(q.subject), p: term(q.predicate), o: term(q.object)};
}
function term (t) {
  if (t.termType === "BlankNode") return {t: "bnode", v: t.value};
  if (t.termType === "Literal") {
    const out = {t: "literal", v: t.value};
    if (t.language) out.lang = t.language;
    else if (t.datatype && t.datatype.value) out.dt = t.datatype.value;
    return out;
  }
  return {t: "iri", v: t.value};
}

/** Distinct source bindings, keyed by their path in the ORIGINAL binding tree.
 *
 *  Raw frame-binding counts cannot answer "were all bindings consumed?":
 *  normalizeBindingTree distributes a variable that occurs once above a
 *  repetition into every frame below it, so a patient name appears N times and
 *  is consumed once. Collapsing on the origin path removes the duplicates. */
function originIndex (frames, frameOrigins) {
  const all = new Map(); // "frameIdx varName" -> origin key
  const distinct = new Set();
  frames.forEach((frame, i) => {
    Object.keys(frame).forEach((v) => {
      const path = (frameOrigins[i] || {})[v];
      const key = JSON.stringify(path !== undefined ? path : [i, v]);
      all.set(i + " " + v, key);
      distinct.add(key);
    });
  });
  return {all, distinct};
}

function coverageOf (origins, chosen) {
  const total = [...origins.distinct].sort();
  if (!chosen || !chosen.used)
    return {total: total.length, consumed: 0, unconsumed: total, chosenAvailable: false};
  const consumed = new Set();
  for (const k of chosen.used) {
    const o = origins.all.get(k);
    if (o !== undefined) consumed.add(o);
  }
  return {
    total: total.length,
    consumed: consumed.size,
    unconsumed: total.filter((k) => !consumed.has(k)),
    chosenAvailable: true,
  };
}

/** lastReport carries whole TripleConstraint objects; keep the diagnosis,
 *  drop the payload, so the response stays readable in a failure log. */
function cleanReport (r) {
  if (!r) return null;
  return {
    unboundVariables: (r.unboundVariables || []).map((f) => ({
      variable: f.variable || null, predicate: f.predicate || null,
      code: f.code || null, error: f.error || null,
    })),
    unusedStatics: r.unusedStatics || [],
    alternatives: r.alternatives || 0,
    explorationTruncated: r.explorationTruncated === true,
    configsPruned: r.configsPruned || 0,
  };
}

/** emit exactly once.
 *
 * If serialising a success response threw, the outer catch would call crash()
 * and a second JSON document would be appended to the first. The driver parses
 * stdout, so two documents is not a failure it can report -- it is a parse
 * error that hides whatever actually went wrong. */
let emitted = false;
function emit (obj) {
  if (emitted) {
    process.stderr.write("bridge tried to respond twice: "
                         + JSON.stringify(obj).slice(0, 500) + "\n");
    return;
  }
  let body;
  try {
    body = JSON.stringify(obj);
  } catch (e) {
    emitted = true;
    process.stdout.write(JSON.stringify(
      {ok: false, stage: "bridge", error: "response is not serialisable: " + e.message}));
    process.exitCode = 1;
    return;
  }
  emitted = true;
  process.stdout.write(body);
  process.exitCode = obj.ok ? 0 : 1;
}
function crash (e) {
  emit({ok: false, stage: "bridge", error: e && e.stack ? e.stack : String(e)});
}
