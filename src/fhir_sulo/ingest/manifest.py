"""Loader for the pinned profile manifest and element table under ``profiles/``.

The manifest is the single source of truth for the pinned release, profile set,
code systems, unit codes, element scope and status/value policy. Nothing in
this package hard-codes a LOINC code or a UCUM unit; if you find one outside a
docstring or a test, it is a bug.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
# src/fhir_sulo/ingest -> repository root
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
PROFILES_DIR = os.path.join(REPO_ROOT, "profiles")

MANIFEST_PATH = os.path.join(PROFILES_DIR, "fhir-r4-pilot.json")
ELEMENT_TABLE_PATH = os.path.join(PROFILES_DIR, "fhir-r4-element-table.json")


class ManifestError(ValueError):
    pass


class Manifest:
    """The pinned profile manifest, with the accessors ingestion needs."""

    def __init__(self, data: Dict[str, Any], element_table: Dict[str, Any]):
        self.data = data
        self.elements = element_table
        self._validate()

    # -- construction -------------------------------------------------------

    @classmethod
    def load(cls, manifest_path: str = MANIFEST_PATH,
             element_table_path: str = ELEMENT_TABLE_PATH) -> "Manifest":
        with open(manifest_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        with open(element_table_path, "r", encoding="utf-8") as fh:
            table = json.load(fh)
        return cls(data, table)

    def _validate(self) -> None:
        for key in ("release", "source_server", "renderer", "resources",
                    "code_systems", "unit_systems", "status_policy", "value_policy"):
            if key not in self.data:
                raise ManifestError(f"manifest is missing required key {key!r}")
        if self.fhir_release != self.elements.get("fhir_release"):
            raise ManifestError(
                f"manifest release {self.fhir_release!r} != element table release "
                f"{self.elements.get('fhir_release')!r}"
            )
        for rtype in self.data["resources"]:
            if rtype not in self.elements["types"]:
                raise ManifestError(f"resource {rtype!r} has no element table entry")

    # -- release / renderer -------------------------------------------------

    @property
    def fhir_release(self) -> str:
        return self.data["release"]["fhir_release"]

    @property
    def fhir_base(self) -> str:
        return self.data["release"]["fhir_vocabulary_base"]

    @property
    def server_base(self) -> str:
        return self.data["source_server"]["base_url"]

    @property
    def renderer_id(self) -> str:
        return self.data["renderer"]["renderer_id"]

    @property
    def renderer_options(self) -> Dict[str, Any]:
        return dict(self.data["renderer"]["options"])

    @property
    def terminology_snapshot(self) -> str:
        return self.data["terminology_snapshot"]

    @property
    def code_system_iri_templates(self) -> Dict[str, str]:
        return self.data.get("code_system_iri_templates", {})

    # -- profiles -----------------------------------------------------------

    def supported_resource_types(self):
        return sorted(self.data["resources"])

    def base_profile(self, resource_type: str) -> str:
        try:
            return self.data["resources"][resource_type]["base_profile"]
        except KeyError:
            raise ManifestError(f"resource type {resource_type!r} is not in scope")

    def validated_profiles(self, resource_type: str):
        entry = self.data["resources"].get(resource_type)
        if entry is None:
            raise ManifestError(f"resource type {resource_type!r} is not in scope")
        return tuple(
            p["canonical"] for p in entry["pinned_profiles"] if p.get("role") == "validated"
        )

    def known_profiles(self, resource_type: str):
        entry = self.data["resources"][resource_type]
        return tuple(p["canonical"] for p in entry["pinned_profiles"])

    def in_scope_elements(self, resource_type: str):
        return tuple(self.data["resources"][resource_type]["in_scope_elements"])

    def source_only_elements(self, resource_type: str):
        return tuple(self.data["resources"][resource_type].get("source_only_elements", ()))

    # -- terminology --------------------------------------------------------

    def is_pinned_code(self, system: str, code: str) -> bool:
        entry = self.data["code_systems"].get(system)
        if entry is None:
            return False
        return any(c["code"] == code for c in entry.get("pinned_codes", ()))

    def is_pinned_unit(self, system: Optional[str], code: Optional[str]) -> bool:
        if system is None or code is None:
            return False
        entry = self.data["unit_systems"].get(system)
        if entry is None:
            return False
        return any(c["code"] == code for c in entry.get("pinned_codes", ()))

    # -- policy -------------------------------------------------------------

    def status_outcome(self, resource_type: str, status: str) -> Optional[str]:
        return self.data["status_policy"].get(resource_type, {}).get(status)

    def value_policy(self, name: str) -> Dict[str, str]:
        try:
            return self.data["value_policy"][name]
        except KeyError:
            raise ManifestError(f"no value policy named {name!r}")

    @property
    def supported_modifier_extensions(self):
        return tuple(self.data.get("supported_modifier_extensions", ()))

    # -- element table ------------------------------------------------------

    def element_def(self, type_name: str, element_name: str) -> Dict[str, Any]:
        types = self.elements["types"]
        if type_name not in types:
            raise ManifestError(
                f"type {type_name!r} is not in the pinned element table; the renderer "
                "refuses unknown types rather than dropping their content"
            )
        elements = types[type_name]["elements"]
        if element_name not in elements:
            raise ManifestError(
                f"element {type_name}.{element_name} is not in the pinned element table; "
                "the renderer refuses unknown elements rather than dropping their content "
                "(acceptance matrix row 'Source fidelity')"
            )
        return elements[element_name]

    def has_type(self, type_name: str) -> bool:
        return type_name in self.elements["types"]

    def type_kind(self, type_name: str) -> str:
        return self.elements["types"][type_name]["kind"]

    def primitive_xsd(self, fhir_type: str):
        table = self.elements["primitive_xsd"]
        if fhir_type not in table:
            return _MISSING
        return table[fhir_type]

    def is_primitive(self, fhir_type: str) -> bool:
        return fhir_type in self.elements["primitive_xsd"]


_MISSING = object()


_DEFAULT: Optional[Manifest] = None


def default_manifest() -> Manifest:
    """Process-wide pinned manifest. Loaded once; never fetched over a network."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Manifest.load()
    return _DEFAULT
