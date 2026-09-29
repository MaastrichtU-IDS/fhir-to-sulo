"""FHIR R4 JSON -> FHIR RDF, deterministically, over the pinned profile subset.

Specification followed: https://hl7.org/fhir/R4/rdf.html. Conventions verified
against HL7's own published Turtle (``observation-example-bloodpressure.ttl``,
``observation-example-f205-egfr.ttl``, ``encounter-example.ttl``), which the
oracle test in ``tests/contracts/ingest/test_oracle_conformance.py`` reproduces.

Why not the HL7 validator CLI: see
``docs/fhir-sulo/decisions/DR-101-fhir-rdf-renderer.md``. The short version is
that ``ValidationEngine.convert`` is hard-coded to JSON or XML, so the CLI
cannot emit Turtle at all.

Determinism contract
--------------------
* Blank nodes are labelled ``b0``..``bN`` by a depth-first walk in FHIR element
  order (object key order as it appears in the source JSON, arrays in index
  order). The same JSON therefore always yields the same labels.
* The canonical serialisation is sorted N-Triples, so even a change in walk
  order could not change the canonical bytes.
* Nothing here reads the network, the clock, the environment or a random
  source.

Fidelity contract
-----------------
Any element or type not present in the pinned element table raises
:class:`~fhir_sulo.ingest.manifest.ManifestError`. Silent dropping is the
failure mode the acceptance matrix row "Source fidelity" exists to prevent, so
it is made impossible rather than tested for.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .jsonio import FhirNumber
from .manifest import Manifest, ManifestError, default_manifest
from .ntriples import BNode, IRI, Literal, Triple, serialize

RDF_TYPE = IRI("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
OWL_ONTOLOGY = "http://www.w3.org/2002/07/owl#Ontology"
OWL_IMPORTS = "http://www.w3.org/2002/07/owl#imports"
OWL_VERSION_IRI = "http://www.w3.org/2002/07/owl#versionIRI"
XSD = "http://www.w3.org/2001/XMLSchema#"

# FHIR temporal lexical forms -> xsd datatype (manifest documents the policy;
# these patterns implement it).
_RE_YEAR = re.compile(r"^\d{4}$")
_RE_YEAR_MONTH = re.compile(r"^\d{4}-\d{2}$")
_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+\-]\d{2}:\d{2})$")

_RELATIVE_REF = re.compile(r"^(?:[A-Z][A-Za-z]+)/[A-Za-z0-9\-.]{1,64}(?:/_history/[A-Za-z0-9\-.]{1,64})?$")


class RenderError(ValueError):
    pass


def temporal_datatype(lexical: str, fhir_type: str) -> str:
    """Pick the xsd datatype that preserves the source temporal precision."""
    if _RE_DATETIME.match(lexical):
        return XSD + "dateTime"
    if _RE_DATE.match(lexical):
        return XSD + "date"
    if _RE_YEAR_MONTH.match(lexical):
        return XSD + "gYearMonth"
    if _RE_YEAR.match(lexical):
        return XSD + "gYear"
    raise RenderError(
        f"{fhir_type} value {lexical!r} does not match any FHIR R4 temporal form; "
        "refusing to guess a datatype and lose precision"
    )


class RenderedResource:
    """The rendered graph plus the bookkeeping ingestion needs afterwards."""

    def __init__(self, triples: List[Triple], root: IRI, resource_type: str,
                 renderer_id: str, modifier_extension_urls: Tuple[str, ...],
                 node_paths: Dict[Any, str]):
        self.triples = triples
        self.root = root
        self.resource_type = resource_type
        self.renderer_id = renderer_id
        self.modifier_extension_urls = modifier_extension_urls
        #: node term -> FHIRPath-ish location, for evidence and diagnostics
        self.node_paths = node_paths

    @property
    def nt(self) -> str:
        """The canonical serialisation: sorted N-Triples."""
        return serialize(self.triples)


class FhirRdfRenderer:
    def __init__(self, manifest: Optional[Manifest] = None, **option_overrides):
        self.m = manifest or default_manifest()
        self.options = self.m.renderer_options
        unknown = set(option_overrides) - set(self.options)
        if unknown:
            raise RenderError(f"unknown renderer options: {sorted(unknown)}")
        self.options.update(option_overrides)

    # -- public -------------------------------------------------------------

    def render(self, resource: Dict[str, Any], base: Optional[str] = None) -> RenderedResource:
        base = base if base is not None else self.m.server_base
        rtype = resource.get("resourceType")
        if not rtype:
            raise RenderError("resource has no resourceType")
        if not self.m.has_type(rtype):
            raise ManifestError(f"resourceType {rtype!r} is not in the pinned element table")

        rid = resource.get("id")
        if not rid:
            raise RenderError(f"{rtype} has no id; the canonical IRI cannot be formed")

        state = _State(base)
        root = IRI(base + rtype + "/" + str(rid))
        state.node_paths[root] = rtype

        state.emit(Triple(root, RDF_TYPE, IRI(self.m.fhir_base + rtype)))
        if self.options.get("emit_node_role_tree_root", True):
            state.emit(Triple(root, IRI(self.m.fhir_base + "nodeRole"),
                              IRI(self.m.fhir_base + "treeRoot")))

        self._render_object(resource, rtype, root, rtype, state, skip={"resourceType"})

        if self.options.get("emit_reference_stub_types", True):
            for iri, target_type in sorted(state.reference_stubs.items()):
                state.emit(Triple(IRI(iri), RDF_TYPE, IRI(self.m.fhir_base + target_type)))

        if self.options.get("emit_ontology_header", False):
            doc = IRI(base + rtype + "/" + str(rid) + ".ttl")
            state.emit(Triple(doc, RDF_TYPE, IRI(OWL_ONTOLOGY)))
            state.emit(Triple(doc, IRI(OWL_IMPORTS), IRI(self.m.fhir_base + "fhir.ttl")))

        return RenderedResource(
            triples=state.triples, root=root, resource_type=rtype,
            renderer_id=self.m.renderer_id,
            modifier_extension_urls=tuple(state.modifier_extension_urls),
            node_paths=state.node_paths,
        )

    # -- internals ----------------------------------------------------------

    def _render_object(self, obj: Dict[str, Any], type_name: str, subject,
                       path: str, state: "_State", skip=()) -> None:
        for key, value in obj.items():
            if key in skip:
                continue
            if key.startswith("_"):
                raise ManifestError(
                    f"{path}.{key}: primitive extension elements are not in the pinned "
                    "subset; refusing rather than dropping them"
                )
            ed = self.m.element_def(type_name, key)
            predicate = IRI(self.m.fhir_base + ed["predicate"])
            child_path = f"{path}.{key}"
            if ed.get("repeats"):
                if not isinstance(value, list):
                    raise RenderError(f"{child_path}: expected an array")
                for index, item in enumerate(value):
                    node = self._render_value(item, ed, subject, predicate,
                                              f"{child_path}[{index}]", state,
                                              index=index)
                    if node is not None and isinstance(node, (BNode, IRI)):
                        state.emit(Triple(node, IRI(self.m.fhir_base + "index"),
                                          Literal(str(index), XSD + "integer")))
            else:
                if isinstance(value, list):
                    raise RenderError(f"{child_path}: expected a single value, got an array")
                self._render_value(value, ed, subject, predicate, child_path, state)

            if ed.get("modifier"):
                for item in (value if isinstance(value, list) else [value]):
                    if isinstance(item, dict) and "url" in item:
                        state.modifier_extension_urls.append(str(item["url"]))

    def _render_value(self, value: Any, ed: Dict[str, Any], subject, predicate: IRI,
                      path: str, state: "_State", index: Optional[int] = None):
        ftype = ed["type"]

        if ftype == "#resource":
            # A contained resource: its own resourceType drives the element table.
            if not isinstance(value, dict):
                raise RenderError(f"{path}: contained entry must be an object")
            ctype = value.get("resourceType")
            if not ctype or not self.m.has_type(ctype):
                raise ManifestError(f"{path}: contained resourceType {ctype!r} is not in scope")
            node = state.bnode(path)
            state.emit(Triple(subject, predicate, node))
            state.emit(Triple(node, RDF_TYPE, IRI(self.m.fhir_base + ctype)))
            self._render_object(value, ctype, node, path, state, skip={"resourceType"})
            return node

        if self.m.is_primitive(ftype):
            literal = self._primitive_literal(value, ftype, path)
            if ed.get("raw_literal"):
                # Narrative.div and friends are direct string objects.
                state.emit(Triple(subject, predicate, literal))
                return None
            node = state.bnode(path)
            state.emit(Triple(subject, predicate, node))
            state.emit(Triple(node, IRI(self.m.fhir_base + "value"), literal))
            if ed.get("link"):
                state.emit(Triple(node, IRI(self.m.fhir_base + "link"), IRI(str(value))))
            return node

        # Complex datatype or backbone element.
        if not isinstance(value, dict):
            raise RenderError(f"{path}: expected an object for FHIR type {ftype}")
        node = state.bnode(path)
        state.emit(Triple(subject, predicate, node))
        self._render_object(value, ftype, node, path, state)

        if ftype == "Reference":
            self._render_reference_link(value, node, path, state)
        if ftype == "Coding" and self.options.get("emit_code_system_class_assertions", False):
            self._render_code_class(value, node, state)
        return node

    def _render_reference_link(self, ref: Dict[str, Any], node, path: str, state: "_State") -> None:
        literal = ref.get("reference")
        if literal is None:
            return
        text = str(literal)
        if text.startswith("#"):
            # Contained reference: there is no external IRI to link to. The
            # resolution is recorded as evidence by references.py, not invented
            # as a graph edge here.
            return
        if text.startswith("http://") or text.startswith("https://") or text.startswith("urn:"):
            absolute = text
            target_type = _type_from_reference(text)
        elif _RELATIVE_REF.match(text):
            absolute = state.base + text
            target_type = text.split("/", 1)[0]
        else:
            # Not a form this pilot resolves. Leave the literal in place with no
            # fhir:link; references.py reports it as unresolvable.
            return
        state.emit(Triple(node, IRI(self.m.fhir_base + "link"), IRI(absolute)))
        if target_type:
            state.reference_stubs[absolute] = target_type

    def _render_code_class(self, coding: Dict[str, Any], node, state: "_State") -> None:
        system, code = coding.get("system"), coding.get("code")
        if system is None or code is None:
            return
        template = self.m.code_system_iri_templates.get(str(system))
        if template is None:
            return
        state.emit(Triple(node, RDF_TYPE, IRI(template.replace("{code}", str(code)))))

    def _primitive_literal(self, value: Any, ftype: str, path: str) -> Literal:
        xsd = self.m.primitive_xsd(ftype)
        if xsd is None:
            if isinstance(value, bool) or isinstance(value, FhirNumber):
                raise RenderError(f"{path}: expected a JSON string for FHIR type {ftype}")
            return Literal(str(value))
        if xsd == "#temporal":
            if not isinstance(value, str) or isinstance(value, FhirNumber):
                raise RenderError(f"{path}: expected a JSON string for FHIR type {ftype}")
            return Literal(value, temporal_datatype(value, ftype))
        if xsd.endswith("#boolean"):
            if not isinstance(value, bool):
                raise RenderError(f"{path}: expected a JSON boolean for FHIR type {ftype}")
            return Literal("true" if value else "false", xsd)
        # integer / decimal: the lexical form must survive exactly.
        if not isinstance(value, FhirNumber):
            raise RenderError(
                f"{path}: expected a JSON number for FHIR type {ftype}, got {type(value).__name__}; "
                "parse the source with fhir_sulo.ingest.jsonio so the lexical form is preserved"
            )
        return Literal(str(value), xsd)


def _type_from_reference(absolute: str) -> Optional[str]:
    parts = absolute.rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if re.match(r"^[A-Z][A-Za-z]+$", parts[i]):
            return parts[i]
    return None


class _State:
    def __init__(self, base: str):
        self.base = base
        self.triples: List[Triple] = []
        self.counter = 0
        self.node_paths: Dict[Any, str] = {}
        self.reference_stubs: Dict[str, str] = {}
        self.modifier_extension_urls: List[str] = []

    def emit(self, triple: Triple) -> None:
        self.triples.append(triple)

    def bnode(self, path: str) -> BNode:
        node = BNode(f"b{self.counter}")
        self.counter += 1
        self.node_paths[node] = path
        return node


def render(resource: Dict[str, Any], manifest: Optional[Manifest] = None,
           base: Optional[str] = None, **options) -> RenderedResource:
    return FhirRdfRenderer(manifest, **options).render(resource, base=base)
