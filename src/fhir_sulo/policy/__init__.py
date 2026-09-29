"""Policy tables, canonical keying, and the audit record shared by the
identity and terminology services (Agent 5).

Kept in one module so the determinism rules are enforced once rather than
duplicated in two packages.
"""

from .bundle import (
    POLICY_BUNDLE_NAME,
    PolicyBundle,
    PolicyError,
    default_policy_dir,
    parse_policy_version,
)
from .canonical import canonical_json, digest, key_fragment, normalise_text, slugify
from .record import DecisionRecord

__all__ = [
    "PolicyBundle",
    "PolicyError",
    "POLICY_BUNDLE_NAME",
    "parse_policy_version",
    "default_policy_dir",
    "canonical_json",
    "digest",
    "key_fragment",
    "normalise_text",
    "slugify",
    "DecisionRecord",
]
