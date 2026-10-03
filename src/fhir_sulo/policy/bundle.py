"""Loading and versioning of the policy tables in ``policies/``.

The bundle digest is the single value Agent 6 puts into ``RunRecord`` as the
policy version: it changes if any byte of any policy table changes.

A missing or malformed policy file raises at load time. There is no "carry on
with defaults" path: an external lookup must supply a value or fail explicitly
(concept note section 3).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

from .canonical import digest

__all__ = [
    "PolicyBundle",
    "PolicyError",
    "default_policy_dir",
    "parse_policy_version",
    "POLICY_BUNDLE_NAME",
]

POLICY_BUNDLE_NAME = "fhir-sulo-policies"

_POLICY_VERSION_RE = re.compile(
    r"^(?P<bundle>[a-z0-9-]+)/identity-(?P<identity>[^+]+)"
    r"\+code-(?P<code_interpretation>[^+]+)"
    r"\+unit-(?P<unit>[^+]+)"
    r"\+sha256\.(?P<digest_prefix>[0-9a-f]{16})$"
)


class PolicyError(RuntimeError):
    """A policy table is missing, unparseable, or internally inconsistent."""


def parse_policy_version(policy_version: str) -> Dict[str, str]:
    """Resolve a ``RunRecord.policy_version`` string back to its components.

    Raises ``PolicyError`` if the string is not one this project produced.
    """
    match = _POLICY_VERSION_RE.match(policy_version.strip())
    if not match:
        raise PolicyError("not a fhir-sulo policy version string: %r" % policy_version)
    return match.groupdict()


_FILES = {
    "identity_policy": "identity-policy.v1.json",
    "code_interpretation": "code-interpretation.v1.json",
    "unit_policy": "unit-policy.v1.json",
}


def default_policy_dir() -> Path:
    """``policies/`` at the repository root, or ``$FHIR_SULO_POLICY_DIR``."""
    override = os.environ.get("FHIR_SULO_POLICY_DIR")
    if override:
        return Path(override)
    # src/fhir_sulo/policy/bundle.py -> repo root is three parents up from src/
    return Path(__file__).resolve().parents[3] / "policies"


@dataclass(frozen=True)
class PolicyBundle:
    identity: Mapping[str, Any]
    code_interpretation: Mapping[str, Any]
    unit: Mapping[str, Any]
    source_dir: str

    @classmethod
    def load(cls, policy_dir: Any = None) -> "PolicyBundle":
        root = Path(policy_dir) if policy_dir is not None else default_policy_dir()
        if not root.is_dir():
            raise PolicyError("policy directory not found: %s" % root)
        loaded: Dict[str, Any] = {}
        for key, filename in _FILES.items():
            path = root / filename
            if not path.is_file():
                raise PolicyError("policy table not found: %s" % path)
            try:
                with path.open("r", encoding="utf-8") as handle:
                    loaded[key] = json.load(handle)
            except ValueError as exc:
                raise PolicyError("policy table %s is not valid JSON: %s" % (path, exc))
            version = loaded[key].get("version")
            if not version:
                raise PolicyError("policy table %s has no version" % path)
        bundle = cls(
            identity=loaded["identity_policy"],
            code_interpretation=loaded["code_interpretation"],
            unit=loaded["unit_policy"],
            source_dir=str(root),
        )
        bundle.validate()
        return bundle

    # -- versioning ------------------------------------------------------

    @property
    def policy_version(self) -> str:
        """The single string for ``RunRecord.policy_version``.

        Covers all three tables at once and is resolvable back to them by
        ``parse_policy_version``: it names each table's semantic version and
        pins the exact bytes with the bundle digest.

        Note that this string is *not* an input to any entity key. Entity IRIs
        are keyed on ``key_revision`` instead, so a policy edit that does not
        change the keying answer moves this string while leaving every IRI
        alone. See ``entity_key_revision``.
        """
        return "%s/identity-%s+code-%s+unit-%s+sha256.%s" % (
            POLICY_BUNDLE_NAME,
            self.identity["version"],
            self.code_interpretation["version"],
            self.unit["version"],
            self.bundle_digest[:16],
        )

    @property
    def terminology_snapshot(self) -> str:
        """The single string for ``RunRecord.terminology_snapshot``."""
        code_snapshot = str(self.code_interpretation["terminology_snapshot"]["snapshot_id"])
        ucum_snapshot = str(self.unit["ucum_snapshot"]["snapshot_id"])
        if code_snapshot == ucum_snapshot:
            return code_snapshot
        return "code=%s+ucum=%s" % (code_snapshot, ucum_snapshot)

    @property
    def entity_key_revision(self) -> str:
        """Bumping this - and only this - re-keys every entity IRI."""
        return str(self.identity["entity_iri"]["key_revision"])

    @property
    def quality_key_revision(self) -> str:
        return str(self.identity["quality_identity"]["key_revision"])

    @property
    def versions(self) -> Dict[str, str]:
        """Per-table detail behind ``policy_version``, for audit records."""
        return {
            "policy_version": self.policy_version,
            "identity_policy": str(self.identity["version"]),
            "code_interpretation": str(self.code_interpretation["version"]),
            "unit_policy": str(self.unit["version"]),
            "terminology_snapshot": self.terminology_snapshot,
            "entity_key_revision": self.entity_key_revision,
            "quality_key_revision": self.quality_key_revision,
            "policy_bundle_digest": self.bundle_digest,
        }

    @property
    def bundle_digest(self) -> str:
        """sha256 over the canonical form of all three tables together."""
        return digest(
            {
                "identity_policy": self.identity,
                "code_interpretation": self.code_interpretation,
                "unit_policy": self.unit,
            }
        )

    def matches_policy_version(self, policy_version: str) -> bool:
        """True if this bundle is byte-for-byte the one that string names."""
        return self.policy_version == policy_version

    # -- internal consistency --------------------------------------------

    def validate(self) -> None:
        iri = self.identity.get("entity_iri")
        if not isinstance(iri, dict):
            raise PolicyError("identity policy has no entity_iri block")
        style = iri.get("key_style")
        if style not in iri.get("key_style_options", {}):
            raise PolicyError("unknown identity key_style: %r" % (style,))
        if style == "legacy-concept-note" and not iri.get("single_source_scope"):
            raise PolicyError(
                "key_style 'legacy-concept-note' requires entity_iri.single_source_scope "
                "to name the one permitted source scope"
            )
        length = iri.get("key_length_hex_chars")
        if not isinstance(length, int) or not 8 <= length <= 64:
            raise PolicyError("entity_iri.key_length_hex_chars must be an int in 8..64")
        if iri.get("key_hash_algorithm") != "sha256":
            raise PolicyError("only sha256 is supported for entity keys")
        if not str(iri.get("key_revision", "")).strip():
            raise PolicyError("entity_iri.key_revision is required")
        if "policy_version" in iri.get("key_input_fields", []):
            raise PolicyError(
                "entity_iri.key_input_fields must not contain 'policy_version': entity "
                "IRIs would move on every unrelated policy edit. Use 'key_revision'."
            )

        contained = self.identity.get("contained_reference_scoping")
        if not isinstance(contained, dict):
            raise PolicyError(
                "identity policy has no contained_reference_scoping block; without "
                "it the service cannot scope a '#local' reference to its container "
                "and two containers' '#p-inline' would merge (IR-604)"
            )
        template = str(contained.get("scope_id_template", ""))
        for field in ("{scope_id}", "{container_url}"):
            if field not in template:
                raise PolicyError(
                    "contained_reference_scoping.scope_id_template must interpolate "
                    "%s; %r does not, so contained resources in different containers "
                    "would share a scope" % (field, template)
                )
        if contained.get("missing_container_url") != "rejected":
            raise PolicyError(
                "contained_reference_scoping.missing_container_url must be "
                "'rejected'; anything else silently falls back to the dataset "
                "scope, which is the merge this rule exists to prevent"
            )
        if not str(contained.get("missing_container_url_reason_code", "")).strip():
            raise PolicyError(
                "contained_reference_scoping.missing_container_url_reason_code is required"
            )

        quality = self.identity.get("quality_identity")
        if not isinstance(quality, dict):
            raise PolicyError("identity policy has no quality_identity block")
        mode = quality.get("mode")
        if mode is not None and mode not in quality.get("allowed_modes", {}):
            raise PolicyError("unknown quality_identity.mode: %r" % (mode,))
        if not str(quality.get("key_revision", "")).strip():
            raise PolicyError("quality_identity.key_revision is required")
        for name, spec in quality.get("allowed_modes", {}).items():
            if "policy_version" in spec.get("key_input_fields", []):
                raise PolicyError(
                    "quality mode %r keys on 'policy_version'; use 'key_revision'" % name
                )

        for table, entry_key, id_key in (
            (self.code_interpretation, "entries", "entry_id"),
            (self.unit, "units", "unit_id"),
        ):
            seen = set()
            statuses = set(table.get("review_status_values", {}))
            for entry in table.get(entry_key, []):
                ident = entry.get(id_key)
                if not ident:
                    raise PolicyError("%s entry without %s" % (table["policy_id"], id_key))
                if ident in seen:
                    raise PolicyError("duplicate %s: %s" % (id_key, ident))
                seen.add(ident)
                if entry.get("review_status") not in statuses:
                    raise PolicyError(
                        "%s has unknown review_status %r"
                        % (ident, entry.get("review_status"))
                    )

        dimensions = set(self.unit.get("dimensions", {}))
        for unit in self.unit.get("units", []):
            if unit.get("dimension") not in dimensions:
                raise PolicyError(
                    "unit %s has undeclared dimension %r"
                    % (unit["unit_id"], unit.get("dimension"))
                )
        for entry in self.code_interpretation.get("entries", []):
            expected = entry.get("expected_unit_dimension")
            if expected is not None and expected not in dimensions:
                raise PolicyError(
                    "code entry %s expects undeclared unit dimension %r"
                    % (entry["entry_id"], expected)
                )
