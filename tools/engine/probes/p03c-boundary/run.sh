#!/bin/sh
# Probe 3c/3d: where exactly does the nesting support stop?
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
echo "### 3c: two levels, NO variable on the outer group (2 reports x 2 panels)"
$BIN/shex-validate -x source-novar.shex -d data-novar.ttl -m '<http://ex.example/P>@START' \
  --extension @shexjs/extension-map > c.val || exit 1
$BIN/shexmap-materialize -t target-novar.shex -r 'tag:out/root' < c.val > c.ttl || exit 1
cat c.ttl
echo "   reports emitted: $(grep -c 'target.example/report>' c.ttl)  (source had 2)"
echo
echo "### 3d: two levels, outer variable, exactly ONE inner per group"
$BIN/shex-validate -x ../p03b-two-levels/source.shex -d data-one-each.ttl -m '<http://ex.example/P>@START' \
  --extension @shexjs/extension-map > d.val || exit 1
$BIN/shexmap-materialize -t ../p03b-two-levels/target.shex -r 'tag:out/root' < d.val > d.ttl || exit 1
cat d.ttl
echo "-- grouping --"
node ../p03b-two-levels/report.js d.ttl
echo "-- expected:   one: [(100,60)]   two: [(110,70)] --"
