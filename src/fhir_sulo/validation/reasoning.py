"""OWL reasoning: the SULO PRO property-chain entailment, and consistency.

Choice: HermiT, through ROBOT, in Docker, pinned by image digest
================================================================
The entailment the pilot depends on is (DR-002, verified against SULO 0.2.12)::

    sulo:hasParticipant owl:propertyChainAxiom
        ( sulo:hasParticipant [ owl:inverseOf sulo:hasFeature ] ) .

A **property chain containing an inverse property** is outside OWL 2 EL. An
EL reasoner does not report that it cannot do it - it returns fewer
entailments and exits 0. So the reasoner must be OWL 2 DL, and the choice must
be *verified*, not read off a feature table.
``verify_property_chain_support`` does that, and
``tests/integration/test_reasoning_pro.py`` fails if the reasoner is swapped
for one that cannot do it. ELK is checked in the same test as a negative
control, and it does indeed silently entail nothing.

The pilot brief prohibits a JVM dependency *for the mapping stack*; a JVM
reasoner is acceptable. There is no ``java`` on the host, so ROBOT runs in
Docker, pinned by image digest rather than by tag, because a tag can be
repointed.

The trap this module exists to avoid
------------------------------------
``robot merge -i sulo.ttl -i data.ttl`` **loses the entailment**, silently and
with exit code 0. OWLAPI parses each input file as its own RDF-to-OWL unit, so
in ``data.ttl`` - which contains no ``owl:ObjectProperty`` declaration for
``sulo:hasParticipant`` - the participation triples are parsed as
``AnnotationAssertion``. Annotations carry no semantics, the chain never fires,
and the output looks plausible. Measured on this host:

* two ``-i`` inputs:   ``AnnotationAssertion(sulo:hasParticipant ...)``, no entailment
* one merged input:    ``ObjectPropertyAssertion``, entailment present

So ``materialize`` merges the ontology and the data into **one parse unit**
with rdflib before handing anything to ROBOT, and declares any domain term the
ontology does not. ``probe_separate_parse_units`` reproduces the trap, and a
test pins it, so the merge cannot be "simplified away" later.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "ROBOT_IMAGE_TAG",
    "ROBOT_IMAGE_DIGEST",
    "ROBOT_IMAGE",
    "DEFAULT_REASONER",
    "SULO_PATH",
    "SULO_SHA256",
    "SULO_VERSION",
    "ReasonerUnavailable",
    "ReasoningError",
    "InconsistentOntology",
    "ChainVerification",
    "ConsistencyReport",
    "RobotReasoner",
    "verify_property_chain_support",
    "probe_separate_parse_units",
    "PRO_PROBE_TTL",
    "PRO_REFUTATION_TTL",
]

ROBOT_IMAGE_TAG = "obolibrary/robot:v1.9.7"
ROBOT_IMAGE_DIGEST = (
    "sha256:58da5acb0bb861ca84409213f2b6e15ab41eda145e602ef5cfdf87d974ec5976"
)
ROBOT_IMAGE = "obolibrary/robot@%s" % ROBOT_IMAGE_DIGEST
"""Pinned by digest. A tag can be repointed; a digest cannot."""

DEFAULT_REASONER = "HermiT"
"""OWL 2 DL. ELK (EL) and JFact are the other reasoners ROBOT ships; ELK
cannot do this chain, which the verification test demonstrates rather than
asserts."""

DEFAULT_AXIOM_GENERATORS = ("PropertyAssertion", "ClassAssertion")

DEFAULT_EXCLUDE_TAUTOLOGIES = "structural"
"""Drop tautological inferences. Not an optimisation detail - a correctness
and scale requirement.

SULO makes ``hasPart``, ``contains`` and ``isIn`` reflexive and transitive,
and every individual is related to every other by ``owl:topObjectProperty``.
The property-assertion generator therefore emits O(n^2) triples per batch that
say nothing. Measured on 40 synthetic encounters (1,508 input triples):

=========================== ========= ==================================
setting                     time      inferred lines
=========================== ========= ==================================
``-A PropertyAssertion``      2.65 s   95,949  (305 topObjectProperty)
``+ -t structural``           1.95 s    2,924  (0 topObjectProperty)
=========================== ========= ==================================

A 33x reduction in output and a quadratic term removed. The PRO entailment
survives - it is not a tautology - and ``verify_property_chain`` is run with
this setting active, so that is checked rather than assumed."""

_HERE = os.path.dirname(os.path.abspath(__file__))
SULO_PATH = os.path.join(_HERE, "ontology", "sulo-0.2.12.ttl")
SULO_VERSION = "0.2.12"
SULO_SHA256 = "ea4bd090e5677db18446b255b81c6c8f844c2d6e4e29424bacf13b06d29e5c8c"
"""Of ``versions/sulo-0.2.12.ttl`` at commit
``1a4abc1699471187e94fbc59591101b2b635d6ea`` of ``AIDAVA-DEV/sulo`` (DR-002).
Vendored so the reasoning tests run offline and so an upstream force-push
cannot change what the pilot was verified against. Checked by a test."""

# Namespaces whose predicates are metadata, not OWL object properties. Left
# undeclared so they stay annotations: asserting prov:wasDerivedFrom as an
# object property would drag every FHIR source IRI into the DL signature for
# no benefit.
_ANNOTATION_NAMESPACES = (
    "http://www.w3.org/ns/prov#",
    "http://purl.org/dc/terms/",
    "http://purl.org/dc/elements/1.1/",
    "http://www.w3.org/2004/02/skos/core#",
    "urn:fhir-sulo:prov#",
    "urn:fhir-sulo:shapes#",
)

# The RDF/RDFS/OWL/XSD vocabularies are OWL's own *structural* syntax, not
# domain terms. Declaring anything in them is actively destructive: an
# injected `owl:complementOf a owl:ObjectProperty` makes OWLAPI re-read a
# class expression as a plain object property assertion, and the expression
# silently stops constraining anything.
#
# This is not hypothetical. An earlier version of this module declared them,
# and `verify_property_chain` caught it: the entailment still materialized,
# but the refutation stopped being detected - because the refutation's
# `owl:complementOf` restriction had been dismantled. That is precisely why
# the verification has two independent halves.
_STRUCTURAL_NAMESPACES = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2001/XMLSchema#",
)


class ReasonerUnavailable(RuntimeError):
    """Docker or the pinned ROBOT image is not available on this host."""


class ReasoningError(RuntimeError):
    """ROBOT failed for a reason other than an inconsistent ontology."""


class InconsistentOntology(ReasoningError):
    """The reasoner found the ontology inconsistent."""


@dataclass(frozen=True)
class ChainVerification:
    """Evidence that the chosen reasoner performs the PRO entailment."""

    reasoner: str
    image: str
    entailment_materialized: bool
    refutation_detected: bool
    inferred_triple: str
    evidence: Tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """Both checks must pass.

        ``entailment_materialized`` alone would also be true if the axiom
        generator invented the triple; ``refutation_detected`` alone would be
        true if the reasoner were sound but the generator never emitted
        anything. Together they say the reasoner entails it *and* the pipeline
        surfaces it.
        """
        return self.entailment_materialized and self.refutation_detected

    def report(self) -> str:
        lines = [
            "reasoner:                 %s" % self.reasoner,
            "image:                    %s" % self.image,
            "entailment materialized:  %s" % self.entailment_materialized,
            "refutation detected:      %s" % self.refutation_detected,
            "expected inferred triple: %s" % self.inferred_triple,
            "verdict:                  %s" % ("USABLE" if self.usable else "NOT USABLE"),
        ]
        lines.extend("  %s" % e for e in self.evidence)
        return "\n".join(lines)


@dataclass(frozen=True)
class ConsistencyReport:
    consistent: bool
    reasoner: str
    detail: str = ""


# The hand-written probe graph, exactly the concept note section 6 pattern
# reduced to its smallest form. Written out as text rather than built
# programmatically so that what the reasoner is asked is readable in the diff.
PRO_PROBE_TTL = """
@prefix sulo: <https://w3id.org/sulo/> .
@prefix ex:   <https://example.org/fhir-sulo/> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .

ex:encounter-9 a sulo:Process ;
    sulo:hasParticipant ex:patient-role-enc-9 .

ex:patient-role-enc-9 a sulo:Role ;
    sulo:isFeatureOf ex:person-p123 .

ex:person-p123 a sulo:SpatialObject .
"""

# The same graph plus an explicit denial of the entailment. If the reasoner
# entails `encounter-9 hasParticipant person-p123`, this is inconsistent. This
# is the check that cannot be passed by an axiom generator's accident: it asks
# the reasoner itself, not the serialiser.
PRO_REFUTATION_TTL = """
@prefix sulo: <https://w3id.org/sulo/> .
@prefix ex:   <https://example.org/fhir-sulo/> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .

ex:encounter-9 a sulo:Process ;
    sulo:hasParticipant ex:patient-role-enc-9 ;
    a [ a owl:Class ;
        owl:complementOf [ a owl:Restriction ;
            owl:onProperty sulo:hasParticipant ;
            owl:hasValue ex:person-p123 ] ] .

ex:patient-role-enc-9 a sulo:Role ;
    sulo:isFeatureOf ex:person-p123 .

ex:person-p123 a sulo:SpatialObject .
"""

EXPECTED_INFERRED_TRIPLE = (
    "<https://example.org/fhir-sulo/encounter-9> "
    "<https://w3id.org/sulo/hasParticipant> "
    "<https://example.org/fhir-sulo/person-p123>"
)


def reasoner_available() -> bool:
    """Can an OWL reasoner be run here at all?

    True if ``robot`` is on PATH (the benchmark image, or a developer machine
    with a JVM) or Docker can start the pinned image. Tests skip on this
    rather than on Docker alone, so that a container which has ROBOT but not
    Docker still exercises them.
    """
    return shutil.which("robot") is not None or _docker_available()


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True, text=True,
    )
    return probe.returncode == 0


class RobotReasoner:
    """Drives ROBOT, locally if it is on PATH and otherwise in the pinned image.

    **Local backend.** If ``robot`` is on ``PATH`` it is invoked directly. That
    is how the Gate 4 benchmark image runs: it carries the ROBOT jar copied
    from the same pinned digest, so the reasoner runs *inside* the
    ``--cpus=4 --memory=8g`` cgroup and its JVM shows up in the measured peak.
    Shelling out to Docker from inside the container would put the JVM in a
    different cgroup and the memory figure would be a fiction.

    **Docker backend.** Otherwise a container is created from the pinned image
    and files are shipped in and out with ``docker cp``. Colima shares only
    the VM owner's home directory, so a bind mount into the scratchpad does
    not work on the pilot host (DR-301 operational note); this is the same
    pattern ``tools/engine/run.sh`` uses. The container is created once and
    reused, because JVM start-up dominates the cost of a small ontology.

    Either way it is the same ROBOT build. ``backend`` reports which was used,
    and the benchmark report prints it.
    """

    def __init__(
        self,
        *,
        reasoner: str = DEFAULT_REASONER,
        image: str = ROBOT_IMAGE,
        cpus: Optional[str] = None,
        memory: Optional[str] = None,
        java_max_heap: Optional[str] = None,
        declare_terms: bool = True,
        ontology_path: str = SULO_PATH,
        exclude_tautologies: Optional[str] = DEFAULT_EXCLUDE_TAUTOLOGIES,
        prefer_local: bool = True,
    ) -> None:
        self.prefer_local = prefer_local
        self.reasoner = reasoner
        self.image = image
        self.cpus = cpus
        self.memory = memory
        self.java_max_heap = java_max_heap
        self.declare_terms = declare_terms
        self.ontology_path = ontology_path
        self.exclude_tautologies = exclude_tautologies
        self._container: Optional[str] = None
        self._local = bool(prefer_local and shutil.which("robot"))

    # ------------------------------------------------------------- lifecycle

    @property
    def backend(self) -> str:
        return "local robot on PATH" if self._local else "docker %s" % ROBOT_IMAGE_TAG

    def __enter__(self) -> "RobotReasoner":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        if self._local or self._container is not None:
            return
        if not _docker_available():
            raise ReasonerUnavailable(
                "docker is not available. The OWL reasoner runs in the pinned "
                "image %s because there is no java on this host." % ROBOT_IMAGE_TAG
            )
        name = "fhir-sulo-robot-%s" % uuid.uuid4().hex[:10]
        cmd = ["docker", "run", "-d", "--name", name, "-w", "/w"]
        if self.cpus:
            cmd.append("--cpus=%s" % self.cpus)
        if self.memory:
            cmd.append("--memory=%s" % self.memory)
        if self.java_max_heap:
            cmd.extend(["-e", "ROBOT_JAVA_ARGS=-Xmx%s" % self.java_max_heap])
        cmd.extend(["--entrypoint", "sleep", self.image, "infinity"])
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ReasonerUnavailable(
                "could not start the pinned reasoner container: %s"
                % (proc.stderr.strip() or proc.stdout.strip())
            )
        self._container = name

    def close(self) -> None:
        if self._container is None:
            return
        subprocess.run(
            ["docker", "rm", "-f", self._container], capture_output=True, text=True
        )
        self._container = None

    # ----------------------------------------------------------------- input

    @staticmethod
    def _graph_of(data):
        import rdflib

        if isinstance(data, rdflib.Graph):
            return data
        graph = rdflib.Graph()
        if isinstance(data, str):
            fmt = "turtle" if ("@prefix" in data or "PREFIX" in data) else "nt"
            graph.parse(data=data, format=fmt)
        elif isinstance(data, (list, tuple)):
            graph.parse(data="\n".join(str(q) for q in data), format="nt")
        else:
            raise TypeError("cannot read a graph from %s" % type(data).__name__)
        return graph

    def _declared_terms(self):
        import rdflib

        ontology = rdflib.Graph()
        ontology.parse(self.ontology_path, format="turtle")
        OWL = rdflib.OWL
        declared = set()
        for kind in (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
                     OWL.Class, rdflib.RDFS.Class):
            declared.update(ontology.subjects(rdflib.RDF.type, kind))
        return ontology, declared

    def _merged_input(self, data_graph, include_ontology: bool = True):
        """Ontology and data in ONE graph, with missing domain terms declared.

        Both halves of this matter and neither is optional; see the module
        docstring for the measurement that shows why.
        """
        import rdflib

        merged = rdflib.Graph()
        ontology, declared = self._declared_terms()
        if include_ontology:
            for triple in ontology:
                merged.add(triple)
        for triple in data_graph:
            merged.add(triple)

        if not self.declare_terms:
            return merged

        OWL, RDF = rdflib.OWL, rdflib.RDF
        classes, object_props, data_props, individuals = set(), set(), set(), set()

        def structural(term) -> bool:
            return any(str(term).startswith(ns) for ns in _STRUCTURAL_NAMESPACES)

        for subject, predicate, obj in data_graph:
            if predicate == RDF.type:
                if (
                    isinstance(obj, rdflib.URIRef)
                    and obj not in declared
                    and not structural(obj)
                ):
                    classes.add(obj)
                if isinstance(subject, rdflib.URIRef) and not structural(subject):
                    individuals.add(subject)
                continue
            if not isinstance(predicate, rdflib.URIRef) or structural(predicate):
                continue
            if any(str(predicate).startswith(ns) for ns in _ANNOTATION_NAMESPACES):
                continue
            if predicate in declared:
                if isinstance(subject, rdflib.URIRef) and not structural(subject):
                    individuals.add(subject)
                if isinstance(obj, rdflib.URIRef) and not structural(obj):
                    individuals.add(obj)
                continue
            if isinstance(obj, rdflib.Literal):
                data_props.add(predicate)
            else:
                object_props.add(predicate)
                if isinstance(obj, rdflib.URIRef) and not structural(obj):
                    individuals.add(obj)
            if isinstance(subject, rdflib.URIRef) and not structural(subject):
                individuals.add(subject)

        for term in classes:
            merged.add((term, RDF.type, OWL.Class))
        for term in object_props:
            merged.add((term, RDF.type, OWL.ObjectProperty))
        for term in data_props:
            merged.add((term, RDF.type, OWL.DatatypeProperty))
        for term in individuals - classes - object_props - data_props - declared:
            merged.add((term, RDF.type, OWL.NamedIndividual))
        return merged

    # ------------------------------------------------------------- execution

    def _run_robot(self, args: Sequence[str]) -> subprocess.CompletedProcess:
        if self._local:
            env = dict(os.environ)
            if self.java_max_heap:
                env["ROBOT_JAVA_ARGS"] = "-Xmx%s" % self.java_max_heap
            return subprocess.run(
                ["robot"] + list(args), capture_output=True, text=True, env=env
            )
        if self._container is None:
            self.start()
        return subprocess.run(
            ["docker", "exec", self._container, "robot"] + list(args),
            capture_output=True, text=True,
        )

    def _ship(self, local_path: str, remote_name: str) -> str:
        remote = "/w/%s" % remote_name
        proc = subprocess.run(
            ["docker", "cp", local_path, "%s:%s" % (self._container, remote)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise ReasoningError("docker cp in failed: %s" % proc.stderr.strip())
        return remote

    def _fetch(self, remote: str, local_path: str) -> bool:
        proc = subprocess.run(
            ["docker", "cp", "%s:%s" % (self._container, remote), local_path],
            capture_output=True, text=True,
        )
        return proc.returncode == 0

    def _reason_files(
        self,
        input_paths: Sequence[str],
        *,
        axiom_generators: Sequence[str] = DEFAULT_AXIOM_GENERATORS,
        inferences_only: bool = True,
        reasoner: Optional[str] = None,
    ):
        """Run ``robot [merge] reason`` over already-prepared local files."""
        self.start()
        scratch = tempfile.mkdtemp(prefix="fhir-sulo-robot-")
        try:
            if self._local:
                remotes = list(input_paths)
                out_remote = os.path.join(scratch, "out.ttl")
            else:
                remotes = [
                    self._ship(path, "in%02d.ttl" % index)
                    for index, path in enumerate(input_paths)
                ]
                out_remote = "/w/out-%s.ttl" % uuid.uuid4().hex[:8]
            return self._invoke(
                remotes, out_remote, scratch, axiom_generators, inferences_only, reasoner
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _invoke(
        self, remotes, out_remote, scratch, axiom_generators, inferences_only, reasoner
    ):
        import rdflib

        args: List[str] = []
        if len(remotes) > 1:
            args.append("merge")
            for remote in remotes:
                args.extend(["-i", remote])
            args.append("reason")
        else:
            args.extend(["reason", "-i", remotes[0]])
        args.extend(["-r", reasoner or self.reasoner])
        if axiom_generators:
            args.extend(["-A", " ".join(axiom_generators)])
            # Only meaningful with a generator; on a bare consistency check
            # there is no inferred axiom set to prune.
            if self.exclude_tautologies:
                args.extend(["-t", self.exclude_tautologies])
        if inferences_only:
            args.extend(["-n", "true"])
        args.extend(["-o", out_remote])

        proc = self._run_robot(args)
        combined = (proc.stdout or "") + (proc.stderr or "")
        if "ontology is inconsistent" in combined.lower():
            raise InconsistentOntology(combined.strip())
        if proc.returncode != 0:
            raise ReasoningError(
                "robot reason failed (exit %d): %s" % (proc.returncode, combined.strip())
            )

        graph = rdflib.Graph()
        if self._local:
            if not os.path.exists(out_remote):
                raise ReasoningError("robot produced no output file")
            graph.parse(out_remote, format="turtle")
            return graph
        local = os.path.join(scratch, "out.ttl")
        if not self._fetch(out_remote, local):
            raise ReasoningError("robot produced no output file")
        graph.parse(local, format="turtle")
        return graph

    def materialize(
        self,
        data,
        *,
        axiom_generators: Sequence[str] = DEFAULT_AXIOM_GENERATORS,
        include_ontology: bool = True,
    ):
        """Return the *inferred* triples for ``data`` under SULO.

        Only the inferences, not the input, so a caller can see exactly what
        reasoning added. Union it with the asserted graph to query over both;
        ``reason_and_merge`` does that.
        """
        merged = self._merged_input(self._graph_of(data), include_ontology=include_ontology)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "merged.ttl")
            merged.serialize(path, format="turtle")
            return self._reason_files([path], axiom_generators=axiom_generators)

    def reason_and_merge(self, data, **kwargs):
        """Asserted graph plus its entailments, ready for competency queries."""
        asserted = self._graph_of(data)
        inferred = self.materialize(asserted, **kwargs)
        import rdflib

        out = rdflib.Graph()
        for triple in asserted:
            out.add(triple)
        for triple in inferred:
            out.add(triple)
        return out

    def check_consistency(self, data, *, include_ontology: bool = True) -> ConsistencyReport:
        """Is the asserted graph consistent with SULO?"""
        try:
            self.materialize(
                data, axiom_generators=(), include_ontology=include_ontology
            )
        except InconsistentOntology as exc:
            return ConsistencyReport(False, self.reasoner, str(exc))
        return ConsistencyReport(True, self.reasoner, "no inconsistency reported")

    # ---------------------------------------------------------- verification

    def verify_property_chain(self) -> ChainVerification:
        """Prove that this reasoner performs the SULO PRO chain entailment.

        Two independent checks, because either alone can be passed for the
        wrong reason:

        1. **Materialization** - reason over the probe graph and look for
           ``encounter-9 hasParticipant person-p123`` among the inferences.
        2. **Refutation** - reason over the same graph plus an explicit denial
           of that triple, and require the reasoner to report the ontology
           inconsistent. This asks the reasoner directly and cannot be
           satisfied by a serialiser that invented the triple.
        """
        import rdflib

        evidence: List[str] = []

        inferred = self.materialize(PRO_PROBE_TTL)
        expected = (
            rdflib.URIRef("https://example.org/fhir-sulo/encounter-9"),
            rdflib.URIRef("https://w3id.org/sulo/hasParticipant"),
            rdflib.URIRef("https://example.org/fhir-sulo/person-p123"),
        )
        materialized = expected in inferred
        evidence.append(
            "materialization: %d inferred triples; expected triple %s"
            % (len(inferred), "PRESENT" if materialized else "ABSENT")
        )

        try:
            self.materialize(PRO_REFUTATION_TTL, axiom_generators=())
            refuted = False
            evidence.append(
                "refutation: reasoner accepted a graph that denies the entailment, "
                "so it does not entail it"
            )
        except InconsistentOntology:
            refuted = True
            evidence.append(
                "refutation: reasoner reported the denial inconsistent, so it does "
                "entail the triple"
            )

        return ChainVerification(
            reasoner=self.reasoner,
            image=self.image,
            entailment_materialized=materialized,
            refutation_detected=refuted,
            inferred_triple=EXPECTED_INFERRED_TRIPLE,
            evidence=tuple(evidence),
        )

    def probe_separate_parse_units(self) -> bool:
        """Reproduce the OWLAPI annotation trap. Returns True if it still bites.

        Hands ROBOT the ontology and the data as **two** ``-i`` inputs, the way
        one would naively write it. OWLAPI parses each separately, the data
        file declares no object properties, the participation triples become
        ``AnnotationAssertion``, and the entailment silently disappears.

        This exists so that the merge in ``_merged_input`` has a test behind
        it: if someone replaces it with a two-file invocation, the test that
        calls this notices.
        """
        import rdflib

        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "data.ttl")
            rdflib.Graph().parse(data=PRO_PROBE_TTL, format="turtle").serialize(
                data_path, format="turtle"
            )
            inferred = self._reason_files([self.ontology_path, data_path])
        expected = (
            rdflib.URIRef("https://example.org/fhir-sulo/encounter-9"),
            rdflib.URIRef("https://w3id.org/sulo/hasParticipant"),
            rdflib.URIRef("https://example.org/fhir-sulo/person-p123"),
        )
        return expected not in inferred


def verify_property_chain_support(
    reasoner: str = DEFAULT_REASONER, **kwargs
) -> ChainVerification:
    """Convenience wrapper: start a reasoner, verify the chain, tear it down."""
    with RobotReasoner(reasoner=reasoner, **kwargs) as robot:
        return robot.verify_property_chain()


def probe_separate_parse_units(reasoner: str = DEFAULT_REASONER, **kwargs) -> bool:
    with RobotReasoner(reasoner=reasoner, **kwargs) as robot:
        return robot.probe_separate_parse_units()
