#!/bin/sh
# Probe 3: nested repetition / iteration scopes -- does materialization
# preserve within-group (panel) association of systolic+diastolic?
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
T=http://target.example
for V in A B C D E; do
  echo "===== variant $V ====="
  $BIN/shex-validate -x source.shex -d "data$V.ttl" -m '<http://ex.example/P>@START' \
    --extension @shexjs/extension-map > "out$V.val" 2> "err$V.txt" || { echo "VALIDATE FAILED"; cat "err$V.txt"; continue; }
  $BIN/shexmap-materialize -t target.shex -r 'tag:out/root' < "out$V.val" > "out$V.ttl" 2> "merr$V.txt" \
    || { echo "MATERIALIZE FAILED"; cat "merr$V.txt"; continue; }
  cat "out$V.ttl"
  echo "-- pairs (systolic,diastolic) --"
  node /w/probes/pairs.js "out$V.ttl" "$T/systolic" "$T/diastolic"
done
