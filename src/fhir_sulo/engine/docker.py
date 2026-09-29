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

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Optional

DEFAULT_TAG = "fhir-sulo/shexmap:1.0.0-alpha.33"
BRIDGE_DIR = "/srv/engine/bridge"

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
DEFAULT_CONTEXT = os.path.join(_REPO_ROOT, "tools", "engine")


class EngineUnavailable(RuntimeError):
    """Docker, or the pinned image, is not usable here."""


class EngineInvocationError(RuntimeError):
    """The bridge could not be run at all (as distinct from returning a failure)."""


@dataclass(frozen=True)
class EngineImage:
    """A built, pinned engine image and the calls it answers."""

    tag: str = DEFAULT_TAG
    context: str = DEFAULT_CONTEXT
    timeout_seconds: int = 300

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

    def call(self, script: str, request: Mapping[str, Any]) -> Any:
        """Run one bridge script. Returns its parsed JSON response.

        A bridge reports its *own* failures inside the JSON (``ok: false``) and
        exits 1; that is a result, not an error, and is returned to the caller.
        Only a failure to run the bridge at all raises here.
        """
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


def default_image(tag: Optional[str] = None) -> EngineImage:
    return EngineImage(tag=tag or os.environ.get("FHIR_SULO_ENGINE_IMAGE", DEFAULT_TAG))
