#!/bin/sh
# Verify the pilot from a CLEAN CLONE, not in place.
#
# The acceptance matrix's "Deployability" row reads: "One documented command
# runs CLI/API and CI tests with pinned versions." Running the suite in a
# working tree does not test that -- a tree accumulates a .venv, a built
# engine image, generated fixtures and whatever else the last run left. This
# clones the current branch into a scratch directory and runs it from nothing.
#
#   tools/verify-clean-clone.sh [branch]
#
# Needs Docker for the engine and reasoner stages. Exits non-zero on the first
# failure, because a partial pass is not what this check is for.
set -e

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
SRC="$(git rev-parse --show-toplevel)"
DEST="$(mktemp -d "${TMPDIR:-/tmp}/fhir-sulo-cleanclone.XXXXXX")"
trap 'rm -rf "$DEST"' EXIT

echo "== cloning $BRANCH into $DEST =="
git clone -q --branch "$BRANCH" "$SRC" "$DEST"
cd "$DEST"
echo "   $(git log --oneline -1)"
echo "   $(git ls-files | wc -l | tr -d ' ') tracked files"

echo
echo "== 1/5  zero-install path (no venv, standard library only) =="
make contracts-stdlib

echo
echo "== 2/5  pinned dependencies =="
make venv >/dev/null
echo "   ok"

echo
echo "== 3/5  full suite with the live engine required =="
FHIR_SULO_REQUIRE_ENGINE=1 FHIR_SULO_ENGINE_TESTS=1 \
  PYTHONPATH=src .venv/bin/python -m pytest tests -q

echo
echo "== 4/5  static analysis of every committed ShExMap pair =="
make lint-schemas

echo
echo "== 5/5  end to end: FHIR JSON -> maps -> store =="
STORE="$DEST/_verify-store"
PYTHONPATH=src .venv/bin/python -m fhir_sulo.pipeline.cli batch \
  --family egfr --quality-mode per-observation \
  --out "$DEST/_verify-batch.jsonl" --load "$STORE" \
  fixtures/r4/egfr/egfr-baseline/egfr-456.json >/dev/null
PYTHONPATH=src .venv/bin/python -m fhir_sulo.store.cli inspect \
  --state "$STORE/state.json" | grep -E "current_graphs|current_triples"

echo
echo "== clean clone verified =="
