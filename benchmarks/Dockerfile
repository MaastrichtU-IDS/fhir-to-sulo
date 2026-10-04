# The documented benchmark runner. Gate 4: "The benchmark processes 10,000
# synthetic resources on a documented 4-vCPU/8-GB runner within 15 minutes,
# with peak memory below 6 GB and no unexpected mapping failures."
#
# "Documented" is taken literally: this file IS the runner, so the number is
# reproducible on any machine with Docker rather than being whatever laptop
# produced it. The constraints (--cpus=4 --memory=8g) are applied at `docker
# run`, by benchmarks/run.sh, which refuses to run without them.
#
# One image, not two, so the host stages and the reasoning stage are measured
# in the SAME cgroup. Summing two separately-constrained containers would
# under-report peak memory, because the peak of a sum is not the sum of peaks.
#
# ROBOT comes from the image digest that validation/reasoning.py pins and that
# the PRO entailment was verified against - copied, not re-downloaded, so the
# benchmark cannot silently run a different build of the reasoner.

FROM obolibrary/robot@sha256:58da5acb0bb861ca84409213f2b6e15ab41eda145e602ef5cfdf87d974ec5976 AS robot

FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openjdk-17-jre-headless procps docker.io \
 && rm -rf /var/lib/apt/lists/*

# docker.io is the CLI only. The composed pipeline spawns the pinned ShExMap
# engine with `docker run`, and nested Docker is not available here, so
# run.sh mounts the host daemon's socket and those engine containers are
# SIBLINGS of this one. They are therefore NOT inside this container's
# --cpus=4 --memory=8g cgroup. run.sh says so and the report records it: the
# measured time is a lower bound, because the engine gets the whole host.

COPY --from=robot /tools/robot.jar /tools/robot.jar
RUN printf '#!/bin/sh\nexec java $ROBOT_JAVA_ARGS -jar /tools/robot.jar "$@"\n' > /usr/local/bin/robot \
 && chmod +x /usr/local/bin/robot

COPY requirements-runtime.txt /tmp/requirements-runtime.txt
RUN pip install --no-cache-dir -r /tmp/requirements-runtime.txt

ENV PYTHONPATH=/w/src:/w/benchmarks
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /w
