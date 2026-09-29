"""Classify the body of a ``%Map:{ ... %}`` annotation exactly as the engine does.

Why this exists, and why it copies two regular expressions verbatim:

DR-301 probe 4b found that the pinned engine's response to an unrecognised Map
code is **silent deletion of the entire shape that used it**. There is no error,
no stderr, and exit status 0. CD-1 therefore moves the obligation "invalid
``id()`` uses fail before data processing" onto the host linter, restated as *any
unknown Map function*.

To catch that reliably the linter has to agree with the engine about how a code
is read, including the engine's own sharp edge. The engine tries
``variablePattern`` **first**, so ``id(v:panelId)`` -- which contains a colon --
is not seen as a function call at all. It is read as a variable in an undeclared
prefix named ``id(v``, and reported, if anything is reported, as an unbound
variable. A code with no colon, ``skolemize(x)``, takes the other route and dies
inside ``extensions.lower`` with ``Unknown extension``. Both outcomes are silent
at the CLI. A linter that only looked for ``name(...)`` would miss the first and
whichever one an author actually typed is not predictable.

So both regexes below are transcribed from
``@shexjs/extension-map/src/ThreadedMaterializer.ts`` (1.0.0-alpha.33) rather
than approximated, and the dispatch order is the engine's order. The known
function names come from ``src/extensions.ts``.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

#: ``ThreadedMaterializer.ts:55`` -- ``<iri>`` or ``prefix:local``. Tried first.
#:
#: ``\Z``, not ``$``: JavaScript's ``$`` without ``/m`` matches only at the very
#: end of the string, while Python's ``$`` also matches before a trailing
#: newline. With ``$`` the linter would read ``" v:name \n"`` as a variable
#: while the engine reads it as an unrecognised code and deletes the shape --
#: a divergence in exactly the direction that hides a fault.
VARIABLE_PATTERN = re.compile(r"^ *(?:<([^>]*)>|([^:]*):([^ ]*)) *\Z")

#: ``ThreadedMaterializer.ts:56`` -- any ``name(...)``. Tried second.
#:
#: **No** ``re.S``, because the JavaScript has no ``/s`` flag: its ``.`` stops
#: at a newline. With ``re.S`` a multi-line ``hashmap(v:x, {\n "a": "b"\n})``
#: -- the natural way to write a map of any size -- would lint as a valid
#: function while the engine matches neither pattern and deletes the shape.
#: Verified against the installed source, not assumed.
FUNCTION_PATTERN = re.compile(r"^\s*[a-zA-Z0-9]+\(.*\)\s*\Z")

#: Not the engine's: used only to explain *why* a function-shaped code was
#: read as a variable. See ``parse_map_code``.
LOOKS_LIKE_A_CALL = re.compile(r"^\s*[a-zA-Z0-9]+\(")

#: ``extensions.ts`` dispatch table. Anything else raises ``Unknown extension``.
KNOWN_FUNCTIONS = frozenset({"hashmap", "regex", "test"})

#: ``regex_extension.ts:11`` -- ``?<prefix:local>`` or ``?<<iri>>``.
CAPTURE_GROUP = re.compile(r"\?<(?:([a-zA-Z:]+)|<([^>]+)>)>")

#: ``hashmap_extension.ts:24`` -- first argument is the variable. This one
#: *does* carry ``/s`` in the JavaScript, so ``re.S`` here is the faithful
#: translation, not an oversight matching the line above.
HASHMAP_ARGS = re.compile(r"^[ ]*([\w:<>]+)[ ]*,[ ]*(\{.*)$", re.S)

MAP_EXTENSION_IRI = "http://shex.io/extensions/Map/#"


class CodeKind(enum.Enum):
    VARIABLE = "variable"
    FUNCTION = "function"
    UNPARSEABLE = "unparseable"


@dataclass(frozen=True)
class MapCode:
    """One parsed Map annotation.

    ``variables`` is every variable the code *reads or writes*, already expanded
    against the schema's prefixes where that was possible. ``problem`` is set
    when the engine would not have understood the code -- which, at runtime,
    means it would have deleted the surrounding shape without saying so.
    """

    raw: str
    kind: CodeKind
    variables: Tuple[str, ...] = ()
    function: Optional[str] = None
    problem: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.problem is None


def _expand(prefixed: str, prefixes: Mapping[str, str]) -> Tuple[Optional[str], Optional[str]]:
    """Expand ``<iri>`` or ``prefix:local``. Returns ``(expanded, problem)``."""
    m = VARIABLE_PATTERN.match(prefixed)
    if m is None:
        return None, f"{prefixed.strip()!r} is not a variable reference"
    if m.group(1) is not None:
        if not m.group(1):
            # `<>` parses, binds the empty variable name, and so binds nothing;
            # the engine prunes the branch in silence.
            return None, "<> is an empty variable name and can never bind"
        return m.group(1), None
    prefix, local = m.group(2), m.group(3)
    if prefix not in prefixes:
        # The engine's _expandPrefix falls back to `prefix + ":" + local`, so
        # this becomes a variable name nothing will ever bind -- and the branch
        # that needed it is pruned in silence.
        return (
            prefix + ":" + local,
            f"prefix {prefix!r} is not declared in this schema, so "
            f"{prefixed.strip()!r} can never bind",
        )
    return prefixes[prefix] + local, None


def parse_map_code(raw: str, prefixes: Mapping[str, str]) -> MapCode:
    """Read one Map code the way ``_stepTripleConstraint`` reads it."""
    # Engine order: variable first. `id(v:panelId)` lands here, not in the
    # function branch, because it contains a colon.
    m = VARIABLE_PATTERN.match(raw)
    if m is not None:
        expanded, problem = _expand(raw, prefixes)
        if problem and LOOKS_LIKE_A_CALL.match(raw):
            # The engine does this too, and it is the single most confusing
            # thing about writing Map codes: a call whose argument contains a
            # colon and no space matches the *variable* pattern first, so it
            # never reaches the function dispatcher. Say so, rather than
            # leaving the author to wonder what prefix `regex(/(?<v` is.
            name = raw.strip().split("(", 1)[0]
            problem = (
                f"{raw.strip()!r} looks like a call to {name!r}, but the engine "
                f"tries its variable pattern first and this matches it: the "
                f"argument contains a ':' and no space, so the whole code is "
                f"read as a variable in an undeclared prefix and the enclosing "
                f"shape is deleted without an error"
                + ("" if name in KNOWN_FUNCTIONS else
                   f". {name!r} is not a Map function either; the engine knows "
                   f"only {', '.join(sorted(KNOWN_FUNCTIONS))}")
            )
        return MapCode(
            raw=raw,
            kind=CodeKind.VARIABLE,
            variables=(expanded,) if expanded else (),
            problem=problem,
        )

    if FUNCTION_PATTERN.match(raw):
        body = raw.strip()
        open_at = body.index("(")
        name = body[:open_at]
        args = body[open_at + 1 : body.rindex(")")]
        if name not in KNOWN_FUNCTIONS:
            return MapCode(
                raw=raw,
                kind=CodeKind.FUNCTION,
                function=name,
                problem=(
                    f"unknown Map function {name!r}; the engine knows only "
                    f"{', '.join(sorted(KNOWN_FUNCTIONS))} and deletes the "
                    "enclosing shape without an error when it meets another "
                    "(DR-301 probe 4b, CD-1)"
                ),
            )
        variables, problem = _function_variables(name, args, prefixes)
        return MapCode(
            raw=raw, kind=CodeKind.FUNCTION, function=name,
            variables=variables, problem=problem,
        )

    return MapCode(
        raw=raw,
        kind=CodeKind.UNPARSEABLE,
        problem=(
            f"{raw.strip()!r} is neither a variable (<iri> or prefix:local) nor a "
            "function call; the engine will drop the constraint that carries it"
        ),
    )


def _function_variables(
    name: str, args: str, prefixes: Mapping[str, str]
) -> Tuple[Tuple[str, ...], Optional[str]]:
    """The variables a known Map function reads or writes."""
    if name == "test":
        return (), None

    if name == "hashmap":
        m = HASHMAP_ARGS.match(args)
        if m is None:
            return (), "hashmap(...) needs a variable name and a JSON map as arguments"
        expanded, problem = _expand(m.group(1), prefixes)
        return ((expanded,) if expanded else ()), problem

    # regex(/.../) declares its variables as named capture groups.
    found = []
    problems = []
    for group in CAPTURE_GROUP.finditer(args):
        token = f"<{group.group(2)}>" if group.group(2) else group.group(1)
        expanded, problem = _expand(token, prefixes)
        if expanded:
            found.append(expanded)
        if problem:
            problems.append(problem)
    if not found and not problems:
        return (), "regex(...) declares no named capture group, so it binds nothing"
    return tuple(found), ("; ".join(problems) if problems else None)
