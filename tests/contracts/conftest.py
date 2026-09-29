"""Make ``src/`` importable and pin the policy directory for contract tests."""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
POLICIES = REPO_ROOT / "policies"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("FHIR_SULO_POLICY_DIR", str(POLICIES))
