#!/bin/sh
# exit-code discipline (measured WITHOUT a pipe, so $? is the tool's own)
cd "$(dirname "$0")"
BIN=/w/node_modules/.bin
$BIN/shex-validate -x ../p03-iteration/source.shex -d nonconformant.ttl \
  -m '<http://ex.example/P>@START' --extension @shexjs/extension-map > f.val 2>/dev/null
echo "shex-validate on nonconformant data   -> exit $?"
$BIN/shexmap-materialize -t ../p03-iteration/target.shex -r 'tag:out/root' < f.val > m.ttl 2>m.err
echo "shexmap-materialize on a failing .val -> exit $?  (stderr: $(head -c 60 m.err))"
echo "                                          stdout bytes: $(wc -c < m.ttl)"
$BIN/shexmap-materialize -t ../p05-lineage/target-typo.shex -r 'tag:out/root' < ../p03-iteration/outA.val > t.ttl 2>t.err
echo "shexmap-materialize, target var never bound -> exit $?  (silently partial)"
echo "  stdout: $(cat t.ttl)"
echo "  stderr: $(head -c 200 t.err)"
$BIN/shex-validate -x ../p05-lineage/target-typo.shex --diagnose >d.out 2>d.err
echo "shex-validate --diagnose -> exit $?  stderr: $(head -1 d.err)"
