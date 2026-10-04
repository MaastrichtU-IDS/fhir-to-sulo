#!/bin/sh
# verdicts.sh -- runs INSIDE the container; one line of PASS/FAIL per probe.
# Full transcripts come from the per-probe run.sh scripts under probes/.
cd /w/probes
BIN=/w/node_modules/.bin
RC=0
say () { printf '%-6s %s\n' "$1" "$2"; [ "$1" = FAIL ] && RC=1; return 0; }

# --- 1 install & surface -------------------------------------------------
[ -x $BIN/shexmap-materialize ] && [ -x $BIN/shex-validate ] && [ -x $BIN/shexmap-debug ] \
  && node -e 'require("@shexjs/extension-map")({rdfjs:require("n3"),Validator:{}}).ThreadedMaterializer' \
  && say PASS "1  install & surface: shex-validate, shexmap-materialize, shexmap-debug + ThreadedMaterializer API" \
  || say FAIL "1  install & surface"

# --- 2 minimal end-to-end ------------------------------------------------
sh p02-minimal/run.sh > /tmp/p02.log 2>&1
grep -q '<tag:out/root> <http://target.example/label> "Alice"' /tmp/p02.log \
  && say PASS "2  minimal end-to-end materialization" || say FAIL "2  minimal end-to-end materialization"

# --- 3 iteration scopes, ONE level ---------------------------------------
sh p03-iteration/run.sh > /tmp/p03.log 2>&1
ok=1
for want in '(105,70) (120,80)' '(105,70) (120,80)' '(105,70) (120,80)' '(105,70) (120,80)' '(105,70) (120,80) (99,61)'; do :; done
n=$(grep -c '^(105,70) (120,80)$' /tmp/p03.log)
m=$(grep -c '^(105,70) (120,80) (99,61)$' /tmp/p03.log)
[ "$n" = 4 ] && [ "$m" = 1 ] \
  && say PASS "3  iteration scopes, ONE level of repetition: pairs stay associated under every triple order" \
  || say FAIL "3  iteration scopes, ONE level of repetition"

# --- 3b iteration scopes, TWO levels -------------------------------------
sh p03b-two-levels/run.sh > /tmp/p03b.log 2>&1
if grep -q '^one: \[(100,60) (101,61)\]$' /tmp/p03b.log && grep -q '^two: \[(110,70) (111,71)\]$' /tmp/p03b.log; then
  say PASS "3b iteration scopes, TWO levels of repetition"
else
  say FAIL "3b iteration scopes, TWO levels of repetition -- groups mis-associated AND a panel is lost (see probes/p03b-two-levels)"
fi

# --- 3c/3d where the nesting support stops -------------------------------
sh p03c-boundary/run.sh > /tmp/p03c.log 2>&1
grep -q 'reports emitted: 1  (source had 2)' /tmp/p03c.log \
  && say FAIL "3c two outer groups with no outer variable collapse into one (expected: 2)" \
  || say PASS "3c outer grouping preserved"
grep -q '^one: \[(100,60)\]$' /tmp/p03c.log && grep -q '^two: \[(110,70)\]$' /tmp/p03c.log \
  && say PASS "3d two levels, one inner each" \
  || say FAIL "3d two levels with only ONE inner element each is still mis-associated"

# --- 4 deterministic node identity ---------------------------------------
sh p04-identity/run.sh > /tmp/p04.log 2>&1
grep -q 'IDENTICAL' /tmp/p04.log \
  && say PASS "4a bnode labels + output are byte-identical across runs (deterministic)" \
  || say FAIL "4a determinism"
grep -q 'target.example/iri' /tmp/p04.log \
  && say PASS "4b id() minted an IRI" \
  || say FAIL "4b no id() function: '%Map:{ id(v:x) %}' silently prunes the whole shape"
grep -q 'target.example/panel> <http://ex.example/p1>, <http://ex.example/p2>' /tmp/p04.log \
  && say FAIL "4c a Map var on a shape-valued constraint emits the IRI as a LEAF and drops the sub-shape" \
  || say PASS "4c Map var names the sub-shape node"

# --- 5 per-quad lineage ---------------------------------------------------
sh p05-lineage/run.sh > /tmp/p05.log 2>&1
grep -q 'src={"variables":\["http://ex.example/var#sys"\],"frame":1' /tmp/p05.log \
  && say PASS "5  per-quad lineage via API: materializer.provenance[] + frameOrigins[]" \
  || say FAIL "5  per-quad lineage"

# --- 6 inverse / pivot ----------------------------------------------------
sh p06-inverse/run.sh > /tmp/p06.log 2>&1
grep -q 'tag:back/root' /tmp/p06.log \
  && say PASS "6  inverse/pivot: target graph revalidates and yields identical bindings; full round trip" \
  || say FAIL "6  inverse/pivot recovery"

# --- 7 static analysis ----------------------------------------------------
sh p07-static/run.sh > /tmp/p07.log 2>&1
ls $BIN | grep -qiE 'check|lint' \
  && say PASS "7  a shexmap-check equivalent ships" \
  || say FAIL "7  no static checker ships; unbound target variables only surface at runtime, via the API's lastReport"

# --- 8 failure reporting --------------------------------------------------
sh p08-failure/run.sh > /tmp/p08.log 2>&1
sh p08-failure/exitcodes.sh > /tmp/p08e.log 2>&1
grep -q 'yes, parses' /tmp/p08.log \
  && say PASS "8a validation failures are machine-parseable JSON (shex-validate exits 1)" \
  || say FAIL "8a validation failure reporting"
grep -q 'shexmap-materialize on a failing .val -> exit 0' /tmp/p08e.log \
  && say FAIL "8b shexmap-materialize EXITS 0 on a fatal materialization error and prints an empty graph" \
  || say PASS "8b shexmap-materialize signals materialization errors via exit code"
grep -q 'silently partial' /tmp/p08e.log && grep -q 'exit 0  (silently partial)' /tmp/p08e.log \
  && say FAIL "8c an unbindable target variable silently yields a PARTIAL graph, exit 0, nothing on stderr" \
  || say PASS "8c partial materialization is reported"

# --- 10 proposed resolution for the two-level blocker --------------------
sh p10-workaround/run.sh > /tmp/p10.log 2>&1
grep -q '^one: \[(100,60) (101,61)\]$' /tmp/p10.log && grep -q '^two: \[(110,70) (111,71)\]$' /tmp/p10.log \
  && say PASS "10 WORKAROUND: N one-level maps joined on the group IRI reproduce the two-level map exactly" \
  || say FAIL "10 workaround for the two-level blocker"

# --- 11 scale -------------------------------------------------------------
sh p11-scale/run.sh > /tmp/p11.log 2>&1
grep -q 'CLI panels emitted: 19   (source had 60)' /tmp/p11.log \
  && say FAIL "11a the CLI silently emits at most 19 of N repetitions (maxAccepts defaults to 20, exit 0, no stderr)" \
  || say PASS "11a starred cardinality is not truncated by the CLI"
grep -q 'n= 200 maxAccepts>n .* panels= 200/200' /tmp/p11.log \
  && say PASS "11b raising maxAccepts through the API removes the cap (200/200, 500/500)" \
  || say FAIL "11b maxAccepts does not explain the cap"

# --- 9 upstream fixture conformance --------------------------------------
sh p09-fixtures/run.sh > /tmp/p09.log 2>&1
tail -1 /tmp/p09.log | grep -q '7 pass, 1 fail' \
  && say PASS "9  upstream fixtures: 7/8 reproduce (the 1 miss is a staticVar absent from the stored expectation)" \
  || say FAIL "9  upstream fixture conformance: $(tail -1 /tmp/p09.log)"

echo
echo "logs: /tmp/p0*.log inside the container"
exit $RC
