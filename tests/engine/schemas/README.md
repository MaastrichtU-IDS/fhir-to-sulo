# Linter test schemas

One directory per case. `pair.json` names the files and what the linter must say
about them; `source.shex` and `target.shex` are the pair.

The `neg-*` cases are the negative schemas the acceptance matrix row "Mapping
analysis — Static schema check and negative schemas" requires. Each one is a
schema pair that the pinned engine accepts and then mishandles **silently** —
that is the point of the case. The comment at the top of each negative pair
records what the engine actually does with it, measured in DR-301, so the case
cannot be "fixed" by relaxing the linter without noticing what stops being caught.

`parsed/` under `tests/engine/fixtures` holds the ShExJ for each schema, produced
by the pinned engine's own parser. Committing it lets the linter's tests run in
CI without Docker; `test_linter_docker.py` re-parses and fails if it has drifted.
