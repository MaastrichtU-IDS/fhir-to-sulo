/* common.js -- the parts of a ShExMap job that both bridges need.
 *
 * `run-pass.js` runs one validate-and-materialize pass, which is the shape the
 * driver's recorded regression fixtures are written against.  `run-map.js`
 * validates once and materializes many passes, which is how the maps in
 * `maps/r4/` actually run: the engine has no id(), so every IRI-identified
 * target node is the root of its own pass (DR-301 4b/4c, DR-302), and the
 * blood-pressure map has ten of them over one source binding.
 *
 * Validating ten times to materialize ten passes would be ten times the work
 * for one answer, so the multi-pass bridge exists; everything below is what
 * the two have in common, kept in one place so they cannot drift.
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

function parseSchema (text, baseIRI) {
  return ShExParser.construct(baseIRI, {}, {index: true}).parse(text);
}

/** Validate the source graph and lift the ShExMap bindings out of the result. */
function bindSource (spec) {
  const schema = parseSchema(spec.schema, spec.baseIRI || "urn:fhir-sulo:source");
  const store = new N3.Store();
  store.addQuads(new N3.Parser({baseIRI: spec.dataBaseIRI || "urn:fhir-sulo:data"})
                 .parse(spec.data));
  const validator = new ShExValidator(schema, rdfjsDB(store), {results: "api"});
  MapModule.register(validator, {ShExTerm});
  const shape = spec.shapeLabel || ShExValidator.Start;
  const validation = resultMapToShapeExprTest(
    validator.validateShapeMap([{node: spec.node, shape}]));
  if (validation.type === "Failure" || validation.type === "FailureList")
    return {ok: false, validation};
  return {ok: true, validation, bindings: ShExUtil.valToExtension(validation, MAP_EXT)};
}

/** Number every TripleConstraint in a target schema.
 *
 *  The driver asserts that each emitted quad names one of these, which is the
 *  mechanical form of "the host emits no triple of its own" (DR-302). Identity
 *  is by object, because that is what `provenance[].tc` carries. */
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
 *  normalizeBindingTree distributes a variable that sits above a repetition
 *  into every frame below it, so a patient name appears N times and is
 *  consumed once. Collapsing on the origin path removes the duplicates. */
function originIndex (frames, frameOrigins) {
  const all = new Map();
  const distinct = new Set();
  const names = new Map(); // origin key -> the variable it binds
  frames.forEach((frame, i) => {
    Object.keys(frame).forEach((v) => {
      const path = (frameOrigins[i] || {})[v];
      const key = JSON.stringify(path !== undefined ? path : [i, v]);
      all.set(i + " " + v, key);
      distinct.add(key);
      names.set(key, v);
    });
  });
  return {all, distinct, names};
}

function coverageOf (origins, chosen) {
  const total = [...origins.distinct].sort();
  const named = (keys) =>
    [...new Set(keys.map((k) => origins.names.get(k)).filter(Boolean))].sort();
  if (!chosen || !chosen.used)
    return {total: total.length, consumed: 0, unconsumed: total,
            unconsumedVariables: named(total), chosenAvailable: false};
  const consumed = new Set();
  for (const k of chosen.used) {
    const o = origins.all.get(k);
    if (o !== undefined) consumed.add(o);
  }
  const left = total.filter((k) => !consumed.has(k));
  return {
    total: total.length,
    consumed: consumed.size,
    unconsumed: left,
    // the variable names behind `unconsumed`. A caller cannot tell a dropped
    // value from a host-consumed one (a node-key input, an identity service
    // input, an eligibility guard) without knowing which variable it was.
    unconsumedVariables: named(left),
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

function provenanceOf (materializer, tcIds) {
  return (materializer.provenance || []).map((p, i) => ({
    quadIndex: i,
    predicate: p.predicate,
    constraintId: tcIds.get(p.tc) || null,
    kind: p.src && p.src.constant ? "constant"
        : p.src && p.src.structural ? "structural"
        : p.src && p.src.statics ? "static"
        : "binding",
    variables: (p.src && p.src.variables) || [],
    frame: p.src && typeof p.src.frame === "number" ? p.src.frame : null,
  }));
}

/** Every guard must be set by the caller. CD-2: nothing inherits an engine
 *  default, so a change to one cannot quietly change our output. */
function checkOptions (options) {
  for (const k of REQUIRED_OPTIONS)
    if (typeof (options || {})[k] !== "number")
      return `option ${k} must be set explicitly (CD-2: no engine default may be inherited)`;
  return null;
}

function materializerFor (schema, staticVars, options) {
  return new MapModule.ThreadedMaterializer(schema, {
    staticVars: staticVars || {},
    maxAccepts: options.maxAccepts,
    maxRepeat: options.maxRepeat,
    maxSteps: options.maxSteps,
    exploreSteps: options.exploreSteps,
    maxCallDepth: options.maxCallDepth,
  });
}

/** Emit exactly once.
 *
 *  If serialising a success response threw, the outer catch would call crash()
 *  and a second JSON document would be appended to the first. The driver
 *  parses stdout, so two documents is not a failure it can report -- it is a
 *  parse error that hides whatever actually went wrong. */
function emitter () {
  let emitted = false;
  return function emit (obj) {
    if (emitted) {
      process.stderr.write("bridge tried to respond twice\n");
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
  };
}

function readRequest (handle) {
  let raw = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (c) => { raw += c; });
  process.stdin.on("end", () => handle(raw));
}

module.exports = {
  MAP_EXT, REQUIRED_OPTIONS, MapModule,
  parseSchema, bindSource, indexConstraints, termsOf, term,
  originIndex, coverageOf, cleanReport, provenanceOf,
  checkOptions, materializerFor, emitter, readRequest,
};
