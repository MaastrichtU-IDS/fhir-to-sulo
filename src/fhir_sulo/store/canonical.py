"""Re-export shim. The implementation is ``fhir_sulo.canonical``.

IR-602: this module and ``fhir_sulo.policy.canonical`` were independent
implementations of the same normalisation rules. They agreed -- a drift test
proved it, and an NFC->NFD injection proved the test had teeth -- but entity
keys and graph keys must not merely *agree* about what "the same input" means;
they must be computed by the same code.

Both are now aliases of one module. The import path is kept because
``store/``, ``provenance/`` and ``validation/`` depend on it.

Do not add a definition here. ``tests/integration/test_canonicalisers_agree.py``
fails if a second definition of any of these primitives appears anywhere under
``src/``.
"""

from ..canonical import canonical_json, digest, normalise_text, sha256_hex

__all__ = ["normalise_text", "canonical_json", "sha256_hex", "digest"]
