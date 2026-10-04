#!/bin/sh
# run.sh -- re-run every ShExMap engine probe from clean and print PASS/FAIL.
#
# HOST SIDE.  There is no node on this host and colima only shares the VM
# owner's home, so bind mounts into the scratchpad do not work; we ship the
# tree into a container with `docker cp` instead.
#
#   ./run.sh              full run (npm install + all probes)
#   ./run.sh --keep       reuse an existing container, skip npm install
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
IMAGE=node:20-bookworm-slim
C=shexprobe

if [ "$1" != "--keep" ] || ! docker exec $C true 2>/dev/null; then
  docker rm -f $C >/dev/null 2>&1 || true
  docker run -d --name $C -w /w $IMAGE sleep infinity >/dev/null
  docker cp "$HERE/package.json" $C:/w/package.json
  docker cp "$HERE/package-lock.json" $C:/w/package-lock.json
  echo "== npm ci (pinned) =="
  docker exec $C sh -c 'cd /w && npm ci --no-audit --no-fund' >/dev/null
fi
docker exec $C rm -rf /w/probes
docker cp "$HERE/probes" $C:/w/probes >/dev/null
docker cp "$HERE/verdicts.sh" $C:/w/verdicts.sh
docker exec $C sh /w/verdicts.sh
