#!/usr/bin/env node
/* run-map.js -- drive the pinned ShExMap engine for one map job and print a
 * single JSON result document.
 *
 * TEMPORARY, TEST-ONLY.  Agent 4 owns the production materialization driver
 * (DR-301 decision 3, CD-2).  This exists so Agent 3's acceptance tests can run
 * before that driver lands, and should be deleted when it does.
 *
 * It obeys the same two rules as the production driver:
 *   - binding extraction uses `shex-validate`, which is well behaved: exit 1 on
 *     nonconformance, parseable JSON Failure on stdout (DR-301 probe 8a);
 *   - materialization uses the ThreadedMaterializer API with maxAccepts /
 *     maxRepeat / maxSteps / exploreSteps raised explicitly.  The shipped
 *     `shexmap-materialize` is banned: it truncates every repetition to 19
 *     items and exits 0 on fatal and on partial output (DR-301 B2/B3).
 *
 * Usage:  node run-map.js <job.json>
 *         node run-map.js -          (job JSON on stdin)
 */
"use strict";

const FS = require("fs");
const CP = require("child_process");
const N3 = require("n3");
const ShExUtil = require("@shexjs/util");
const ShExParser = require("@shexjs/parser");
const Mapper = require("@shexjs/extension-map")({ rdfjs: N3, Validator: {} });

const MAP_EXT = "http://shex.io/extensions/Map/#";
const VALIDATE = process.env.SHEX_VALIDATE || "/w/node_modules/.bin/shex-validate";

// DR-301 blocker B2: maxAccepts defaults to 20 and silently truncates any
// repetition to 19 items.  These are mandatory, not tuning.
const MANDATORY_GUARDS = { maxAccepts: 1e6, maxRepeat: 1e6, maxSteps: 1e9, exploreSteps: 1e9 };

function parseSchema(path) {
  return ShExParser.construct("file://" + path, {}, { index: true })
    .parse(FS.readFileSync(path, "utf8"));
}

function termToNT(t) {
  if (t.termType === "NamedNode") return "<" + t.value + ">";
  if (t.termType === "BlankNode") return "_:" + t.value;
  if (t.termType === "Literal") {
    const lex = JSON.stringify(t.value);
    if (t.language) return lex + "@" + t.language;
    const dt = t.datatype && t.datatype.value;
    if (dt && dt !== "http://www.w3.org/2001/XMLSchema#string") return lex + "^^<" + dt + ">";
    return lex;
  }
  return String(t.value);
}

function main() {
  // The job comes in on stdin when the argument is "-".  It used to be
  // docker cp'd to a fixed /w/job.json, which raced: `docker cp` returns once
  // the daemon has accepted the archive, so a later `docker exec` could read
  // the PREVIOUS call's job.  That produced graphs from the wrong fixture and
  // made the BP suite non-deterministic.  stdin has no such window.
  const job = JSON.parse(process.argv[2] === "-"
    ? FS.readFileSync(0, "utf8")
    : FS.readFileSync(process.argv[2], "utf8"));
  const out = {
    ok: false, stage: "validate", validation: null, bindings: null,
    passes: [], nquads: "", engine: {
      shex: require("shex/package.json").version,
      extensionMap: require("@shexjs/extension-map/package.json").version,
      node: process.version,
      guards: MANDATORY_GUARDS,
    },
  };

  // ---- stage 1: bind (CLI validator; exits 1 on nonconformance) -----------
  // `dataInline` lets a caller validate a graph it just produced rather than one
  // committed on disk.  The inverse/pivot tests use it so they revalidate FRESH
  // output: reading the committed golden would make them blind to exactly the
  // drift they exist to catch.
  let dataPath = job.data;
  if (job.dataInline !== undefined) {
    dataPath = "/tmp/run-map-inline-" + process.pid + ".nt";
    FS.writeFileSync(dataPath, job.dataInline);
  }
  const shapeMap = "<" + job.focus + ">@" + (job.startShape ? "<" + job.startShape + ">" : "START");
  const args = ["-x", job.sourceSchema, "-d", dataPath, "-m", shapeMap,
                "--extension", "@shexjs/extension-map"];
  const proc = CP.spawnSync(VALIDATE, args, { encoding: "utf8", maxBuffer: 1 << 28 });
  if (proc.status !== 0) {
    let failure = null;
    try { failure = JSON.parse(proc.stdout); } catch (e) { /* not JSON */ }
    out.validation = {
      ok: false, exitCode: proc.status, failure,
      stdout: failure ? null : (proc.stdout || "").slice(0, 4000),
      stderr: (proc.stderr || "").slice(0, 4000),
    };
    process.stdout.write(JSON.stringify(out, null, 1));
    return;
  }
  out.validation = { ok: true, exitCode: 0, failure: null };
  const bindings = ShExUtil.valToExtension(JSON.parse(proc.stdout), MAP_EXT);
  out.bindings = bindings;

  // Host-side binding mutation hook.  Used ONLY by the fault-injection tests,
  // to prove the acceptance checks can actually fail.  Never on a real run.
  const feed = job.bindingsOverride !== undefined ? job.bindingsOverride : bindings;

  // ---- stage 2: materialize, one pass per target root ---------------------
  out.stage = "materialize";

  const unionQuads = [];
  for (const pass of job.passes || []) {
    // staticVars are scoped PER PASS.  A pass that is handed a run binding it
    // never uses reports it in lastReport.unusedStatics, and the harness
    // treats that as an error -- which is how a mistyped variable name is
    // caught, given that the engine's own response to an unknown Map function
    // is to silently delete the whole shape (DR-301 4b / CD-1).
    const opts = Object.assign({}, MANDATORY_GUARDS, job.options || {}, pass.options || {},
                               { staticVars: pass.staticVars || job.staticVars || {} });
    const targetSchema = parseSchema(pass.targetSchema || job.targetSchema);
    const m = new Mapper.ThreadedMaterializer(targetSchema, opts);
    const entry = { name: pass.name, root: pass.root, shape: pass.shape,
                    quads: [], report: null, error: null };
    let quads;
    try {
      quads = m.materialize(feed, pass.root, pass.shape);
    } catch (e) {
      entry.error = { message: String((e && e.message) || e), report: (e && e.report) || null };
      entry.report = (e && e.report) || null;
      out.passes.push(entry);
      process.stdout.write(JSON.stringify(out, null, 1));
      return;
    }
    const r = m.lastReport || {};
    entry.report = {
      alternatives: r.alternatives,
      explorationTruncated: r.explorationTruncated,
      unboundVariables: r.unboundVariables || [],
      unusedStatics: r.unusedStatics || [],
      configsPruned: r.configsPruned,
    };

    // DR-301 4d: the blank-node counter restarts at _:tm0 for every
    // materialization, so unioning passes without relabelling silently merges
    // unrelated blank nodes.  Relabelling is semantically a no-op.
    const relabel = (t) =>
      t.termType === "BlankNode" ? N3.DataFactory.blankNode(pass.name + "_" + t.value) : t;
    for (const q of quads) {
      const s = relabel(q.subject), p = q.predicate, o = relabel(q.object);
      entry.quads.push([termToNT(s), termToNT(p), termToNT(o)]);
      unionQuads.push([termToNT(s), termToNT(p), termToNT(o)]);
    }
    out.passes.push(entry);
  }

  const lines = unionQuads.map((t) => t[0] + " " + t[1] + " " + t[2] + " .");
  out.nquads = Array.from(new Set(lines)).sort().join("\n");
  out.stage = "done";
  out.ok = true;
  process.stdout.write(JSON.stringify(out, null, 1));
}

main();
