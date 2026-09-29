#!/usr/bin/env node
/* server.js -- the pinned engine as a resident process.
 *
 * WHY: the Gate 4 benchmark measured `materialize` at 0.472 s per resource, of
 * which 0.339 s -- 72% -- was `docker run` start-up, paid twice per resource
 * (bind, then materialize). Actual materialization is 0.030 ms. We were paying
 * four orders of magnitude more to start a container than to do the work.
 *
 * WHAT CHANGES, AND WHAT DOES NOT: the transport is identical to the one-shot
 * bridges -- JSON in on stdin, JSON out on stdout, nothing bind-mounted. It is
 * the same `docker run --rm -i`; it just is not closed after one request.
 * That matters, because the no-bind-mount rule was a deliberate response to
 * the colima trap (DR-301: an unshared bind mount silently yields an EMPTY
 * directory), and because a *named* long-lived container would reintroduce
 * exactly the shared-mutable-state class of bug behind CD-5. This container
 * has no name, is owned by one host process, and dies when that process's
 * stdin closes.
 *
 * Framing: one JSON request per line in, one JSON response per line out.
 * `JSON.stringify` never emits a raw newline, so the framing is unambiguous.
 * Every response carries the request's `id` so a caller can match them.
 *
 * Schema cache: schemas are parsed once per (text, baseIRI) and reused. The
 * benchmark re-parsed a 153-line ShExC document for every one of 10,000
 * resources. Parsing is pure and the parsed tree is only read afterwards --
 * `ThreadedMaterializer` keeps its NFA cache on itself, not on the schema --
 * so reuse cannot change output. `tests/engine/test_session.py` asserts that
 * against the one-shot bridges rather than trusting the argument.
 */
"use strict";

const crypto = require("crypto");
const C = require("./common");

const schemaCache = new Map();
const MAX_CACHED_SCHEMAS = 64;

function cachedSchema (text, baseIRI) {
  const key = crypto.createHash("sha256").update(baseIRI + "\u0000" + text).digest("hex");
  let entry = schemaCache.get(key);
  if (entry === undefined) {
    const schema = C.parseSchema(text, baseIRI);
    entry = {schema, constraints: C.indexConstraints(schema)};
    if (schemaCache.size >= MAX_CACHED_SCHEMAS) // bounded: a long run must not grow
      schemaCache.delete(schemaCache.keys().next().value);
    schemaCache.set(key, entry);
  }
  return entry;
}

// ---------------------------------------------------------------------------
// operations
// ---------------------------------------------------------------------------

function opPing () {
  return {ok: true, pong: true, node: process.version,
          cachedSchemas: schemaCache.size};
}

function opParse (req) {
  try {
    const ShExParser = require("@shexjs/parser");
    const base = req.baseIRI || "urn:fhir-sulo:schema";
    const parser = ShExParser.construct(base, {}, {index: true});
    const schema = parser.parse(req.schema);
    return {
      ok: true,
      schema: JSON.parse(JSON.stringify(schema, (k, v) => k.startsWith("_") ? undefined : v)),
      prefixes: schema._prefixes || parser._prefixes || {},
      base,
    };
  } catch (e) {
    return {ok: false, error: e.message,
            line: e.hash && e.hash.loc ? e.hash.loc.first_line : null,
            column: e.hash && e.hash.loc ? e.hash.loc.first_column : null};
  }
}

/** One map job: bind (unless bindings are supplied), then materialize each pass. */
function opRunMap (req) {
  const passes = req.passes || [];
  if (passes.length > 0) {
    const bad = C.checkOptions(req.options);
    if (bad) return {ok: false, stage: "request", error: bad};
  }

  let bindings = req.bindings;
  let validation = {ok: true, suppliedBindings: true};
  if (bindings === undefined || bindings === null) {
    if (!req.source)
      return {ok: false, stage: "request",
              error: "neither `source` nor `bindings` was given"};
    let bound;
    try {
      bound = bindSourceCached(req.source);
    } catch (e) {
      return {ok: false, stage: "validate", error: e.message};
    }
    if (!bound.ok) return {ok: false, stage: "validate", validation: bound.validation};
    bindings = bound.bindings;
    validation = {ok: true, suppliedBindings: false};
  }

  if (passes.length === 0)
    return {ok: true, stage: "bind", validation, bindings, passes: []};

  let entry;
  try {
    entry = cachedSchema(req.target.schema, req.target.baseIRI || "urn:fhir-sulo:target");
  } catch (e) {
    return {ok: false, stage: "parse-target", error: e.message};
  }
  const {schema: targetSchema, constraints: {ids: tcIds, table: constraints}} = entry;

  const out = [];
  for (const spec of passes) {
    const m = C.materializerFor(targetSchema, spec.staticVars, req.options);
    let quads;
    try {
      quads = m.materialize(bindings, spec.root, spec.shape || undefined);
    } catch (e) {
      return {ok: false, stage: "materialize", pass: spec.name,
              error: e.message, report: C.cleanReport(e.report),
              validation, bindings, frames: m.frames || null, passes: out};
    }
    const origins = C.originIndex(m.frames || [], m.frameOrigins || []);
    out.push({
      name: spec.name, root: spec.root, shape: spec.shape || null,
      quads: quads.map(C.termsOf),
      provenance: C.provenanceOf(m, tcIds),
      constraints,
      lastReport: C.cleanReport(m.lastReport),
      accepts: (m.accepts || []).map((a) => ({
        consumed: a.consumed, skipped: a.skipped, quads: a.quads.length})),
      coverage: C.coverageOf(origins, m.chosen || null),
      frames: m.frames || [],
      frameOrigins: m.frameOrigins || [],
    });
  }
  return {ok: true, stage: "done", validation, bindings, passes: out};
}

/** Validation, with the source schema parsed once rather than per resource. */
function bindSourceCached (spec) {
  const N3 = require("n3");
  const ShExTerm = require("@shexjs/term");
  const ShExUtil = require("@shexjs/util");
  const {ShExValidator, resultMapToShapeExprTest} = require("@shexjs/validator");
  const {rdfjsDB} = require("@shexjs/neighborhood-rdfjs");

  const {schema} = cachedSchema(spec.schema, spec.baseIRI || "urn:fhir-sulo:source");
  const store = new N3.Store();
  store.addQuads(new N3.Parser({baseIRI: spec.dataBaseIRI || "urn:fhir-sulo:data"})
                 .parse(spec.data));
  const validator = new ShExValidator(schema, rdfjsDB(store), {results: "api"});
  C.MapModule.register(validator, {ShExTerm});
  const shape = spec.shapeLabel || ShExValidator.Start;
  const validation = resultMapToShapeExprTest(
    validator.validateShapeMap([{node: spec.node, shape}]));
  if (validation.type === "Failure" || validation.type === "FailureList")
    return {ok: false, validation};
  return {ok: true, validation,
          bindings: ShExUtil.valToExtension(validation, C.MAP_EXT)};
}

/** Many jobs in one round trip.
 *
 *  Safe under DR-302: every map is rooted at exactly one FHIR resource and
 *  nothing crosses resources, so a batch is N independent runs that happen to
 *  share a process. Each item is answered independently -- one item's failure
 *  is reported against that item and does not abandon the rest -- so batching
 *  cannot turn a per-resource failure into a per-batch one. */
function opBatch (req, run) {
  const items = req.items || [];
  const results = [];
  for (const item of items) {
    let response;
    try {
      response = run(item.request);
    } catch (e) {
      response = {ok: false, stage: "bridge", error: e && e.stack ? e.stack : String(e)};
    }
    results.push({id: item.id, response});
  }
  return {ok: true, results};
}

const OPS = {
  ping: opPing,
  parse: opParse,
  "run-map": opRunMap,
  "run-map-batch": (req) => opBatch(req, opRunMap),
  "parse-batch": (req) => opBatch(req, opParse),
};

// ---------------------------------------------------------------------------
// the loop
// ---------------------------------------------------------------------------

function handle (line) {
  let req;
  try {
    req = JSON.parse(line);
  } catch (e) {
    return {id: null, ok: false, stage: "request",
            error: "malformed JSON request: " + e.message};
  }
  const op = OPS[req.op];
  if (!op)
    return {id: req.id === undefined ? null : req.id, ok: false, stage: "request",
            error: "unknown op " + JSON.stringify(req.op) + "; known: "
                   + Object.keys(OPS).join(", ")};
  let body;
  try {
    body = op(req);
  } catch (e) {
    body = {ok: false, stage: "bridge", error: e && e.stack ? e.stack : String(e)};
  }
  body.id = req.id === undefined ? null : req.id;
  return body;
}

let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let index;
  while ((index = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, index);
    buffer = buffer.slice(index + 1);
    if (line.trim() === "") continue;
    let out;
    try {
      out = JSON.stringify(handle(line));
    } catch (e) {
      out = JSON.stringify({id: null, ok: false, stage: "bridge",
                            error: "response is not serialisable: " + e.message});
    }
    process.stdout.write(out + "\n");
  }
});
// stdin closing is the shutdown signal: when the owning host process exits,
// its end of the pipe closes, node exits, and `--rm` removes the container.
// Nothing has to remember to clean up, which is the point.
process.stdin.on("end", () => { process.exit(0); });
