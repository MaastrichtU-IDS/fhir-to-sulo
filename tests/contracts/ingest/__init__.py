"""Gate 0/1 ingestion contract tests (Agent 2).

Runnable with the standard library alone, because CI installs nothing:
``PYTHONPATH=src python3 -m unittest discover -s tests/contracts -p 'test_*.py'``.
The one test that needs rdflib (the HL7 oracle comparison) skips cleanly
without it; every test that could hide a fidelity loss does not.
"""
