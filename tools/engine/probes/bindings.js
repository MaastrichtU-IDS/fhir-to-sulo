#!/usr/bin/env node
/* bindings.js <val-file> -- print the ShExMap binding tree extracted from a .val */
const FS=require("fs"), ShExUtil=require("@shexjs/util");
const MapExt="http://shex.io/extensions/Map/#";
const t=ShExUtil.valToExtension(JSON.parse(FS.readFileSync(process.argv[2],"utf8")), MapExt);
console.log(JSON.stringify(t,null,1));
