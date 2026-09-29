"""Read a map's run-binding manifest: the declaration both tools work from.

``maps/r4/<family>/<family>-bindings.v1.json`` is the single indirection point
Agent 3 built. It names, for one map:

* the variable and shape namespaces;
* the **passes** -- one per IRI-identified target node, because the engine has
  no ``id()`` and only a materialization's root node has a controllable IRI
  (DR-301 4b/4c, DR-302's decomposition);
* which variables each pass is handed as ``staticVars``, and which come from
  the source schema;
* the node-key templates the host mints roots from;
* the placeholder vocabulary IRIs awaiting review.

Both the linter and the runner read it, and that is the point. Before this
module the linter walked from ``start`` alone, so on the blood-pressure map it
analysed **one of ten** root shapes and reported the other nine's variables as
unused -- an answer that was wrong rather than partial. A manifest-driven walk
sees every pass the runner will actually execute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

MANIFEST_FORMAT = "fhir-sulo/map-run-bindings/0.1.0"


class ManifestError(ValueError):
    """The manifest cannot be used as written."""


@dataclass(frozen=True)
class PassSpec:
    """One declared pass: a target shape, the node it is rooted at, its vars.

    ``requires_source_binding`` / ``forbids_source_binding`` are the only
    conditional in the host path, and they select between alternative entry
    shapes rather than switching on data. A pass is skipped exactly when the
    source bound nothing for the named variable -- DR-302's "one engine
    invocation per group", applied to a group that is absent.
    """

    name: str
    shape: str                      # local name, within the shape namespace
    root: str                       # name of the node-key or provided variable
    variables: Tuple[str, ...]      # local names, within the variable namespace
    requires_source_binding: Optional[str] = None
    forbids_source_binding: Optional[str] = None

    def runs_for(self, source_bindings: Mapping[str, Any]) -> bool:
        """Whether this pass runs against these source bindings."""
        def bound(name: str) -> bool:
            value = source_bindings.get(name)
            if value is None:
                return False
            if isinstance(value, Mapping):
                return bool(value.get("value"))
            return bool(value)

        if self.requires_source_binding and not bound(self.requires_source_binding):
            return False
        if self.forbids_source_binding and bound(self.forbids_source_binding):
            return False
        return True

    @property
    def is_conditional(self) -> bool:
        return bool(self.requires_source_binding or self.forbids_source_binding)


@dataclass(frozen=True)
class Manifest:
    """One map's run-binding manifest."""

    family: str
    path: Path
    raw: Mapping[str, Any]

    @property
    def map_id(self) -> str:
        return self.raw["map_id"]

    @property
    def semantic_version(self) -> str:
        return self.raw.get("semantic_version", "0.0.0")

    @property
    def var_namespace(self) -> str:
        return self.raw["var_namespace"]

    @property
    def shape_namespace(self) -> str:
        return self.raw["shape_namespace"]

    @property
    def domain_namespace(self) -> str:
        return self.raw["domain_namespace"]["value"]

    @property
    def source_bound_variables(self) -> Tuple[str, ...]:
        return tuple(self.raw.get("source_bound_vars", ()))

    @property
    def vocabulary(self) -> Dict[str, str]:
        """Static IRIs declared in the manifest, by local variable name."""
        return {name: spec["iri"] for name, spec in self.raw.get("vocabulary", {}).items()}

    @property
    def identity_provided(self) -> Tuple[str, ...]:
        """Variables a service supplies at run time, not the manifest."""
        return tuple(self.raw.get("identity_provided", {}))

    @property
    def node_key_templates(self) -> Dict[str, str]:
        return dict(self.raw.get("node_keys", {}))

    @property
    def passes(self) -> Tuple[PassSpec, ...]:
        out = []
        for spec in self.raw.get("passes", ()):
            out.append(PassSpec(
                name=spec["name"],
                shape=spec["shape"],
                root=spec["root"],
                variables=tuple(spec.get("vars", ())),
                requires_source_binding=spec.get("requires_source_binding"),
                forbids_source_binding=spec.get("forbids_source_binding"),
            ))
        return tuple(out)

    # -- derived ------------------------------------------------------------

    def var_iri(self, local: str) -> str:
        return self.var_namespace + local

    def shape_iri(self, local: str) -> str:
        return self.shape_namespace + local

    def static_variables_of(self, spec: PassSpec) -> Tuple[str, ...]:
        """The variables this pass receives as ``staticVars``, as full IRIs.

        Source-bound variables are excluded: the engine reads those from the
        binding tree, and handing one in as a static would make it always
        available and never consumed, which is a different thing entirely.
        """
        source_bound = set(self.source_bound_variables)
        return tuple(self.var_iri(name) for name in spec.variables
                     if name not in source_bound)

    def node_keys(self, **values: str) -> Dict[str, str]:
        return {
            name: template.format(domain=self.domain_namespace, **values)
            for name, template in self.node_key_templates.items()
        }

    def validate(self) -> None:
        """Refuse a manifest whose own declarations do not hang together."""
        problems = []
        if self.raw.get("format") != MANIFEST_FORMAT:
            problems.append(
                f"format is {self.raw.get('format')!r}, expected {MANIFEST_FORMAT!r}")
        for key in ("map_id", "var_namespace", "shape_namespace", "passes"):
            if key not in self.raw:
                problems.append(f"missing {key!r}")
        if problems:
            raise ManifestError(f"{self.path}: " + "; ".join(problems))

        known = set(self.vocabulary) | set(self.identity_provided) \
            | set(self.node_key_templates) | set(self.source_bound_variables)
        names = [p.name for p in self.passes]
        if len(set(names)) != len(names):
            raise ManifestError(f"{self.path}: duplicate pass name(s)")
        for spec in self.passes:
            unknown = [v for v in spec.variables if v not in known]
            if unknown:
                problems.append(
                    f"pass {spec.name!r} lists variable(s) {unknown} that the manifest "
                    f"neither declares in `vocabulary`/`identity_provided`/`node_keys` "
                    f"nor names in `source_bound_vars`, so the host has no way to "
                    f"supply them")
            if spec.root not in known:
                problems.append(
                    f"pass {spec.name!r} is rooted at {spec.root!r}, which is not a "
                    f"node key or a provided variable")
        if problems:
            raise ManifestError(f"{self.path}: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MapFiles:
    """One map family's shipped files.

    The naming is Agent 3's: ``<family>-source.v1.shex``, ``-target.v1.shex``,
    ``-bindings.v1.json``, ``-map-contract.v1.json``. DR-303 originally claimed
    ``source.shex``/``target.shex``, which matched nothing that shipped, so the
    linter discovered no pairs at all and `make lint-schemas` exited 2 on every
    run. Discovery now follows what is on disk.
    """

    family: str
    directory: Path
    source: Path
    target: Path
    bindings: Optional[Path] = None
    contract: Optional[Path] = None

    @property
    def manifest(self) -> Optional[Manifest]:
        if self.bindings is None:
            return None
        return load_manifest_file(self.bindings, self.family)


def _pick(directory: Path, family: str, role: str, extension: str) -> Optional[Path]:
    """Newest ``<family>-<role>.v<N>.<ext>``, or the unversioned form."""
    candidates = sorted(directory.glob(f"{family}-{role}.v*{extension}"))
    if candidates:
        return candidates[-1]
    plain = directory / f"{family}-{role}{extension}"
    if plain.exists():
        return plain
    # the layout DR-303 originally described, still supported for a lone pair
    generic = directory / f"{role}{extension}"
    return generic if generic.exists() else None


def discover(root: Path) -> Sequence[MapFiles]:
    """Every map family under ``root``, at any depth.

    Recursive because pairs are grouped by FHIR release (``maps/r4/<family>/``)
    and a one-level scan would silently find nothing -- for a build gate, the
    worst outcome, and the one that actually happened.
    """
    found = []
    for directory in sorted(p for p in root.rglob("*") if p.is_dir()):
        family = directory.name
        source = _pick(directory, family, "source", ".shex")
        target = _pick(directory, family, "target", ".shex")
        if source is None and target is None:
            source = directory / "source.shex"
            target = directory / "target.shex"
            if not (source.exists() and target.exists()):
                continue
            family = directory.name
        if source is None or target is None:
            continue
        found.append(MapFiles(
            family=family,
            directory=directory,
            source=source,
            target=target,
            bindings=_pick(directory, family, "bindings", ".json"),
            contract=_pick(directory, family, "map-contract", ".json"),
        ))
    return found


def load_manifest_file(path: Path, family: Optional[str] = None) -> Manifest:
    manifest = Manifest(
        family=family or path.parent.name,
        path=path,
        raw=json.loads(path.read_text(encoding="utf-8")),
    )
    manifest.validate()
    return manifest


def load_manifest(family: str, repo_root: Path, version: str = "v1") -> Manifest:
    path = repo_root / "maps" / "r4" / family / f"{family}-bindings.{version}.json"
    return load_manifest_file(path, family)
