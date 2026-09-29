"""Tiny N-Triples helpers for asserting things about a materialized graph."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Sequence, Set, Tuple

RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
SULO = "https://w3id.org/sulo/"
PROV = "http://www.w3.org/ns/prov#"


def parse(nquads: str) -> List[Tuple[str, str, str]]:
    """Parse N-Triples into a deduplicated, sorted list of term triples."""
    out = set()
    for line in nquads.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert line.endswith(" ."), line
        body = line[:-2]
        s, rest = body.split(" ", 1)
        p, o = rest.split(" ", 1)
        out.add((s, p, o.strip()))
    return sorted(out)


def subjects(triples) -> Set[str]:
    return {s for s, _, _ in triples}


def objects(triples) -> Set[str]:
    return {o for _, _, o in triples}


def predicates(triples) -> Set[str]:
    return {p for _, p, _ in triples}


def po(triples, subject: str) -> List[Tuple[str, str]]:
    return sorted((p, o) for s, p, o in triples if s == subject)


def objects_of(triples, subject: str, predicate: str) -> List[str]:
    return sorted(o for s, p, o in triples if s == subject and p == predicate)


def types_of(triples, subject: str) -> List[str]:
    return objects_of(triples, subject, RDF_TYPE)


def subjects_of_type(triples, iri: str) -> List[str]:
    return sorted(s for s, p, o in triples if p == RDF_TYPE and o == "<%s>" % iri)


def sources(triples) -> List[str]:
    """Nodes that are a subject but never an object: the graph's entry points."""
    return sorted(subjects(triples) - objects(triples))


def blank_nodes(triples) -> Set[str]:
    return {t for trip in triples for t in (trip[0], trip[2]) if t.startswith("_:")}


def entailed_participants(triples) -> Set[Tuple[str, str]]:
    """Apply SULO's PRO chain: hasParticipant o isFeatureOf -> hasParticipant.

    SULO 0.2.12 asserts
    ``sulo:hasParticipant owl:propertyChainAxiom (sulo:hasParticipant [owl:inverseOf
    sulo:hasFeature])`` and ``sulo:isFeatureOf owl:inverseOf sulo:hasFeature``
    (DR-002, verified against the axiom).  Computing it here lets a test assert
    that the entailment holds *and* that the map did not assert it directly.
    """
    has_part = "<%shasParticipant>" % SULO
    is_feature_of = "<%sisFeatureOf>" % SULO
    roles = defaultdict(set)
    holders = defaultdict(set)
    for s, p, o in triples:
        if p == has_part:
            roles[s].add(o)
        elif p == is_feature_of:
            holders[s].add(o)
    out = set()
    for process, rs in roles.items():
        for role in rs:
            for holder in holders.get(role, ()):
                out.add((process, holder))
    return out
