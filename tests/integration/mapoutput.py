"""Access to the **real** emitted target graphs, for the Gate 2/3/4 suites.

Why this exists
---------------
Agent 6's reasoning, SHACL and competency suites originally ran on
hand-written graphs in ``tests/integration/graphs/``. An independent review
pointed out that those graphs are not what the maps emit:

=================== ============================== ==========================
                    hand-written                   real map output
=================== ============================== ==========================
person IRI          ``ex:person-p123``             ``person-<32 hex>``
person type         ``sulo:SpatialObject``         ``sulo:Object``
quality type        ``sulo:Feature``               ``sulo:Quality``
time datatype       ``xsd:dateTimeStamp``          ``xsd:dateTime``
=================== ============================== ==========================

The properties happen to hold on both, so this was not a correctness bug. But
a Gate 3 condition backed by a graph nobody's pipeline produces establishes
nothing, and would not notice the map drifting. So the suites now run against
``fixtures/expected/*/*/target.nt`` — the graphs Agent 3's maps actually
produce, regenerated and drift-checked by ``fixtures/expected/build.py``.

The hand-written graphs are kept only where they are genuinely minimal units
with no real-map equivalent: ``negatives.ttl`` (deliberately malformed graphs
that no correct map would emit) and ``bp-cross-join.ttl`` (the failure mode
the BP pairing test must be able to detect).

Ownership note: this module only **reads** ``fixtures/``, which Agents 2 and 3
own. Nothing here writes to it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import support  # noqa: F401  (sets sys.path)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPECTED = os.path.join(REPO, "fixtures", "expected")

EX = "https://example.org/fhir-sulo/"
SULO = "https://w3id.org/sulo/"

SYSTOLIC_QUALITY = EX + "SystolicBloodPressureQuality"
DIASTOLIC_QUALITY = EX + "DiastolicBloodPressureQuality"


@dataclass(frozen=True)
class MapOutput:
    """One fixture's declared outcome, and its emitted graph if it has one."""

    family: str
    fixture_id: str
    directory: str
    outcome: Dict[str, object]

    @property
    def map_outcome(self) -> str:
        return str(self.outcome.get("map_outcome", ""))

    @property
    def is_mapped(self) -> bool:
        return self.map_outcome == "mapped"

    @property
    def target_path(self) -> Optional[str]:
        path = os.path.join(self.directory, "target.nt")
        return path if os.path.exists(path) else None

    @property
    def quality_identity_mode(self) -> Optional[str]:
        """Which answer to review item R2 this graph was generated under.

        Recorded by ``fixtures/expected/build.py`` in every ``outcome.json``.
        Read here rather than assumed, so a suite that depends on the mode
        says so and a change to it is visible in the test output.
        """
        params = self.outcome.get("run_parameters") or {}
        return params.get("quality_identity_mode")  # type: ignore[union-attr]

    def triples(self) -> str:
        """The emitted N-Triples, comment lines stripped."""
        path = self.target_path
        if path is None:
            raise FileNotFoundError(
                "%s/%s has no target.nt: its declared outcome is %r"
                % (self.family, self.fixture_id, self.map_outcome)
            )
        with open(path, encoding="utf-8") as handle:
            return "\n".join(
                line for line in handle.read().splitlines()
                if line.strip() and not line.startswith("#")
            )

    def graph(self):
        import rdflib

        graph = rdflib.Graph()
        graph.parse(data=self.triples(), format="nt")
        return graph


def _load_all() -> Tuple[MapOutput, ...]:
    found: List[MapOutput] = []
    if not os.path.isdir(EXPECTED):
        return ()
    for family in sorted(os.listdir(EXPECTED)):
        family_dir = os.path.join(EXPECTED, family)
        if not os.path.isdir(family_dir):
            continue
        for fixture_id in sorted(os.listdir(family_dir)):
            directory = os.path.join(family_dir, fixture_id)
            outcome_path = os.path.join(directory, "outcome.json")
            if not os.path.exists(outcome_path):
                continue
            with open(outcome_path, encoding="utf-8") as handle:
                outcome = json.load(handle)
            found.append(MapOutput(family, fixture_id, directory, outcome))
    return tuple(found)


ALL = _load_all()
MAPPED = tuple(m for m in ALL if m.target_path is not None)
AVAILABLE = bool(MAPPED)

SKIP_NO_FIXTURES = (
    "needs Agent 3's expected graphs under fixtures/expected/ "
    "(run fixtures/expected/build.py)"
)



def _subject_of(item: "MapOutput"):
    """(resource identity, version) for a mapped fixture.

    Read from the FHIR source document under ``fixtures/r4/``, because
    ``outcome.json`` records the map result and not the source version.
    Identity is ``resourceType/id`` -- two fixtures are versions of the same
    resource exactly when those match.
    """
    import glob as _glob

    src_dir = os.path.join(REPO, "fixtures", "r4", item.family, item.fixture_id)
    for path in sorted(_glob.glob(os.path.join(src_dir, "*.json"))):
        name = os.path.basename(path)
        if name in ("case.json", "expected-bindings.json", "outcome.json"):
            continue
        try:
            doc = json.loads(open(path, encoding="utf-8").read())
        except Exception:
            continue
        rtype, rid = doc.get("resourceType"), doc.get("id")
        if not (rtype and rid):
            continue
        ver = ((doc.get("meta") or {}).get("versionId"))
        try:
            ver_n = int(ver)
        except (TypeError, ValueError):
            ver_n = None
        return "%s/%s" % (rtype, rid), ver_n
    return None, None


CURRENT_MAPPED = None
"""Mapped fixtures minus superseded versions of the same resource.

`egfr-456` now ships at v1, v2 and v3. v1 and v2 both emit the SAME result
node IRI -- that is the point of the correction scenario, and it is why the
store replaces rather than accumulates. So a naive union of every mapped
fixture is not a graph the pipeline would ever produce: the shared quantity
node ends up with two `sulo:hasValue` literals, which violates DR-002
axiom 1 (hasValue is functional).

A graph-wide conformance check must therefore merge the CURRENT graphs --
one per subject -- exactly as the store holds them.
"""


def _compute_current_mapped():
    """Drop only SUPERSEDED versions, never variants.

    Several BP fixtures reuse `Observation/bp-1` at versionId 1 --
    `bp-two-panels`, `bp-reordered-serialisation`, `bp-component-omitted`,
    `bp-other-patient`. Those are alternative scenarios, not a version
    history, and they merged fine before the lineage fixtures arrived.
    Collapsing them would silently shrink the batch and weaken the
    graph-wide orphan and cross-patient checks.

    So a fixture is superseded only when another fixture has the same
    resource identity AND a strictly greater versionId.
    """
    versions = {}
    for item in MAPPED:
        ident, ver = _subject_of(item)
        if ident is None or ver is None:
            continue
        versions.setdefault(ident, set()).add(ver)

    keep = []
    for item in MAPPED:
        ident, ver = _subject_of(item)
        if ident is None or ver is None:
            keep.append(item)
            continue
        if ver < max(versions[ident]):
            continue          # superseded by a later version of this resource
        keep.append(item)
    return tuple(sorted(keep, key=lambda m: m.fixture_id))


def by_id(fixture_id: str) -> MapOutput:
    for item in ALL:
        if item.fixture_id == fixture_id:
            return item
    raise KeyError(
        "no expected-output fixture %r; have: %s"
        % (fixture_id, ", ".join(sorted(i.fixture_id for i in ALL)))
    )


def iso_z(value: str) -> str:
    """Normalise an ``xsd:dateTime`` string to the ``Z`` spelling.

    The maps emit ``"2026-09-02T14:00:00Z"^^xsd:dateTime``. rdflib parses that
    into a ``datetime`` and renders it back as ``2026-09-02T14:00:00+00:00``,
    which is the same instant spelled differently. Tests compare instants, not
    spellings, so they go through here rather than hard-coding whichever form
    the current rdflib happens to produce.

    Worth noting for the record: the earlier hand-written graphs used
    ``xsd:dateTimeStamp``, which rdflib has no Python mapping for, so the
    lexical form survived untouched and this difference never showed up.
    """
    return value.replace("+00:00", "Z")


def merged_graph(*fixture_ids: str):
    """One graph holding several fixtures' output, as a batch would deliver."""
    import rdflib

    graph = rdflib.Graph()
    for fixture_id in fixture_ids:
        graph.parse(data=by_id(fixture_id).triples(), format="nt")
    return graph

CURRENT_MAPPED = _compute_current_mapped()
