"""Re-export shim. The implementation is ``fhir_sulo.canonical``.

IR-602: this module and ``fhir_sulo.store.canonical`` were independent
implementations of the same normalisation rules, written on separate branches.
They agreed, and a drift test kept them agreeing, but two implementations of a
determinism primitive is the condition the drift test existed to survive, not
a design.

Both are now aliases of one module. The import path is kept because it is
depended on across ``policy/``, ``identity/`` and the test suite, and changing
it would have been churn with no safety benefit.

Do not add a definition here. ``tests/integration/test_canonicalisers_agree.py``
fails if a second definition of any of these primitives appears anywhere under
``src/``.
"""

from ..canonical import (
    canonical_json,
    digest,
    key_fragment,
    normalise_text,
    sha256_hex,
    slugify,
)

__all__ = [
    "normalise_text",
    "canonical_json",
    "sha256_hex",
    "digest",
    "slugify",
    "key_fragment",
]
