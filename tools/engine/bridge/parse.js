#!/usr/bin/env node
/* parse.js -- ShExC -> ShExJ, using the PINNED engine's own parser.
 *
 * The linter must never disagree with the engine about what a schema says, so
 * it does not implement a ShExC parser. It asks this one. `shex-to-json` would
 * almost do, but it drops `_prefixes`, and without prefixes a Map code like
 * `id(v:panelId)` cannot be told from a variable in an undeclared prefix --
 * which is precisely the CD-1 check.
 *
 * stdin : {"schema": "<ShExC text>", "baseIRI": "urn:..."}
 * stdout: {"ok": true, "schema": <ShExJ>, "prefixes": {...}}
 *         {"ok": false, "error": "...", "line": n, "column": n}
 */
"use strict";
const ShExParser = require("@shexjs/parser");

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => { raw += c; });
process.stdin.on("end", () => {
  let req;
  try {
    req = JSON.parse(raw);
  } catch (e) {
    return emit({ok: false, error: "bridge received malformed JSON: " + e.message});
  }
  const base = req.baseIRI || "urn:fhir-sulo:schema";
  try {
    const parser = ShExParser.construct(base, {}, {index: true});
    const schema = parser.parse(req.schema);
    emit({
      ok: true,
      schema: JSON.parse(JSON.stringify(schema, replacer)),
      prefixes: schema._prefixes || parser._prefixes || {},
      base: base,
    });
  } catch (e) {
    emit({
      ok: false,
      error: e.message,
      line: e.hash && e.hash.loc ? e.hash.loc.first_line : null,
      column: e.hash && e.hash.loc ? e.hash.loc.first_column : null,
    });
  }
});

/** Drop the parser's private back-references; they are cyclic and we only
 *  need the ShExJ tree plus the prefix table. */
function replacer (key, value) {
  return key.startsWith("_") ? undefined : value;
}

let emitted = false;
function emit (obj) {
  if (emitted) return;          // one response per invocation; see run-pass.js
  emitted = true;
  process.stdout.write(JSON.stringify(obj));
  process.exitCode = obj.ok ? 0 : 1;
}
