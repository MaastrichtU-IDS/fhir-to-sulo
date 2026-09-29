#!/bin/sh
# run.sh -- the Gate 4 benchmark, on the documented runner.
#
#   benchmarks/run.sh                 10,000 resources, default settings
#   benchmarks/run.sh -n 1000         a smaller trial
#   benchmarks/run.sh --skip-reasoning
#
# The constraints are NOT optional and are not a flag: a "4-vCPU/8-GB runner"
# that is actually a 14-core laptop measures the laptop. --cpus=4 --memory=8g
# are applied here, and the report reads them back out of the cgroup so the
# printed number states the envelope it was produced in.
#
# Colima shares only the VM owner's home directory, so bind mounts into a
# scratchpad do not work on the pilot host (DR-301 operational note). The tree
# is shipped in with `docker cp`, the same pattern tools/engine/run.sh uses.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
IMAGE=fhir-sulo-bench:1
CONTAINER=fhir-sulo-bench

CPUS=${BENCH_CPUS:-4}
MEMORY=${BENCH_MEMORY:-8g}

echo "== building the benchmark image (pinned ROBOT jar + pinned Python deps) =="
cp "$ROOT/requirements-runtime.txt" "$HERE/requirements-runtime.txt"
docker build -q -t "$IMAGE" -f "$HERE/Dockerfile" "$HERE" > /dev/null
rm -f "$HERE/requirements-runtime.txt"

echo "== starting the runner: --cpus=$CPUS --memory=$MEMORY =="
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
# The docker socket is mounted so the composed pipeline can spawn the pinned
# ShExMap engine. Those engine containers are SIBLINGS of this one and are
# therefore NOT inside this --cpus=4 --memory=8g cgroup: they get the whole
# host. The measured time is consequently a LOWER BOUND, and the report says
# so. Constraining them too needs an option on Agent 4's EngineImage, which
# hardcodes `docker run --rm -i`; requested, not worked around.
docker run -d --name "$CONTAINER" \
  --cpus="$CPUS" --memory="$MEMORY" --memory-swap="$MEMORY" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -w /w "$IMAGE" sleep infinity > /dev/null

docker exec "$CONTAINER" mkdir -p /w/src /w/benchmarks
docker cp "$ROOT/src" "$CONTAINER":/w/ > /dev/null
docker cp "$ROOT/benchmarks" "$CONTAINER":/w/ > /dev/null
docker cp "$ROOT/maps" "$CONTAINER":/w/ > /dev/null
docker cp "$ROOT/policies" "$CONTAINER":/w/ > /dev/null
docker cp "$ROOT/profiles" "$CONTAINER":/w/ > /dev/null 2>/dev/null || true
docker cp "$ROOT/tools" "$CONTAINER":/w/ > /dev/null

# --strictness is REQUIRED by run_benchmark.py: review item R5 is unanswered,
# so the policy default rejects and every gate artefact must name what it ran
# under. The wrapper supplies a default so `./benchmarks/run.sh` works with no
# arguments, and anything passed on the command line still wins because "$@"
# comes last. Naming it here is deliberate -- it appears in the report -- and
# is NOT an answer to R5.
STRICTNESS_DEFAULT="--strictness concept-note-literal"
case " $* " in *" --strictness "*) STRICTNESS_DEFAULT="" ;; esac

# Same reasoning: the quality identity policy (R2) has no default and rejects
# when unset, so the benchmark must name a mode to run at all.
QUALITY_DEFAULT="--quality-mode per-observation"
case " $* " in *" --quality-mode "*) QUALITY_DEFAULT="" ;; esac

echo "== running =="
set +e
# shellcheck disable=SC2086  # the defaults are two fixed flag pairs, not a path
docker exec "$CONTAINER" python3 /w/benchmarks/run_benchmark.py \
  --json /w/benchmark-report.json $STRICTNESS_DEFAULT $QUALITY_DEFAULT "$@"
STATUS=$?
set -e

docker cp "$CONTAINER":/w/benchmark-report.json "$HERE/last-report.json" 2>/dev/null \
  && echo "" && echo "JSON report: benchmarks/last-report.json"

docker rm -f "$CONTAINER" > /dev/null
exit $STATUS
