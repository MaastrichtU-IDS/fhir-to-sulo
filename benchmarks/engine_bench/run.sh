#!/bin/sh
# run.sh -- measure the pinned ShExMap engine on the documented runner.
#
#   benchmarks/engine_bench/run.sh
#
# Separate from benchmarks/run.sh because the engine needs Node and the host
# pipeline needs Python + a JVM, and because the maps this runs are a
# performance stand-in rather than Agent 3's reviewed pairs. Same constraints
# (--cpus=4 --memory=8g) so the two numbers can be added.
#
# There is no node on the pilot host, and Colima shares only the VM owner's
# home directory, so the tree goes in with `docker cp` (DR-301 operational
# note; tools/engine/run.sh does the same).
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
IMAGE=node:20-bookworm-slim
C=fhir-sulo-engine-bench

CPUS=${BENCH_CPUS:-4}
MEMORY=${BENCH_MEMORY:-8g}

echo "== starting the runner: --cpus=$CPUS --memory=$MEMORY =="
docker rm -f $C >/dev/null 2>&1 || true
docker run -d --name $C --cpus="$CPUS" --memory="$MEMORY" --memory-swap="$MEMORY" \
  -w /w $IMAGE sleep infinity > /dev/null

docker cp "$HERE/package.json" $C:/w/package.json
if [ -f "$HERE/package-lock.json" ]; then
  docker cp "$HERE/package-lock.json" $C:/w/package-lock.json
  echo "== npm ci (pinned lockfile) =="
  docker exec $C sh -c 'cd /w && npm ci --no-audit --no-fund' > /dev/null
else
  echo "== npm install (no lockfile yet; commit one after the first run) =="
  docker exec $C sh -c 'cd /w && npm install --no-audit --no-fund' > /dev/null
  docker cp $C:/w/package-lock.json "$HERE/package-lock.json"
fi

docker exec $C mkdir -p /w/engine_bench
docker cp "$HERE/bench.js"    $C:/w/engine_bench/bench.js
docker cp "$HERE/source.shex" $C:/w/engine_bench/source.shex
docker cp "$HERE/target.shex" $C:/w/engine_bench/target.shex

echo "== running =="
set +e
docker exec -e BENCH_A -e BENCH_B $C node /w/engine_bench/bench.js
STATUS=$?
set -e

echo ""
echo "== peak memory (cgroup) =="
docker exec $C sh -c 'cat /sys/fs/cgroup/memory.peak 2>/dev/null || cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes 2>/dev/null || echo unknown'

docker rm -f $C > /dev/null
exit $STATUS
