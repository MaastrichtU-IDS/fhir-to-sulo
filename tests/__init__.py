"""Test package root.

`tests/` and its suite directories are real packages so that a module name
like `support` is qualified (`tests.engine.support` vs
`tests.integration.support`). Without this, Agent 4's and Agent 6's
same-named helper modules collided under pytest's rootdir import and six
integration modules failed to collect.
"""
