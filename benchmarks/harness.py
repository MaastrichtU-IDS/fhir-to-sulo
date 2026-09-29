"""Stage timing and peak-memory measurement for the Gate 4 benchmark.

Peak memory is read from the **cgroup**, not from ``resource.getrusage``.
Inside a ``--memory=8g`` container the cgroup peak is what the limit applies
to and what an operator would see; ``ru_maxrss`` reports only this process's
resident set, so it would miss the JVM the reasoner forks - which is the
single largest consumer in the pipeline. Where no cgroup is readable (running
on the host rather than in the container) the harness says so in the report
instead of quietly substituting a smaller number.
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

__all__ = [
    "StageResult",
    "BenchmarkReport",
    "Timer",
    "read_peak_memory_bytes",
    "describe_environment",
]

CGROUP_V2_PEAK = "/sys/fs/cgroup/memory.peak"
CGROUP_V2_CURRENT = "/sys/fs/cgroup/memory.current"
CGROUP_V1_PEAK = "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"


def read_peak_memory_bytes() -> Optional[int]:
    """Peak memory for the whole cgroup, including forked JVMs. None if unknown."""
    for path in (CGROUP_V2_PEAK, CGROUP_V1_PEAK):
        try:
            with open(path) as handle:
                return int(handle.read().strip())
        except (OSError, ValueError):
            continue
    return None


def read_current_memory_bytes() -> Optional[int]:
    try:
        with open(CGROUP_V2_CURRENT) as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def process_maxrss_bytes() -> int:
    """This process's peak RSS. Reported alongside, never instead of, the cgroup."""
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes, macOS bytes.
    return value if value > 1 << 32 else value * 1024


@dataclass
class StageResult:
    name: str
    seconds: float
    items: int
    peak_memory_bytes: Optional[int]
    peak_memory_source: str
    process_maxrss_bytes: int
    detail: Dict[str, object] = field(default_factory=dict)
    failed: bool = False
    failure: str = ""

    @property
    def throughput(self) -> float:
        return (self.items / self.seconds) if self.seconds > 0 else 0.0

    def line(self) -> str:
        if self.failed:
            return "%-26s FAILED  %s" % (self.name, self.failure)
        peak = (
            "%.2f GB (%s)" % (self.peak_memory_bytes / 1e9, self.peak_memory_source)
            if self.peak_memory_bytes is not None
            else "unknown (%s)" % self.peak_memory_source
        )
        return "%-26s %8.2f s  %10.1f items/s  peak %s" % (
            self.name, self.seconds, self.throughput, peak
        )


class Timer:
    """Times one stage and records the cgroup peak observed during it."""

    def __init__(self, name: str, items: int) -> None:
        self.name = name
        self.items = items
        self.detail: Dict[str, object] = {}
        self._start = 0.0
        self.result: Optional[StageResult] = None

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, _tb) -> bool:
        seconds = time.perf_counter() - self._start
        peak = read_peak_memory_bytes()
        self.result = StageResult(
            name=self.name,
            seconds=seconds,
            items=self.items,
            peak_memory_bytes=peak,
            peak_memory_source="cgroup" if peak is not None else "no cgroup readable",
            process_maxrss_bytes=process_maxrss_bytes(),
            detail=self.detail,
            failed=exc is not None,
            failure="%s: %s" % (exc_type.__name__, exc) if exc is not None else "",
        )
        return False  # never swallow


@dataclass
class BenchmarkReport:
    resources: int
    stages: List[StageResult] = field(default_factory=list)
    environment: Dict[str, object] = field(default_factory=dict)
    failure_categories: Dict[str, int] = field(default_factory=dict)

    TIME_LIMIT_SECONDS = 15 * 60
    MEMORY_LIMIT_BYTES = 6 * 10 ** 9

    @property
    def total_seconds(self) -> float:
        return sum(s.seconds for s in self.stages)

    @property
    def peak_memory_bytes(self) -> Optional[int]:
        peaks = [s.peak_memory_bytes for s in self.stages if s.peak_memory_bytes]
        return max(peaks) if peaks else None

    @property
    def within_time_budget(self) -> bool:
        return self.total_seconds <= self.TIME_LIMIT_SECONDS

    @property
    def within_memory_budget(self) -> Optional[bool]:
        peak = self.peak_memory_bytes
        return None if peak is None else peak <= self.MEMORY_LIMIT_BYTES

    @property
    def passed(self) -> bool:
        return (
            self.within_time_budget
            and self.within_memory_budget is True
            and not any(s.failed for s in self.stages)
        )

    def text(self) -> str:
        lines = [
            "FHIR-to-SULO Gate 4 benchmark",
            "=" * 78,
            "resources:      %d" % self.resources,
        ]
        for key in sorted(self.environment):
            lines.append("%-15s %s" % (key + ":", self.environment[key]))
        lines.append("")
        lines.append("stages")
        lines.append("-" * 78)
        for stage in self.stages:
            lines.append("  " + stage.line())
            for key in sorted(stage.detail):
                lines.append("      %-22s %s" % (key, stage.detail[key]))
        lines.append("-" * 78)
        lines.append(
            "TOTAL            %8.2f s  (%.1f min)  throughput %.1f resources/s"
            % (
                self.total_seconds,
                self.total_seconds / 60.0,
                self.resources / self.total_seconds if self.total_seconds else 0.0,
            )
        )
        peak = self.peak_memory_bytes
        lines.append(
            "PEAK MEMORY      %s"
            % ("%.2f GB" % (peak / 1e9) if peak else "unknown (not in a cgroup)")
        )
        lines.append("")
        lines.append("failure categories")
        lines.append("-" * 78)
        if self.failure_categories:
            for name in sorted(self.failure_categories):
                lines.append("  %-40s %d" % (name, self.failure_categories[name]))
        else:
            lines.append("  none")
        lines.append("")
        lines.append("Gate 4 targets")
        lines.append("-" * 78)
        lines.append(
            "  time   <= 15 min   : %s (%.1f min)"
            % ("PASS" if self.within_time_budget else "MISS", self.total_seconds / 60.0)
        )
        budget = self.within_memory_budget
        lines.append(
            "  memory <= 6 GB     : %s"
            % ("PASS" if budget else ("MISS" if budget is False else "NOT MEASURED"))
        )
        lines.append("  VERDICT            : %s" % ("PASS" if self.passed else "MISS"))
        return "\n".join(lines)

    def json(self) -> str:
        return json.dumps(
            {
                "resources": self.resources,
                "environment": self.environment,
                "total_seconds": round(self.total_seconds, 3),
                "peak_memory_bytes": self.peak_memory_bytes,
                "within_time_budget": self.within_time_budget,
                "within_memory_budget": self.within_memory_budget,
                "passed": self.passed,
                "failure_categories": self.failure_categories,
                "stages": [
                    {
                        "name": s.name,
                        "seconds": round(s.seconds, 3),
                        "items": s.items,
                        "throughput_per_second": round(s.throughput, 2),
                        "peak_memory_bytes": s.peak_memory_bytes,
                        "peak_memory_source": s.peak_memory_source,
                        "failed": s.failed,
                        "failure": s.failure,
                        "detail": s.detail,
                    }
                    for s in self.stages
                ],
            },
            indent=2,
            sort_keys=True,
        )


def describe_environment() -> Dict[str, object]:
    import platform
    import sys

    env: Dict[str, object] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
    }
    try:
        with open("/sys/fs/cgroup/memory.max") as handle:
            raw = handle.read().strip()
        env["cgroup_memory_max"] = raw if raw == "max" else "%.1f GB" % (int(raw) / 1e9)
    except OSError:
        env["cgroup_memory_max"] = "not in a cgroup v2"
    try:
        with open("/sys/fs/cgroup/cpu.max") as handle:
            quota, period = handle.read().split()
        env["cgroup_cpus"] = (
            "unlimited" if quota == "max" else "%.2f" % (int(quota) / int(period))
        )
    except (OSError, ValueError):
        env["cgroup_cpus"] = "not in a cgroup v2"
    try:
        env["java"] = subprocess.run(
            ["java", "-version"], capture_output=True, text=True
        ).stderr.splitlines()[0]
    except (OSError, IndexError):
        env["java"] = "not present"
    return env
