#!/bin/sh
# Probe 2: minimal end-to-end ShExMap materialization
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
$BIN/shex-validate -x source.shex -d data.ttl -m '<http://ex.example/x>@START' \
  --extension @shexjs/extension-map > out.val
echo "--- .val ---"; cat out.val
echo "--- materialized ---"
$BIN/shexmap-materialize -t target.shex -r 'tag:out/root' < out.val
