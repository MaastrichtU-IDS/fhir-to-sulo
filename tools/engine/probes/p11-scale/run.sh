#!/bin/sh
# Probe 11: scale.  How many repetitions of a starred constraint survive?
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
S=../p03-iteration
for N in 60 200; do
  echo "### $N panels in the source graph, via the CLI (default options)"
  $BIN/shex-validate -x $S/source.shex -d "data$N.ttl" \
    -m '<http://ex.example/P>@START' --extension @shexjs/extension-map > "s$N.val" || exit 1
  $BIN/shexmap-materialize -t $S/target.shex -r 'tag:out/root' < "s$N.val" > "s$N.ttl" 2> "s$N.err"
  echo "  exit=$?  stderr: $(head -c 140 s$N.err)"
  echo "  CLI panels emitted: $(grep -c 'target.example/panel>' s$N.ttl)   (source had $N)"
done
echo
echo "### the same thing through the API: threshold, root cause, and the fix"
node scale.js
echo
echo "### does the 'perfect accept' short circuit ever fire, and how does the fix scale?"
node scale2.js
