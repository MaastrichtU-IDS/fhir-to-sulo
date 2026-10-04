"""Agent 6's source-to-target, correction, validation and operator tests.

This package exists so the suite can be collected as ``tests.integration.*``.
The bootstrap below puts *this* directory on ``sys.path`` as well, so the
sibling helper modules (``support``, ``mapoutput``) import the same way under
every runner:

* ``python -m unittest discover -s tests/integration``
* ``python -m unittest discover -s tests/integration -t .``
* ``python -m pytest tests/integration`` (what ``make integration`` uses)

Without it, adding this ``__init__.py`` changes the import root and
``import support`` resolves under some runners and not others - which is how
the suite came to pass under one command and fail under another.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "src")

for _path in (_HERE, _SRC):
    if _path not in sys.path:
        sys.path.insert(0, _path)
