#!/bin/sh
# Probe 10: PROPOSED RESOLUTION for the two-level blocker.
#
# Decompose one N-level map into N one-level maps driven by a host-side loop:
#   pass A  root  --> skeleton, with each repeated group's SOURCE IRI as a leaf
#   pass B  for each of those IRIs, materialize its sub-graph ROOTED AT IT (-r)
#   union   the graphs join on the shared IRI -- no rewriting, no invented links
#
# The host picks root nodes and unions; it never edits a triple the engine
# emitted.  Bnode labels ARE relabelled per pass: every materialization
# restarts its counter at _:tm0, so concatenating raw output silently merges
# unrelated bnodes (see the note in merge.js).
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
rm -f part*.ttl union.ttl

echo "### pass A: skeleton"
$BIN/shex-validate -x source.shex -d data.ttl -m '<http://ex.example/P>@START' \
  --extension @shexjs/extension-map > A.val || exit 1
$BIN/shexmap-materialize -t target-outer.shex -r 'http://out.example/Patient/P' < A.val | tee part0.ttl

echo "### pass B: one materialization per repeated group, rooted at its own IRI"
i=0
for R in $(node -e '
  const FS=require("fs"),N3=require("n3");
  const qs=new N3.Parser({baseIRI:"urn:x:"}).parse(FS.readFileSync("part0.ttl","utf8"));
  console.log(qs.filter(q=>q.predicate.value==="http://target.example/report")
                .map(q=>q.object.value).join(" "));'); do
  i=$((i+1)); echo "  -- $R"
  $BIN/shex-validate -x source.shex -d data.ttl \
    -m "<$R>@<file:///w/probes/p10-workaround/Report>" \
    --extension @shexjs/extension-map > B$i.val || exit 1
  $BIN/shexmap-materialize -t target-inner.shex -r "$R" < B$i.val > part$i.ttl
  sed 's/^/     /' part$i.ttl
done

echo "### union"
node merge.js union.ttl part*.ttl
node ../p03b-two-levels/report.js union.ttl
echo "-- expected --"
echo '  one: [(100,60) (101,61)]'
echo '  two: [(110,70) (111,71)]'
