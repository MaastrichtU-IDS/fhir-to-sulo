#!/usr/bin/env node
/* Probe 1: programmatic API surface of the installed ShExMap build. */
const N3 = require("n3");
const shex = require("shex");
console.log("shex (meta package) exports:", Object.keys(shex).sort().join(", "));
const MapFactory = require("@shexjs/extension-map");
console.log("\n@shexjs/extension-map default export is a:", typeof MapFactory);
const Mapper = MapFactory({rdfjs: N3, Validator: {}});
console.log("Map(...) exports:", Object.keys(Mapper).sort().join(", "));
console.log("\nMapper.url =", Mapper.url);
console.log("ThreadedMaterializer is a:", typeof Mapper.ThreadedMaterializer);
console.log("MaterializationError is a:", typeof Mapper.MaterializationError);
const TM = require("@shexjs/extension-map/lib/ThreadedMaterializer");
console.log("\n@shexjs/extension-map/lib/ThreadedMaterializer exports:", Object.keys(TM).sort().join(", "));
console.log("ThreadedMaterializer instance methods:",
  Object.getOwnPropertyNames(TM.ThreadedMaterializer.prototype).sort().join(", "));
for (const p of ["@shexjs/parser","@shexjs/util","@shexjs/validator","@shexjs/loader",
                 "@shexjs/writer","@shexjs/node","@shexjs/term","@shexjs/neighborhood-rdfjs",
                 "@shexjs/eval-simple-1err","@shexjs/eval-threaded-nerr","shape-map"]) {
  let m; try { m = require(p); } catch (e) { console.log(`\n${p}: LOAD FAILED ${e.message}`); continue; }
  console.log(`\n${p}: ${typeof m}` + (typeof m === "object" ? " keys=" + Object.keys(m).sort().slice(0,30).join(", ") : ""));
}
console.log("\nShExUtil.valToExtension is a:", typeof require("@shexjs/util").valToExtension);
