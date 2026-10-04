"""Competency queries and negative queries.

Plan section 5, after the acceptance matrix:

    In addition to shape validation, competency queries must answer: **Which
    eGFR result, value, unit, and time was reported for this person? Which
    systolic/diastolic pair belongs to each encounter time? Who participated
    in this encounter and in which role?** Negative queries must find no
    cross-patient results, erroneous-status clinical assertion, or orphan
    result.

Six queries, three of each. A competency query must return rows; a negative
query must return none. Both directions matter: a competency query that
silently returns nothing looks exactly like a passing negative query, which is
why they are separate types with separate verdicts rather than one list of
SPARQL strings.

Two of these run over the *reasoned* graph
------------------------------------------
``PARTICIPANTS_AND_ROLES`` asks who participated, which under the PRO pattern
means the direct role holder as well as the role - and the person is only a
participant by the SULO property chain. Running it on the asserted graph would
return the roles alone and look like a modelling failure. ``expects_reasoning``
marks it, and ``run_suite`` refuses to report a verdict for such a query on an
unreasoned graph rather than reporting a misleading pass.

Domain classes
--------------
Review item R1 is open: the concept note's ``ex:EGFRResult``,
``ex:PatientRole`` and friends are placeholders with no owner. No query here
hard-codes a domain class IRI. Where one is unavoidable - CQ2 has to tell a
systolic quality from a diastolic one, and the concept note does that with a
type, not a code - the IRI is a **query binding**, supplied by the caller. So
answering R1 means passing two different IRIs, not rewriting a query. The
bindings a query accepts are listed in its ``bindable`` field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from ..store.canonical import digest

__all__ = [
    "CompetencyQuery",
    "NegativeQuery",
    "QueryResult",
    "QuerySuiteReport",
    "COMPETENCY_QUERIES",
    "NEGATIVE_QUERIES",
    "run_query",
    "run_suite",
]

PREFIXES = """
PREFIX sulo: <https://w3id.org/sulo/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
"""


@dataclass(frozen=True)
class CompetencyQuery:
    """A question a clinical user must be able to ask. Must return rows."""

    query_id: str
    question: str
    sparql: str
    expects_reasoning: bool = False
    min_rows: int = 1
    bindable: Tuple[str, ...] = ()
    """Variables the caller may bind, e.g. the person to ask about, or the
    domain class IRIs that review item R1 will supply."""


@dataclass(frozen=True)
class NegativeQuery:
    """A thing that must not be in the graph. Must return no rows."""

    query_id: str
    prohibition: str
    sparql: str
    expects_reasoning: bool = False


@dataclass(frozen=True)
class QueryResult:
    query_id: str
    passed: bool
    row_count: int
    rows: Tuple[Tuple[str, ...], ...]
    variables: Tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class QuerySuiteReport:
    results: Tuple[QueryResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> Tuple[QueryResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    @property
    def digest(self) -> str:
        return digest(
            {
                r.query_id: {"passed": r.passed, "rows": r.row_count}
                for r in sorted(self.results, key=lambda x: x.query_id)
            }
        )

    def summary(self) -> str:
        if self.passed:
            return "%d/%d queries passed" % (len(self.results), len(self.results))
        return "%d of %d queries FAILED: %s" % (
            len(self.failures), len(self.results),
            ", ".join(f.query_id for f in self.failures),
        )


# --------------------------------------------------------- competency queries

Q_EGFR = CompetencyQuery(
    query_id="CQ1-egfr-for-person",
    question="Which eGFR result, value, unit and time was reported for this person?",
    bindable=("person",),
    sparql=PREFIXES + """
        SELECT ?person ?result ?value ?unitCode ?time
        WHERE {
            ?result a sulo:Quantity ;
                    sulo:hasValue ?value ;
                    sulo:hasPart ?unit ;
                    sulo:refersTo ?quality .
            ?unit a sulo:Unit ; sulo:hasValue ?unitCode .
            ?quality sulo:isFeatureOf ?person .
            OPTIONAL { ?result sulo:atTime ?instant . ?instant sulo:hasValue ?time . }
        }
        ORDER BY ?time ?result
    """,
)

Q_BP_PAIRS = CompetencyQuery(
    query_id="CQ2-bp-pair-per-time",
    question="Which systolic/diastolic pair belongs to each encounter time?",
    # The pairing is the whole point. Concept note section 5: the required
    # multiset is {(bp-1,120,80),(bp-2,105,70)} and "a graph that produces
    # (bp-1, 120, 70) or conflates the two panels fails, even if every
    # individual value appears somewhere".
    #
    # So both components are joined through the SAME panel record. A
    # cross-panel association cannot hide: it comes back as an extra row, and
    # the caller compares the result as a multiset against the expected one.
    #
    # ?systolicClass and ?diastolicClass are bindings, not literals in the
    # query: which domain class marks a systolic quality is review item R1.
    bindable=("systolicClass", "diastolicClass"),
    sparql=PREFIXES + """
        SELECT ?panel ?time ?systolic ?diastolic
        WHERE {
            # R11 (2026-09-30): the panel record HAS its component results as
            # PARTS. It referred to them until then. Both components still join
            # through the SAME panel record, which is what makes a cross-panel
            # association show up as an extra row.
            ?panel sulo:hasPart ?sysResult , ?diaResult .
            ?panel sulo:atTime ?instant .
            ?instant sulo:hasValue ?time .

            ?sysResult a sulo:Quantity ;
                       sulo:hasValue ?systolic ;
                       sulo:refersTo ?sysQuality .
            ?sysQuality a ?systolicClass .

            ?diaResult a sulo:Quantity ;
                       sulo:hasValue ?diastolic ;
                       sulo:refersTo ?diaQuality .
            ?diaQuality a ?diastolicClass .

            FILTER (?sysResult != ?diaResult)
        }
        ORDER BY ?time
    """,
)

Q_PARTICIPANTS = CompetencyQuery(
    query_id="CQ3-encounter-participants",
    question="Who participated in this encounter, and in which role?",
    # Needs the SULO property chain: the ROLE is an asserted participant, the
    # PERSON is one only by entailment. Marked accordingly - on an unreasoned
    # graph run_suite reports this as a failure, not as an empty pass.
    expects_reasoning=True,
    sparql=PREFIXES + """
        SELECT ?encounter ?holder ?role
        WHERE {
            ?encounter a sulo:Process ;
                       sulo:hasParticipant ?role .
            ?role a sulo:Role ;
                  sulo:isFeatureOf ?holder .
            ?encounter sulo:hasParticipant ?holder .
        }
        ORDER BY ?encounter ?role
    """,
)

COMPETENCY_QUERIES: Tuple[CompetencyQuery, ...] = (Q_EGFR, Q_BP_PAIRS, Q_PARTICIPANTS)


# ----------------------------------------------------------- negative queries

N_CROSS_PATIENT = NegativeQuery(
    query_id="NQ1-no-cross-patient-result",
    prohibition="No result may reach two different people.",
    sparql=PREFIXES + """
        SELECT ?result ?holderA ?holderB
        WHERE {
            ?result a sulo:Quantity ; sulo:refersTo ?qa , ?qb .
            ?qa sulo:isFeatureOf ?holderA .
            ?qb sulo:isFeatureOf ?holderB .
            FILTER (?holderA != ?holderB)
        }
    """,
)

N_ERRONEOUS_STATUS = NegativeQuery(
    query_id="NQ2-no-erroneous-status-assertion",
    prohibition=(
        "No clinical assertion may derive from a source version whose status is "
        "entered-in-error (concept note section 2)."
    ),
    # The status lives on the source record, which the store keeps out of the
    # semantic graph. The query reaches it through prov:wasDerivedFrom, so it
    # is answerable over (semantic graph UNION provenance registry) - which is
    # exactly the union run_suite is given for the negative suite.
    sparql=PREFIXES + """
        SELECT ?node ?source
        WHERE {
            ?node prov:wasDerivedFrom ?source .
            ?source <urn:fhir-sulo:prov#sourceStatus> "entered-in-error" .
        }
    """,
)

N_ORPHAN = NegativeQuery(
    query_id="NQ3-no-orphan-result",
    prohibition="No materialized quantity, unit or time node may be unreachable.",
    sparql=PREFIXES + """
        SELECT ?node
        WHERE {
            VALUES ?type { sulo:Quantity sulo:Unit sulo:TimeInstant sulo:TimeInterval }
            ?node a ?type .
            FILTER NOT EXISTS { ?anything ?predicate ?node }
        }
    """,
)

N_HAS_PATIENT = NegativeQuery(
    query_id="NQ4-no-hasPatient-predicate",
    prohibition=(
        "The graph contains no hasPatient predicate, in any namespace "
        "(acceptance matrix row PRO; concept note section 2 forbids "
        "resource-specific shortcuts)."
    ),
    sparql=PREFIXES + """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER (STRENDS(STR(?p), "hasPatient") || STRENDS(STR(?p), "hasPatientRole"))
        }
    """,
)

NEGATIVE_QUERIES: Tuple[NegativeQuery, ...] = (
    N_CROSS_PATIENT,
    N_ERRONEOUS_STATUS,
    N_ORPHAN,
    N_HAS_PATIENT,
)


# ------------------------------------------------------------------- execution


def _rows(graph, sparql: str, bindings: Optional[Mapping[str, Any]] = None):
    import rdflib

    init = {}
    for name, value in (bindings or {}).items():
        init[name] = value if isinstance(value, rdflib.term.Node) else rdflib.URIRef(str(value))
    result = graph.query(sparql, initBindings=init or None)
    variables = tuple(str(v) for v in (result.vars or ()))
    rows = tuple(
        tuple("" if cell is None else str(cell) for cell in row) for row in result
    )
    return variables, rows


def run_query(graph, query, *, bindings: Optional[Mapping[str, Any]] = None) -> QueryResult:
    """Run one competency or negative query and decide its verdict."""
    variables, rows = _rows(graph, query.sparql, bindings)
    if isinstance(query, NegativeQuery):
        passed = len(rows) == 0
        note = "" if passed else "prohibited pattern found: %s" % query.prohibition
    else:
        passed = len(rows) >= query.min_rows
        note = (
            ""
            if passed
            else "competency query returned %d rows, expected at least %d: %s"
            % (len(rows), query.min_rows, query.question)
        )
    return QueryResult(
        query_id=query.query_id,
        passed=passed,
        row_count=len(rows),
        rows=rows,
        variables=variables,
        note=note,
    )


def run_suite(
    graph,
    *,
    reasoned: bool,
    bindings: Optional[Mapping[str, Mapping[str, Any]]] = None,
    queries: Optional[Sequence[Any]] = None,
) -> QuerySuiteReport:
    """Run the whole suite, honestly.

    ``reasoned`` says whether ``graph`` already carries OWL entailments. A
    query marked ``expects_reasoning`` run against an unreasoned graph is
    reported as **failed**, with a note saying why, rather than as a pass on a
    graph that could not possibly answer it.
    """
    per_query = dict(bindings or {})
    selected = list(queries) if queries is not None else list(COMPETENCY_QUERIES) + list(
        NEGATIVE_QUERIES
    )

    results: List[QueryResult] = []
    for query in selected:
        if getattr(query, "expects_reasoning", False) and not reasoned:
            results.append(
                QueryResult(
                    query_id=query.query_id,
                    passed=False,
                    row_count=0,
                    rows=(),
                    variables=(),
                    note=(
                        "not run: this query depends on the SULO hasParticipant "
                        "property chain and the graph supplied carries no OWL "
                        "entailments. Materialize with validation.reasoning first. "
                        "Reported as a failure rather than a pass so an unreasoned "
                        "run cannot be mistaken for a passing one."
                    ),
                )
            )
            continue
        results.append(run_query(graph, query, bindings=per_query.get(query.query_id)))
    return QuerySuiteReport(results=tuple(results))
