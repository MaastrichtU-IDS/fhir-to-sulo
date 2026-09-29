#!/bin/sh
# Probe 4: deterministic node identity for target nodes
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
$BIN/shex-validate -x source.shex -d data.ttl -m '<http://ex.example/P>@START' \
  --extension @shexjs/extension-map > out.val || exit 1
echo "### 4a: is there an id() function?"
$BIN/shexmap-materialize -t target-id.shex -r 'tag:out/root' < out.val 2>&1 | head -8
echo
echo "### 4b: can a Map variable name the node of a shape-valued constraint?"
$BIN/shexmap-materialize -t target-varnode.shex -r 'tag:out/root' < out.val 2>&1 | head -20
echo
echo "### 4c: determinism -- two identical runs, byte-compared"
$BIN/shexmap-materialize -t /w/probes/p03-iteration/target.shex -r 'tag:out/root' < out.val > r1.ttl
$BIN/shexmap-materialize -t /w/probes/p03-iteration/target.shex -r 'tag:out/root' < out.val > r2.ttl
if cmp -s r1.ttl r2.ttl; then echo "IDENTICAL (incl. bnode labels)"; else echo "DIFFER"; diff r1.ttl r2.ttl; fi
cat r1.ttl
echo "### 4d: root IRI is settable via -r"
$BIN/shexmap-materialize -t /w/probes/p03-iteration/target.shex -r 'http://out.example/Patient/abc' < out.val | head -3
