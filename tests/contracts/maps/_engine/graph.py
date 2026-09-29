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


# ---------------------------------------------------------------------------
# Reading pivot tuples back out of an EMITTED target graph
# ---------------------------------------------------------------------------
#
# Everything below reads the materialized graph and nothing else -- no source
# binding, no host value.  This is the half that matters for acceptance,
# because the target graph is what reaches a clinical store: a map that binds
# the right things and then emits the wrong ones is exactly the failure a
# source-side assertion cannot see.
#
# `nquads` is a plain string, so the producer is swappable: the test harness,
# Agent 4's driver, or a file on disk all work unchanged.

PROV_DERIVED_FROM = "<http://www.w3.org/ns/prov#wasDerivedFrom>"


def source_resource_id(triples, node: str) -> str:
    """The FHIR resource id this node's own emitted lineage names.

    Read from ``prov:wasDerivedFrom``, e.g.
    ``https://fhir.example/Observation/bp-1/_history/1`` -> ``bp-1``.  The
    panel key is not a literal anywhere in the target graph, so the graph's own
    statement about where the node came from is the only graph-side answer to
    "which observation is this".
    """
    derived = objects_of(triples, node, PROV_DERIVED_FROM)
    if len(derived) != 1:
        raise AssertionError("%s has %d prov:wasDerivedFrom arcs, expected 1: %s"
                             % (node, len(derived), derived))
    return derived[0][1:-1].split("/_history/")[0].rsplit("/", 1)[-1]


def bp_panel_tuples(nquads: str, vocabulary: Mapping[str, str]):
    """``[(panel, sys, dia), ...]`` recovered from an emitted BP target graph.

    Walks panel record -> ``sulo:refersTo`` -> quantity -> ``sulo:hasValue``,
    and decides which slot a quantity fills from the class of the quality it
    ``sulo:refersTo`` -- exactly the structure concept note section 5 specifies
    ("materialize sulo:Quantity -> sulo:refersTo -> a typed systolic or
    diastolic quality").  Nothing is inferred from how a node IRI is spelled,
    from triple order, or from a source binding.

    Raises rather than guessing when the graph is self-inconsistent: a quantity
    whose own domain type disagrees with its quality's class, a quantity with
    two values, or a panel with two quantities in one slot.  An absent
    diastolic yields ``""``, never a borrowed value.

    ``vocabulary`` is the run-binding manifest's ``vocabulary`` map, so the R1
    swap works here too.
    """
    triples = parse(nquads)
    quantity = "<%sQuantity>" % SULO
    refers_to = "<%srefersTo>" % SULO
    has_value = "<%shasValue>" % SULO
    quality_slots = {"<%s>" % vocabulary["sysQualityClass"]: "sys",
                     "<%s>" % vocabulary["diaQualityClass"]: "dia"}
    result_slots = {"<%s>" % vocabulary["sysResultClass"]: "sys",
                    "<%s>" % vocabulary["diaResultClass"]: "dia"}

    out = []
    for panel in subjects_of_type(triples, vocabulary["recordClass"]):
        found = {"sys": "", "dia": ""}
        for referent in objects_of(triples, panel, refers_to):
            types = types_of(triples, referent)
            if quantity not in types:
                continue

            qualities = objects_of(triples, referent, refers_to)
            if len(qualities) != 1:
                raise AssertionError("quantity %s refersTo %d qualities, expected 1"
                                     % (referent, len(qualities)))
            slots = [quality_slots[t] for t in types_of(triples, qualities[0])
                     if t in quality_slots]
            if len(slots) != 1:
                raise AssertionError(
                    "the quality %s of quantity %s carries %d recognised component "
                    "classes, expected exactly 1" % (qualities[0], referent, len(slots)))
            slot = slots[0]

            own = [result_slots[t] for t in types if t in result_slots]
            if own != [slot]:
                raise AssertionError(
                    "%s is typed %s but refersTo a %r quality: the quantity and its "
                    "referent disagree about which component this is" % (referent, own, slot))

            values = objects_of(triples, referent, has_value)
            if len(values) != 1:
                raise AssertionError(
                    "%s has %d sulo:hasValue arcs, expected 1 (hasValue is an "
                    "owl:FunctionalProperty)" % (referent, len(values)))
            if found[slot]:
                raise AssertionError("panel %s has two %s quantities: %s and %s"
                                     % (panel, slot, found[slot], values[0]))
            found[slot] = values[0].split("^^")[0].strip('"')

        out.append((source_resource_id(triples, panel), found["sys"], found["dia"]))
    return sorted(out)
