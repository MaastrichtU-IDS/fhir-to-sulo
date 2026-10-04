#!/usr/bin/env python3
"""Recompute `pairing_hash` in every map contract manifest under maps/r4/.

The pairing hash is sha256 over the bytes of the manifest's `pairing_files`,
in the listed order, with a length prefix per file so that moving a byte
between two files changes the hash.  It identifies the reviewed pairing
(concept note section 7, plan section 3: "pairing version/hash").

    python3 maps/r4/rehash.py            write
    python3 maps/r4/rehash.py --check    verify; exit 1 on drift

`tests/contracts/maps/test_map_contracts.py` runs --check, so a schema edit
that does not update the hash fails the build.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def pairing_hash(files) -> str:
    h = hashlib.sha256()
    for rel in files:
        data = (REPO / rel).read_bytes()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(str(len(data)).encode("ascii"))
        h.update(b"\0")
        h.update(data)
    return h.hexdigest()


def manifests():
    return sorted(HERE.glob("*/*-map-contract.v*.json"))


def main(check: bool) -> int:
    drift = []
    for path in manifests():
        doc = json.loads(path.read_text())
        want = pairing_hash(doc["pairing_files"])
        if doc.get("pairing_hash") != want:
            if check:
                drift.append("%s: pairing_hash is %r, schemas hash to %r"
                             % (path.relative_to(REPO), doc.get("pairing_hash"), want))
            else:
                doc["pairing_hash"] = want
                path.write_text(json.dumps(doc, indent=2) + "\n")
                print("updated %s" % path.relative_to(REPO))
    if drift:
        for line in drift:
            print(line)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--check" in sys.argv))
