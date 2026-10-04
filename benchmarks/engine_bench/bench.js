#!/usr/bin/env node
/* Gate 4 engine scale measurement for the pinned ShExMap build.
 *
 * Agent 4 measured the engine scaling QUADRATICALLY: 1000 panels in 2.1 s,
 * 2000 in 12.4 s (DR-301 B2). The brief called the Gate 4 target "at risk"
 * on that basis. This measures whether it actually is.
 *
 * The claim under test is DR-302's: the quadratic term is in the number of
 * REPETITIONS INSIDE ONE MATERIALIZATION, and the pilot never has more than
 * a handful, because every map is rooted at one FHIR resource with at most
 * one level of repetition. If that is right, 10,000 resources is 10,000
 * small materializations and the total is linear.
 *
 * Both curves are measured, because reporting only the good one would be
 * choosing the flattering measurement:
 *
 *   PART A  N separate materializations of a 2-component panel
 *           - the shape the pilot actually runs
 *   PART B  ONE materialization of a panel with N components
 *           - Agent 4's curve, reproduced, to show the term is real and to
 *             show where it would bite if DR-302 were ever relaxed
 *
 * maxAccepts/maxRepeat/maxSteps/exploreSteps are raised explicitly, per
 * DR-301 decision 1 and CD-2: the defaults silently truncate at 19 items.
 */
"use strict";

const FS = require("fs");
const OS = require("os");
const PATH = require("path");
const N3 = require("n3");
const CP = require("child_process");
const ShExUtil = require("@shexjs/util");
const ShExParser = require("@shexjs/parser");
const Mapper = require("@shexjs/extension-map")({ rdfjs: N3, Validator: {} });

const MapExt = "http://shex.io/extensions/Map/#";
const HERE = __dirname;
const TMP = FS.mkdtempSync(PATH.join(OS.tmpdir(), "engine-bench-"));

const ENGINE_OPTIONS = {
  maxRepeat: 1e6,
  maxAccepts: 1e6,
  maxSteps: 1e9,
  exploreSteps: 1e9,
};

function parseSchema(name) {
  const file = PATH.join(HERE, name);
  return ShExParser.construct("file://" + file, {}, { index: true })
    .parse(FS.readFileSync(file, "utf8"));
}

const targetSchema = parseSchema("target.shex");
const SOURCE = PATH.join(HERE, "source.shex");
const BIN = "/w/node_modules/.bin";

/* One panel with `components` components. */
function panelTurtle(id, components) {
  const lines = ["PREFIX : <http://ex.example/>"];
  const names = [];
  for (let i = 0; i < components; i++) names.push(`<http://ex.example/c${id}-${i}>`);
  lines.push(
    `<http://ex.example/obs${id}> :effective "2026-09-02T09:00:00Z" ; ` +
    `:component ${names.join(", ")} .`
  );
  for (let i = 0; i < components; i++) {
    lines.push(`${names[i]} :code "${i % 2 === 0 ? "8480-6" : "8462-4"}" ; :value ${100 + i} .`);
  }
  return lines.join("\n") + "\n";
}

/* Validate the source graph and extract the shared-variable bindings. */
function bindingsFor(turtle, rootId) {
  const path = PATH.join(TMP, "d.ttl");
  FS.writeFileSync(path, turtle);
  const out = CP.execSync(
    `${BIN}/shex-validate -x ${SOURCE} -d ${path} ` +
    `-m '<http://ex.example/obs${rootId}>@START' --extension @shexjs/extension-map`,
    { maxBuffer: 1e9 }
  ).toString();
  return ShExUtil.valToExtension(JSON.parse(out), MapExt);
}

function materialize(bindings, root) {
  const m = new Mapper.ThreadedMaterializer(targetSchema, ENGINE_OPTIONS);
  const quads = m.materialize(bindings, root);
  /* Fail-fast, per DR-301 decision 3: the engine exits 0 on a partial graph,
   * so the driver - and therefore this benchmark - must check the report
   * rather than trust the exit status. A benchmark that measured silently
   * truncated output would be measuring nothing. */
  const report = m.lastReport || {};
  const unbound = (report.unboundVariables || []).length;
  if (unbound > 0) throw new Error(`unbound variables: ${unbound}`);
  if (report.explorationTruncated) throw new Error("exploration truncated");
  return { quads, report };
}

function partA(counts) {
  console.log("PART A - N separate materializations, 2 components each");
  console.log("         (the shape the pilot actually runs; DR-302)");
  console.log("  " + "N".padStart(8) + "total".padStart(14) + "per resource".padStart(16)
              + "resources/s".padStart(14));

  /* One validation is enough to show the per-resource binding cost; running
   * shex-validate as a subprocess N times would measure process spawn, not
   * the engine. The real driver runs it in-process (CD-2). */
  const oneBinding = bindingsFor(panelTurtle(0, 2), 0);

  const rows = [];
  for (const n of counts) {
    const t0 = Date.now();
    let quads = 0;
    for (let i = 0; i < n; i++) {
      quads += materialize(oneBinding, `tag:out/obs${i}`).quads.length;
    }
    const total = Date.now() - t0;
    rows.push([n, total]);
    console.log("  " + String(n).padStart(8)
              + ((total / 1000).toFixed(3) + " s").padStart(14)
              + ((total / n).toFixed(3) + " ms").padStart(16)
              + (n / (total / 1000)).toFixed(0).padStart(14));
    if (n === counts[counts.length - 1]) {
      console.log("         " + quads + " quads emitted, " + (quads / n) + " per resource");
    }
  }
  return rows;
}

/* PART A is materialization only: it reuses one binding tree N times, so it
 * measures the ThreadedMaterializer and nothing else. The real pipeline also
 * validates each source graph to produce that binding tree. This measures
 * that half through the shipped CLI, which is an UPPER BOUND and a loose one:
 * almost all of it is process spawn, and CD-2 bans the CLI anyway - Agent 4's
 * driver calls the API in-process. Reported so that Part A is not mistaken
 * for an end-to-end figure. */
function partA2(n) {
  console.log("");
  console.log("PART A2 - source validation + binding extraction, per resource");
  console.log("          via the shipped CLI: an UPPER BOUND, spawn-dominated.");
  console.log("          CD-2 bans the CLI; the real driver runs this in-process.");
  const t0 = Date.now();
  for (let i = 0; i < n; i++) bindingsFor(panelTurtle(i, 2), i);
  const total = Date.now() - t0;
  console.log("  " + String(n).padStart(8)
            + ((total / 1000).toFixed(2) + " s").padStart(14)
            + ((total / n).toFixed(1) + " ms").padStart(16)
            + (n / (total / 1000)).toFixed(0).padStart(14) + "  resources/s");
  console.log("  extrapolated to 10,000 resources: "
            + (total / n * 10000 / 1000).toFixed(1) + " s (upper bound)");
}

function partB(counts) {
  console.log("");
  console.log("PART B - ONE materialization with N components");
  console.log("         (Agent 4's quadratic curve, reproduced; DR-301 B2)");
  console.log("  " + "N".padStart(8) + "time".padStart(14) + "us/N^2".padStart(14)
              + "quads".padStart(10));
  for (const n of counts) {
    const bindings = bindingsFor(panelTurtle(1, n), 1);
    const t0 = Date.now();
    const { quads } = materialize(bindings, "tag:out/root");
    const total = Date.now() - t0;
    console.log("  " + String(n).padStart(8)
              + (total + " ms").padStart(14)
              + (total / (n * n) * 1000).toFixed(3).padStart(14)
              + String(quads.length).padStart(10));
  }
}

function linearity(rows) {
  console.log("");
  console.log("LINEARITY of Part A (ms per resource; flat == linear)");
  for (const [n, ms] of rows) {
    console.log("  N=" + String(n).padStart(6) + "  " + (ms / n).toFixed(4) + " ms/resource");
  }
  const first = rows[0][1] / rows[0][0];
  const last = rows[rows.length - 1][1] / rows[rows.length - 1][0];
  const ratio = last / first;
  console.log("  per-resource cost changed by a factor of " + ratio.toFixed(2)
              + " between N=" + rows[0][0] + " and N=" + rows[rows.length - 1][0]);
  console.log("  VERDICT: " + (ratio < 2
    ? "LINEAR in the number of resources"
    : "NOT linear - the per-resource cost grows with N"));
}

const partACounts = (process.env.BENCH_A || "100,1000,5000,10000")
  .split(",").map(Number);
const partBCounts = (process.env.BENCH_B || "100,250,500,1000,2000")
  .split(",").map(Number);

console.log("pinned engine: shex@1.0.0-alpha.33 / @shexjs/extension-map@1.0.0-alpha.33");
console.log("node:          " + process.version);
console.log("options:       " + JSON.stringify(ENGINE_OPTIONS));
console.log("");
const rows = partA(partACounts);
linearity(rows);
partA2(Number(process.env.BENCH_A2 || 100));
partB(partBCounts);
FS.rmSync(TMP, { recursive: true, force: true });
