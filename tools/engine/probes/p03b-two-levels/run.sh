#!/bin/sh
# Probe 3b: TWO levels of repetition (reports x panels).
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
$BIN/shex-validate -x source.shex -d data.ttl -m '<http://ex.example/P>@START' \
  --extension @shexjs/extension-map > out.val || exit 1
$BIN/shexmap-materialize -t target.shex -r 'tag:out/root' < out.val > out.ttl || exit 1
cat out.ttl
echo "-- grouping --"
node report.js out.ttl
echo "-- expected --"
echo '  one: [(100,60) (101,61)]'
echo '  two: [(110,70) (111,71)]'
