# Pinned ShExMap engine image (DR-301).
#
# Built from the committed lockfile so the image is reproducible. The bridge
# scripts are baked in and every invocation is `docker run --rm -i` with the
# request on stdin and the response on stdout: nothing is bind-mounted.
#
# That is deliberate. DR-301 records that this host runs colima, which shares
# only the VM owner's home, so a bind mount into a scratch or repo directory
# silently produces an EMPTY directory rather than an error. Passing every
# input on stdin removes the failure mode instead of documenting it.
# Pinned by digest, not by tag: `node:20-bookworm-slim` moves, so a tag alone
# pins the npm lockfile and not the runtime under it. This is the digest
# DR-301's probes ran against.
FROM node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

WORKDIR /srv/engine
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund && npm cache clean --force

# Under /srv/engine, so Node's resolver walks up to /srv/engine/node_modules.
COPY bridge/ /srv/engine/bridge/

# No ENTRYPOINT: the caller names the bridge script, so one image serves
# `parse`, `bindings` and `materialize` without a dispatcher to keep in sync.
CMD ["node", "--version"]
