"""A resident engine process, owned by exactly one host process.

The Gate 4 benchmark measured `materialize` at 0.472 s per resource, of which
0.339 s was `docker run` start-up paid twice -- once to bind, once to
materialize -- against 0.030 ms of actual materialization. The fix is not to
make the engine faster; it is to stop starting it twenty thousand times.

Three properties are deliberate, and each one is a bug that was already paid
for once:

* **No bind mount.** The transport is still JSON on stdin and stdout. DR-301:
  on this host an unshared bind mount does not fail, it silently presents an
  empty directory.
* **No container name.** A named long-lived container is shared mutable state
  between agent worktrees, which is where CD-5 came from. This container is
  anonymous, is owned by one :class:`EngineSession`, and is not discoverable
  by anything else.
* **Shutdown is not a cleanup step anyone has to remember.** The container
  lives exactly as long as its stdin. When the owning process exits -- even
  by SIGKILL -- the pipe closes, node exits, and ``--rm`` removes the
  container.

The session is single-threaded by construction: one request is written, one
response is read. Sharing one across threads would interleave the framing, so
:meth:`EngineSession.call` takes a lock and says so.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import tempfile
import threading
import weakref
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .docker import BRIDGE_DIR, EngineImage, EngineInvocationError, default_image

SERVER = f"{BRIDGE_DIR}/server.js"

#: Every live session, so the interpreter cannot exit leaving containers up.
_LIVE: "weakref.WeakSet[EngineSession]" = weakref.WeakSet()


def _close_all() -> None:
    for session in list(_LIVE):
        try:
            session.close()
        except Exception:  # noqa: BLE001 - best effort at shutdown
            pass


atexit.register(_close_all)


class EngineSessionClosed(EngineInvocationError):
    """The resident engine is gone, and the call that needed it did not run."""


@dataclass(eq=False)
class EngineSession:
    """A long-lived engine process. Use as a context manager."""

    image: EngineImage = field(default_factory=default_image)
    #: passed to ``docker run`` so the engine can be held to the same envelope
    #: as its caller; the benchmark's sibling containers were outside its cgroup
    cpus: Optional[str] = None
    memory: Optional[str] = None
    timeout_seconds: int = 600

    _process: Optional[subprocess.Popen] = field(default=None, init=False, repr=False)
    _cidfile: Optional[str] = field(default=None, init=False, repr=False)
    _container_id: Optional[str] = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _counter: int = field(default=0, init=False, repr=False)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> "EngineSession":
        if self._process is not None and self._process.poll() is None:
            return self
        self.image.ensure_built()
        # --cidfile so the container can be found again for `docker stats`.
        # With one resident container per run instead of twenty thousand
        # short-lived ones, engine memory is finally a number that can be
        # read rather than estimated -- the benchmark previously had to
        # report its own cgroup and note that the siblings were outside it.
        handle_fd, cidpath = tempfile.mkstemp(prefix="fhir-sulo-engine-", suffix=".cid")
        os.close(handle_fd)
        os.unlink(cidpath)          # docker refuses to write an existing cidfile
        self._cidfile = cidpath
        command = ["docker", "run", "--rm", "-i", "--init", "--cidfile", cidpath]
        if self.cpus:
            command += ["--cpus", str(self.cpus)]
        if self.memory:
            command += ["--memory", str(self.memory), "--memory-swap", str(self.memory)]
        command += [self.image.tag, "node", SERVER]
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
            )
        except OSError as exc:
            raise EngineInvocationError(f"could not start the engine: {exc}") from exc
        _LIVE.add(self)
        # Prove it is up before the first real request, so a broken image
        # fails here rather than inside a 10,000-resource run.
        pong = self.call({"op": "ping"})
        if not pong.get("ok"):
            self.close()
            raise EngineInvocationError(f"engine did not answer ping: {pong}")
        return self

    def close(self) -> None:
        process, self._process = self._process, None
        cidfile, self._cidfile = self._cidfile, None
        if cidfile and os.path.exists(cidfile):
            try:
                os.unlink(cidfile)
            except OSError:
                pass
        if process is None:
            return
        _LIVE.discard(self)
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            process.wait(timeout=20)
        except Exception:  # noqa: BLE001
            process.kill()
            try:
                process.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "EngineSession":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # -- calls --------------------------------------------------------------

    def call(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        """One request, one response. Serialised: the framing is a pipe."""
        with self._lock:
            return self._call_locked(request)

    def _call_locked(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        process = self._process
        if process is None or process.poll() is not None:
            raise EngineSessionClosed(
                "the resident engine is not running"
                + (f" (exit {process.poll()})" if process is not None else ""))
        self._counter += 1
        payload = dict(request)
        payload["id"] = self._counter
        line = json.dumps(payload)
        try:
            process.stdin.write(line + "\n")
            process.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise EngineSessionClosed(
                f"the resident engine closed its input: {exc}\n{self._stderr_tail()}"
            ) from exc

        response_line = process.stdout.readline()
        if response_line == "":
            code = process.poll()
            raise EngineSessionClosed(
                f"the resident engine exited (status {code}) without answering; "
                f"stderr:\n{self._stderr_tail()}")
        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise EngineInvocationError(
                f"engine response was not JSON: {exc}\n{response_line[:2000]}") from exc
        if response.get("id") != payload["id"]:
            # Framing has slipped; every later answer would be misattributed,
            # so the session is finished rather than resynchronised.
            self.close()
            raise EngineInvocationError(
                f"engine response id {response.get('id')!r} does not match request "
                f"{payload['id']!r}; the session is out of step and has been closed")
        return response

    # -- measurement --------------------------------------------------------

    @property
    def container_id(self) -> Optional[str]:
        if self._container_id is None and self._cidfile and os.path.exists(self._cidfile):
            try:
                with open(self._cidfile, encoding="utf-8") as handle:
                    self._container_id = handle.read().strip() or None
            except OSError:
                return None
        return self._container_id

    def memory_bytes(self) -> Optional[int]:
        """Current resident-engine memory, or None if it cannot be read.

        Reported separately from the caller's own cgroup, because the engine
        is a sibling container and always was. What changed is that there is
        now one of it, so the figure is worth reading.
        """
        cid = self.container_id
        if not cid:
            return None
        try:
            proc = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", cid],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0 or "/" not in proc.stdout:
            return None
        return _parse_size(proc.stdout.split("/")[0].strip())

    def _stderr_tail(self) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return "(no stderr)"
        try:
            os.set_blocking(process.stderr.fileno(), False)
            return (process.stderr.read() or "")[-4000:]
        except Exception:  # noqa: BLE001
            return "(stderr unavailable)"

    # -- named operations ---------------------------------------------------

    def parse_schema(self, shexc: str, base_iri: str) -> Dict[str, Any]:
        return self.call({"op": "parse", "schema": shexc, "baseIRI": base_iri})

    def run_map(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        return self.call(dict(request, op="run-map"))

    def run_map_batch(
        self, requests: Sequence[Mapping[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Many map jobs in one round trip, answered in the order given.

        Safe under DR-302: every map is rooted at one FHIR resource and
        nothing crosses resources, so a batch is N independent runs sharing a
        process. Each item is answered on its own, so one resource failing
        cannot abandon the rest of the batch.
        """
        if not requests:
            return []
        items = [{"id": index, "request": dict(request)}
                 for index, request in enumerate(requests)]
        response = self.call({"op": "run-map-batch", "items": items})
        if not response.get("ok"):
            raise EngineInvocationError(
                f"batch failed as a whole: {response.get('error')}")
        by_id = {entry["id"]: entry["response"] for entry in response["results"]}
        missing = [index for index in range(len(requests)) if index not in by_id]
        if missing:
            raise EngineInvocationError(
                f"the engine answered {len(by_id)} of {len(requests)} batch items; "
                f"{len(missing)} unanswered. A partial batch silently dropping "
                f"resources is the failure mode this check exists for")
        return [by_id[index] for index in range(len(requests))]


def open_session(
    image: Optional[EngineImage] = None,
    cpus: Optional[str] = None,
    memory: Optional[str] = None,
) -> EngineSession:
    return EngineSession(image=image or default_image(), cpus=cpus,
                         memory=memory).start()


_UNITS = {"b": 1, "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3,
          "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3}


def _parse_size(text: str) -> Optional[int]:
    """`docker stats` prints e.g. `152.3MiB`."""
    text = text.strip().lower()
    for suffix, factor in sorted(_UNITS.items(), key=lambda kv: -len(kv[0])):
        if text.endswith(suffix):
            try:
                return int(float(text[: -len(suffix)]) * factor)
            except ValueError:
                return None
    return None
