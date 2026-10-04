#!/bin/sh
# Probe 8: what does a failure look like, and is it machine-parseable?
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
echo "### 8a: source-graph validation failure (JSON, the default)"
$BIN/shex-validate -x ../p03-iteration/source.shex -d nonconformant.ttl \
  -m '<http://ex.example/P>@START' --extension @shexjs/extension-map > f.val 2> f.err
echo "exit=$?"
echo "-- stdout --"; head -c 2000 f.val; echo
echo "-- is it JSON? --"; node -e 'JSON.parse(require("fs").readFileSync("f.val","utf8"));console.log("yes, parses")' 2>&1 | tail -1
echo "-- stderr --"; head -5 f.err
echo
echo "### 8b: same failure, --human"
$BIN/shex-validate -x ../p03-iteration/source.shex -d nonconformant.ttl \
  -m '<http://ex.example/P>@START' --human 2>&1 | head -20
echo
echo "### 8c: feeding a FAILING .val to shexmap-materialize"
$BIN/shexmap-materialize -t ../p03-iteration/target.shex -r 'tag:out/root' < f.val 2>&1 | head -12
echo "exit=$?"
