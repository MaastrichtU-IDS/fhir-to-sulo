#!/usr/bin/env node
/* run-map.js -- one map job: validate the source once, materialize N passes.
 *
 * This is the production multi-pass bridge, and it replaces the test-only
 * `tests/contracts/maps/_engine/run-map.js` that Agent 3 wrote to get the Gate
 * 2/3 suites running before the driver landed.
 *
 * Why N passes and one validation: the engine has no `id()`, so only a
 * materialization's root node has a controllable IRI, so every IRI-identified
 * target node is the root of its own pass (DR-301 4b/4c, DR-302's
 * decomposition). The blood-pressure map has ten such nodes over a single
 * source binding. Validating ten times to answer one question would be ten
 * times the work, and it would also make "were all bindings consumed?"
 * meaningless per pass -- coverage is a property of the map, not of a pass.
 *
 * `bindings` in the request replaces the lifted bindings and skips validation.
 * Two legitimate uses: replaying a stored binding tree, and the fault
 * injection Agent 3's tests need to prove their acceptance checks can fail.
 * It is a named field of the request, not a hidden hook: the driver exposes it
 * only through `materialize_from_bindings`, never on the normal path.
 *
 * stdin: {
 *   source: {schema, baseIRI?, data, dataBaseIRI?, node, shapeLabel?} | null,
 *   bindings: <binding tree> | null,   // replaces validation when present
 *   target: {schema, baseIRI?},
 *   passes: [{name, shape, root, staticVars}],   // [] = bind only
 *   options: {maxAccepts, maxRepeat, maxSteps, exploreSteps, maxCallDepth}
 * }
 */
"use strict";

const C = require("./common");

const emit = C.emitter();
C.readRequest((raw) => {
  let req;
  try {
    req = JSON.parse(raw);
  } catch (e) {
    return emit({ok: false, stage: "request", error: "malformed JSON: " + e.message});
  }
  try {
    main(req);
  } catch (e) {
    emit({ok: false, stage: "bridge", error: e && e.stack ? e.stack : String(e)});
  }
});

function main (req) {
  const passes = req.passes || [];
  if (passes.length > 0) {
    const bad = C.checkOptions(req.options);
    if (bad) return emit({ok: false, stage: "request", error: bad});
  }

  // ---- bindings: from validation, or handed in -------------------------
  let bindings = req.bindings;
  let validation = {ok: true, suppliedBindings: true};
  if (bindings === undefined || bindings === null) {
    if (!req.source)
      return emit({ok: false, stage: "request",
                   error: "neither `source` nor `bindings` was given"});
    let bound;
    try {
      bound = C.bindSource(req.source);
    } catch (e) {
      return emit({ok: false, stage: "validate", error: e.message});
    }
    if (!bound.ok)
      return emit({ok: false, stage: "validate", validation: bound.validation});
    bindings = bound.bindings;
    validation = {ok: true, suppliedBindings: false};
  }

  if (passes.length === 0)
    return emit({ok: true, stage: "bind", validation, bindings, passes: []});

  // ---- target schema, parsed and indexed once --------------------------
  let targetSchema, tcIds, constraints;
  try {
    targetSchema = C.parseSchema(req.target.schema,
                                 req.target.baseIRI || "urn:fhir-sulo:target");
    const indexed = C.indexConstraints(targetSchema);
    tcIds = indexed.ids;
    constraints = indexed.table;
  } catch (e) {
    return emit({ok: false, stage: "parse-target", error: e.message});
  }

  // ---- one materialization per declared pass ---------------------------
  const out = [];
  for (const spec of passes) {
    const m = C.materializerFor(targetSchema, spec.staticVars, req.options);
    let quads;
    try {
      quads = m.materialize(bindings, spec.root, spec.shape || undefined);
    } catch (e) {
      return emit({
        ok: false, stage: "materialize", pass: spec.name,
        error: e.message, report: C.cleanReport(e.report),
        validation, bindings,
        frames: m.frames || null,
        passes: out,
      });
    }
    const origins = C.originIndex(m.frames || [], m.frameOrigins || []);
    out.push({
      name: spec.name,
      root: spec.root,
      shape: spec.shape || null,
      quads: quads.map(C.termsOf),
      provenance: C.provenanceOf(m, tcIds),
      constraints,
      lastReport: C.cleanReport(m.lastReport),
      accepts: (m.accepts || []).map((a) => ({
        consumed: a.consumed, skipped: a.skipped, quads: a.quads.length,
      })),
      coverage: C.coverageOf(origins, m.chosen || null),
      frames: m.frames || [],
      frameOrigins: m.frameOrigins || [],
    });
  }

  emit({ok: true, stage: "done", validation, bindings, passes: out});
}
