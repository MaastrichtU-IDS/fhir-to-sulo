"""Run the pinned ShExMap engine in Docker, with nothing bind-mounted.

DR-301 recorded that this host runs colima, which shares only the VM owner's
home directory. A bind mount of any other path does not fail -- it silently
presents an **empty** directory, and the first symptom is a missing-file error
from inside the container. That is a trap for every agent, so the engine
interface here removes it: the image carries the pinned ``node_modules`` and
the bridge scripts, and every invocation is ``docker run --rm -i`` with the
request JSON on stdin and the response JSON on stdout.

No host path is mounted, so nothing depends on which user started the VM.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Optional

ENGINE_VERSION = "1.0.0-alpha.33"
TAG_PREFIX = "fhir-sulo/shexmap"
BRIDGE_DIR = "/srv/engine/bridge"

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
DEFAULT_CONTEXT = os.path.join(_REPO_ROOT, "tools", "engine")


def context_digest(context: str = DEFAULT_CONTEXT) -> str:
    """A short hash of everything that goes into the image.

    The tag carries it, so the tag is content-addressed. It has to be:
    several agent worktrees share one Docker daemon, ``ensure_built()``
    is a no-op when the tag exists, and a plain version tag is therefore
    shared mutable state -- whoever built last wins, and everyone else runs
    an image that does not match their source tree. That was not a
    hypothetical; it silently reverted the bridge under a passing test run.
    """
    digest = hashlib.sha256()
    for name in ("package.json", "package-lock.json", "Dockerfile"):
        path = os.path.join(context, name)
        if os.path.exists(path):
            with open(path, "rb") as handle:
                digest.update(name.encode())
                digest.update(handle.read())
    bridge = os.path.join(context, "bridge")
    for name in sorted(os.listdir(bridge)) if os.path.isdir(bridge) else ():
        path = os.path.join(bridge, name)
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                digest.update(name.encode())
                digest.update(handle.read())
    return digest.hexdigest()[:12]


def default_tag(context: str = DEFAULT_CONTEXT) -> str:
    return f"{TAG_PREFIX}:{ENGINE_VERSION}-{context_digest(context)}"


#: Kept for callers that only want to name the family of images.
DEFAULT_TAG = f"{TAG_PREFIX}:{ENGINE_VERSION}"


class EngineUnavailable(RuntimeError):
    """Docker, or the pinned image, is not usable here."""


class EngineInvocationError(RuntimeError):
    """The bridge could not be run at all (as distinct from returning a failure)."""


@dataclass(frozen=True)
class EngineImage:
    """A built, pinned engine image and the calls it answers."""

    tag: str = ""
    context: str = DEFAULT_CONTEXT
    timeout_seconds: int = 300
    #: Hold the engine to the same envelope as its caller. The Gate 4 runner
    #: is capped at --cpus=4 --memory=8g, but engine containers are its
    #: SIBLINGS and were outside that cgroup, so the measured figures were a
    #: lower bound. Setting these puts the engine inside the same envelope.
    cpus: Optional[str] = None
    memory: Optional[str] = None
    #: A resident engine, created on first use and reused. `call` goes through
    #: it, so the 0.339 s container start-up is paid once per process instead
    #: of once per request.
    reuse_process: bool = True

    _session: Any = None

    def __post_init__(self) -> None:
        if not self.tag:
            object.__setattr__(self, "tag", default_tag(self.context))

    # -- availability -------------------------------------------------------

    @staticmethod
    def docker_present() -> bool:
        if shutil.which("docker") is None:
            return False
        try:
            return subprocess.run(
                ["docker", "info"], capture_output=True, timeout=60
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def exists(self) -> bool:
        try:
            return subprocess.run(
                ["docker", "image", "inspect", self.tag],
                capture_output=True, timeout=60,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def ensure_built(self, rebuild: bool = False) -> None:
        """Build the image from the committed lockfile if it is not present."""
        if not self.docker_present():
            raise EngineUnavailable("docker is not available on this host")
        if self.exists() and not rebuild:
            return
        proc = subprocess.run(
            ["docker", "build", "-t", self.tag, self.context],
            capture_output=True, text=True, timeout=1800,
        )
        if proc.returncode != 0:
            raise EngineUnavailable(
                f"docker build of {self.tag} failed:\n{proc.stderr[-4000:]}"
            )

    # -- identity -----------------------------------------------------------

    def build_id(self) -> str:
        """A value for ``RunRecord.engine_build``: the image's content id.

        The tag alone is not an identity -- it can be rebuilt. The image id is
        what actually produced the graph.
        """
        proc = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", self.tag],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            raise EngineUnavailable(f"image {self.tag} is not built")
        return f"{self.tag}@{proc.stdout.strip()}"

    # -- calls --------------------------------------------------------------

    # -- the resident engine ------------------------------------------------

    def session(self):
        """The resident engine for this image, started on first use."""
        from .session import EngineSession

        existing = object.__getattribute__(self, "_session")
        if existing is not None and existing.is_running:
            return existing
        created = EngineSession(image=self, cpus=self.cpus, memory=self.memory,
                                timeout_seconds=self.timeout_seconds).start()
        object.__setattr__(self, "_session", created)
        return created

    def close(self) -> None:
        existing = object.__getattribute__(self, "_session")
        if existing is not None:
            existing.close()
            object.__setattr__(self, "_session", None)

    def call(self, script: str, request: Mapping[str, Any]) -> Any:
        """Run one bridge operation. Returns its parsed JSON response.

        By default this goes to the resident engine: same JSON-on-stdin
        transport, same image, but the container is not torn down after one
        request. `reuse_process=False` restores the one-shot `docker run` per
        call, which is what the recorded-fixture tests use so that the
        one-shot bridges stay exercised.

        A bridge reports its *own* failures inside the JSON (``ok: false``);
        that is a result, not an error, and is returned to the caller. Only a
        failure to run the bridge at all raises here.
        """
        if self.reuse_process:
            op = _SCRIPT_OPS.get(script)
            if op is not None:
                return self.session().call(dict(request, op=op))
        payload = json.dumps(request)
        try:
            proc = subprocess.run(
                ["docker", "run", "--rm", "-i", self.tag,
                 "node", f"{BRIDGE_DIR}/{script}"],
                input=payload, capture_output=True, text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise EngineInvocationError(
                f"{script} exceeded {self.timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise EngineInvocationError(f"could not run docker: {exc}") from exc

        if not proc.stdout.strip():
            raise EngineInvocationError(
                f"{script} produced no response (exit {proc.returncode}); "
                f"stderr:\n{proc.stderr[-4000:]}"
            )
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise EngineInvocationError(
                f"{script} response was not JSON: {exc}\n{proc.stdout[:2000]}"
            ) from exc

    def parse_schema(self, shexc: str, base_iri: str) -> Mapping[str, Any]:
        """ShExC -> ``{ok, schema, prefixes}`` via the engine's own parser."""
        return self.call("parse.js", {"schema": shexc, "baseIRI": base_iri})

    def run_pass(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """One validate-and-materialize pass. See ``bridge/run-pass.js``."""
        return self.call("run-pass.js", request)


#: Bridge script -> the resident server's op name. A script with no op here
#: still runs one-shot, so adding a bridge does not silently route nowhere.
_SCRIPT_OPS = {
    "run-map.js": "run-map",
    "parse.js": "parse",
}


_SHARED: "dict[tuple, EngineImage]" = {}


def default_image(tag: Optional[str] = None) -> EngineImage:
    """The image for *this* working tree's bridge and lockfile.

    Shared per (tag, cpus, memory) within a process, so that N pipelines mean
    one resident engine rather than N. The benchmark builds a pipeline per map
    family; three containers would be three start-ups and three memory figures
    for no benefit.

    ``FHIR_SULO_ENGINE_IMAGE`` pins a prebuilt image (how CI does it);
    otherwise the tag is derived from the build context, so two worktrees with
    different bridges cannot share, and silently swap, one tag (CD-5).
    ``FHIR_SULO_ENGINE_CPUS`` and ``FHIR_SULO_ENGINE_MEMORY`` hold the engine
    to a resource envelope -- it is a sibling container, so a runner capped at
    4 CPUs does not otherwise constrain it, and the benchmark's figures were a
    lower bound because of exactly that.
    """
    key = (tag or os.environ.get("FHIR_SULO_ENGINE_IMAGE", ""),
           os.environ.get("FHIR_SULO_ENGINE_CPUS") or None,
           os.environ.get("FHIR_SULO_ENGINE_MEMORY") or None)
    existing = _SHARED.get(key)
    if existing is not None:
        return existing
    created = EngineImage(tag=key[0], cpus=key[1], memory=key[2])
    _SHARED[key] = created
    return created
