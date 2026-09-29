#!/bin/sh
# Probe 6: inverse / pivot recovery.  Validate the MATERIALIZED target graph
# against the TARGET schema and see whether the same shared variables come back.
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
S=/w/probes/p03-iteration
[ -f $S/outA.ttl ] || sh $S/run.sh >/dev/null 2>&1

echo "### forward bindings (source graph @ source schema)"
node /w/probes/bindings.js $S/outA.val

echo
echo "### materialized target graph"
cat $S/outA.ttl

echo "### reverse: validate target graph @ target schema, extract bindings"
$BIN/shex-validate -x $S/target.shex -d $S/outA.ttl -m '<tag:out/root>@START' \
  --extension @shexjs/extension-map > rev.val 2> rev.err || { echo "REVERSE VALIDATION FAILED"; cat rev.err; exit 1; }
node /w/probes/bindings.js rev.val

echo
echo "### round trip: rematerialize the SOURCE schema from the reverse bindings"
$BIN/shexmap-materialize -t $S/source.shex -r 'tag:back/root' < rev.val
