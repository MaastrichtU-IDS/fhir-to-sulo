"""Load a map contract manifest into the frozen ``contracts.MapContract``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

from . import engine

REPO = engine.REPO

FAMILY_FILES = {
    "egfr": "maps/r4/egfr/egfr-map-contract.v1.json",
    "bp": "maps/r4/bp/bp-map-contract.v1.json",
    "encounter": "maps/r4/encounter/encounter-map-contract.v1.json",
}


def manifest(family: str) -> Dict:
    return json.loads((REPO / FAMILY_FILES[family]).read_text())


def load(family: str):
    from fhir_sulo.contracts import MapContract, PivotVariable, RepetitionScope, VariableType

    doc = manifest(family)
    pivots = tuple(
        PivotVariable(
            name=v["name"],
            var_type=VariableType(v["var_type"]),
            required=v["required"],
            source_element=v["source_element"],
            target_role=v["target_role"],
            scope=v.get("scope"),
            inverse_covered=v.get("inverse_covered", False),
            notes=tuple(v.get("notes", ())),
        )
        for v in doc["pivot_variables"]
    )
    scopes = tuple(
        RepetitionScope(
            name=s["name"],
            key_variables=tuple(s["key_variables"]),
            member_variables=tuple(s["member_variables"]),
            min_occurs=s.get("min_occurs", 0),
            max_occurs=s.get("max_occurs"),
        )
        for s in doc["repetition_scopes"]
    )
    return MapContract(
        map_id=doc["map_id"],
        semantic_version=doc["semantic_version"],
        pairing_hash=doc["pairing_hash"],
        source_release=doc["source_release"],
        source_profiles=tuple(doc["source_profiles"]),
        source_shape_label=doc["source_shape_label"],
        target_shape_label=doc["target_shape_label"],
        pivot_variables=pivots,
        repetition_scopes=scopes,
        node_key_rules={k: v for k, v in doc["node_key_rules"].items() if not k.startswith("_")},
        terminology_dependencies=tuple(doc["terminology_dependencies"]),
        status_eligibility=tuple(doc["status_eligibility"]),
        expected_failures=tuple(doc["expected_failures"]),
        sulo_version=doc["sulo_version"],
        fixture_references=tuple(doc["fixture_references"]),
        expected_nonmapped_fields=tuple(doc.get("expected_nonmapped_fields", ())),
        allowed_alternative_shapes=tuple(doc.get("allowed_alternative_shapes", ())),
        static_variables=dict(doc.get("static_variables", {})),
        static_analysis_passed=doc.get("static_analysis_passed", False),
    )
