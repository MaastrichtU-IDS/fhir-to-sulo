"""Gate 2 / Gate 3 acceptance tests for the three ShExMap pairings in `maps/r4/`.

`_engine/` used to be a test-only harness with its own Node script, because
the production driver had not landed. It has. The harness is now a thin
adapter over `fhir_sulo.engine.maprun` and `fhir_sulo.pipeline`: these tests
exercise the code that ships, through the same pinned image, with the driver's
`Guards` set explicitly and its per-quad provenance behind
`test_host_emits_no_triples.py`. `shexmap-materialize` is still never used
(CD-2: it truncates every repetition to 19 items and exits 0 on fatal and on
partial output).

The legacy result-document shape is kept on purpose. `require_clean`, `quads`,
`triples` and `objects_of` are used across six modules here, and repointing
the engine underneath was not a reason to rewrite the assertions above it.

The engine runs in Docker. Tests that need it subclass
`_engine.engine.EngineTestCase`, which skips loudly rather than silently -- a
skip is not a pass -- and fails outright when `FHIR_SULO_REQUIRE_ENGINE=1`,
which the gate sets. See `maps/r4/README.md`, DR-201, DR-303 and DR-304.
"""
