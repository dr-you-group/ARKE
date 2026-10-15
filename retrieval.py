"""Candidate retrieval: ontology-grounded scoring on the Playbook graph, and the direct embedding baseline.

Every scorer ranks all Playbook codes and returns the Top-N. Scores are rounded to 5 decimals before a
stable descending sort, so ties keep Playbook row order.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import AbstractSet, Any, DefaultDict, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple, Union

from llm_parser import ParsedProcedure
from playbook import Playbook

log = logging.getLogger(__name__)

TOP_N = 10
METHODS = ("weighted", "jaccard", "match", "f1", "lcs", "direct")


@dataclass(frozen=True)
class Candidate:
    """A Playbook code proposed for a procedure name, with its retrieval score."""

    loinc_num: str
    long_common_name: str
    score: float
    details: Dict[str, Any] = field(default_factory=dict, compare=False)


# ---------------------------------------------------------------- weights

HIGH_WEIGHT_RELATIONS: FrozenSet[str] = frozenset(
    {
        "Modality.Modality Type",
        "Modality.Modality Subtype",
        "Anatomic Location.Region Imaged",
        "Anatomic Location.Imaging Focus",
        "Timing",
        "Pharmaceutical.Substance Given",
        "View.View Type",
        "Anatomic Location.Laterality.Presence",
        "Anatomic Location.Laterality",
    }
)


def relation_key(part_type: str) -> str:
    """Edge label of the knowledge graph: the last two dotted segments after removing "Rad.".

    A single-segment type such as "Rad.Timing" is kept unchanged, and
    "Rad.Anatomic Location.Laterality.Presence" becomes "Laterality.Presence". Neither equals its entry
    in HIGH_WEIGHT_RELATIONS, so those two attributes score with the default weight. The published
    results were produced this way.
    """
    parts = part_type.replace("Rad.", "").split(".")
    return parts[-2] + "." + parts[-1] if len(parts) >= 2 else part_type


@dataclass(frozen=True)
class AttributeWeights:
    """w(a) of weighted matching: ``high`` for clinically important attributes, else ``default``."""

    high_weight_relations: FrozenSet[str] = HIGH_WEIGHT_RELATIONS
    high: float = 1.5
    default: float = 1.0

    def of_part_type(self, part_type: str) -> float:
        return self.high if relation_key(part_type) in self.high_weight_relations else self.default


DEFAULT_WEIGHTS = AttributeWeights()


# ---------------------------------------------------------------- set-based scorers


def _top(results: List[Candidate], top_n: int) -> List[Candidate]:
    return sorted(results, key=lambda c: c.score, reverse=True)[:top_n]


def _count(counter: Dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


class _RidSetScorer:
    """Compares the input RID set (A) with each Playbook code's RID set (B)."""

    def __init__(self, playbook: Playbook) -> None:
        self._playbook = playbook

    def rank(self, parsed: ParsedProcedure, top_n: int = TOP_N) -> List[Candidate]:
        return self.rank_rids(parsed.input_rids(self._playbook), top_n)

    def rank_rids(self, input_rids: AbstractSet[str], top_n: int = TOP_N) -> List[Candidate]:
        raise NotImplementedError

    def _candidate(self, loinc_num: str, score: float, **details: object) -> Candidate:
        return Candidate(loinc_num, self._playbook.long_common_name(loinc_num), round(score, 5), dict(details))


class JaccardScorer(_RidSetScorer):
    """|A∩B| / |A∪B|; codes sharing no attribute are dropped."""

    def rank_rids(self, input_rids: AbstractSet[str], top_n: int = TOP_N) -> List[Candidate]:
        results = []
        for loinc_num, loinc_rids in self._playbook.loinc_rids().items():
            union = input_rids | loinc_rids
            if not union:
                continue
            matched = input_rids & loinc_rids
            score = len(matched) / len(union)
            if score == 0:
                continue
            results.append(self._candidate(loinc_num, score, matched_rids=list(matched)))
        return _top(results, top_n)


class SimpleOverlapScorer(_RidSetScorer):
    """|A∩B| − |B−A| − |A−B| (matched minus missing minus extra)."""

    def __init__(self, playbook: Playbook, penalty_missing: float = 1.0, penalty_extra: float = 1.0) -> None:
        super().__init__(playbook)
        self._penalty_missing = penalty_missing
        self._penalty_extra = penalty_extra

    def rank_rids(self, input_rids: AbstractSet[str], top_n: int = TOP_N) -> List[Candidate]:
        results = []
        for loinc_num, loinc_rids in self._playbook.loinc_rids().items():
            matched, missing, extra = input_rids & loinc_rids, loinc_rids - input_rids, input_rids - loinc_rids
            score = len(matched) - self._penalty_missing * len(missing) - self._penalty_extra * len(extra)
            results.append(
                self._candidate(
                    loinc_num, score, matched_rids=list(matched), missing_rids=list(missing), extra_rids=list(extra)
                )
            )
        return _top(results, top_n)


class WeightedMatchScorer(_RidSetScorer):
    """Σ w(matched) − Σ w(missing) − 1.0 × |extra| (ARKE default).

    Missing attributes take the weight of their Playbook edge; extra input attributes have no edge to
    the candidate and are charged the default weight.
    """

    def __init__(
        self,
        playbook: Playbook,
        weights: AttributeWeights = DEFAULT_WEIGHTS,
        penalty_missing: float = 1.0,
        penalty_extra: float = 1.0,
    ) -> None:
        super().__init__(playbook)
        self._weights = weights
        self._penalty_missing = penalty_missing
        self._penalty_extra = penalty_extra

    def rank_rids(self, input_rids: AbstractSet[str], top_n: int = TOP_N) -> List[Candidate]:
        results = []
        for loinc_num, loinc_rids in self._playbook.loinc_rids().items():
            matched, missing, extra = input_rids & loinc_rids, loinc_rids - input_rids, input_rids - loinc_rids
            breakdown: Dict[str, Dict[str, int]] = {"matched": {}, "missing": {}, "extra": {}}
            score = 0.0
            for rid in matched:
                part_type = self._edge(loinc_num, rid)
                score += self._weights.of_part_type(part_type)
                _count(breakdown["matched"], relation_key(part_type))
            for rid in missing:
                part_type = self._edge(loinc_num, rid)
                score -= self._weights.of_part_type(part_type) * self._penalty_missing
                _count(breakdown["missing"], relation_key(part_type))
            for _ in extra:
                score -= self._weights.default * self._penalty_extra
                _count(breakdown["extra"], "default")
            results.append(
                self._candidate(
                    loinc_num,
                    score,
                    matched_rids=list(matched),
                    missing_rids=list(missing),
                    extra_rids=list(extra),
                    score_breakdown=breakdown,
                )
            )
        return _top(results, top_n)

    def _edge(self, loinc_num: str, rid: str) -> str:
        part_type = self._playbook.edge_part_type(loinc_num, rid)
        assert part_type is not None, "matched and missing RIDs are always Playbook edges"
        return part_type


class F1Scorer(_RidSetScorer):
    """Harmonic mean of precision (matched / A) and recall (matched / B); codes with no match dropped."""

    def rank_rids(self, input_rids: AbstractSet[str], top_n: int = TOP_N) -> List[Candidate]:
        results = []
        for loinc_num, loinc_rids in self._playbook.loinc_rids().items():
            matched = input_rids & loinc_rids
            if not matched:
                continue
            precision = len(matched) / len(input_rids)
            recall = len(matched) / len(loinc_rids)
            f1 = 2 * precision * recall / (precision + recall)
            results.append(self._candidate(loinc_num, f1, matched_rids=list(matched)))
        return _top(results, top_n)


# ---------------------------------------------------------------- LCS (Lowest Common Subsumer)


class RadLexHierarchy:
    """RadLex is-a hierarchy as a parent → child graph."""

    def __init__(self, nodes: Iterable[str], edges: Iterable[Tuple[str, str]]) -> None:
        self._nodes: Set[str] = set(nodes)
        self._parents: DefaultDict[str, Set[str]] = defaultdict(set)
        self._children: DefaultDict[str, Set[str]] = defaultdict(set)
        for parent, child in edges:
            self._nodes.update((parent, child))
            self._parents[child].add(parent)
            self._children[parent].add(child)
        self._depth = self._compute_depths()
        self._ancestor_cache: Dict[str, Set[str]] = {}

    def __contains__(self, rid: object) -> bool:
        return rid in self._nodes

    def depth(self, rid: str) -> int:
        return self._depth.get(rid, 0)

    def _compute_depths(self) -> Dict[str, int]:
        """Shortest distance from any root; nodes no root reaches get depth 0."""
        roots = [n for n in self._nodes if not self._parents.get(n)]
        depth: Dict[str, int] = {root: 0 for root in roots}
        queue = deque(roots)
        while queue:
            node = queue.popleft()
            for child in self._children.get(node, ()):
                if child not in depth:
                    depth[child] = depth[node] + 1
                    queue.append(child)
        return {n: depth.get(n, 0) for n in self._nodes}

    def ancestors_inclusive(self, rid: str) -> Set[str]:
        if rid not in self._ancestor_cache:
            seen = {rid}
            stack = [rid]
            while stack:
                for parent in self._parents.get(stack.pop(), ()):
                    if parent not in seen:
                        seen.add(parent)
                        stack.append(parent)
            self._ancestor_cache[rid] = seen
        return self._ancestor_cache[rid]

    def lowest_common_subsumer(self, rid1: str, rid2: str) -> Optional[str]:
        if rid1 == rid2:
            return rid1
        if rid1 not in self or rid2 not in self:
            return None
        common = self.ancestors_inclusive(rid1) & self.ancestors_inclusive(rid2)
        if not common:
            return None
        return max(common, key=self.depth)

    def similarity(self, rid1: str, rid2: str) -> float:
        """Wu-Palmer: 2·depth(LCS) / (depth(a) + depth(b)); 1.0 for identical RIDs."""
        if rid1 == rid2:
            return 1.0
        lcs = self.lowest_common_subsumer(rid1, rid2)
        if lcs is None:
            return 0.0
        denominator = self.depth(rid1) + self.depth(rid2)
        if denominator == 0:
            return 0.0
        return 2.0 * self.depth(lcs) / denominator


def _extract_rid(entity: Any) -> Optional[str]:
    name = getattr(entity, "name", "") or ""
    if re.match(r"^RID\d+$", name):
        return name
    match = re.search(r"(RID\d+)", getattr(entity, "iri", "") or str(entity))
    return match.group(1) if match else None


def load_radlex_hierarchy(path: Union[str, Path]) -> RadLexHierarchy:
    """Loads the RadLex is-a hierarchy from RadLex.owl (requires owlready2)."""
    from owlready2 import ThingClass, get_ontology

    ontology = get_ontology(str(path)).load()
    nodes: List[str] = []
    edges: List[Tuple[str, str]] = []
    for cls in ontology.classes():
        child = _extract_rid(cls)
        if not child:
            continue
        nodes.append(child)
        for parent in cls.is_a:
            if isinstance(parent, ThingClass):
                parent_rid = _extract_rid(parent)
                if parent_rid:
                    edges.append((parent_rid, child))
    return RadLexHierarchy(nodes, edges)


class LcsScorer:
    """Per attribute type, mean of the best hierarchy similarities in both directions."""

    def __init__(self, playbook: Playbook, hierarchy: RadLexHierarchy, missing_penalty: float = 0.5) -> None:
        self._playbook = playbook
        self._hierarchy = hierarchy
        self._missing_penalty = missing_penalty

    def rank(self, parsed: ParsedProcedure, top_n: int = TOP_N) -> List[Candidate]:
        input_relation_rids = parsed.relation_rids(self._playbook)
        results = []
        for loinc_num, candidate_relation_rids in self._playbook.loinc_relation_rids().items():
            total = 0.0
            breakdown = {}
            for relation in set(input_relation_rids) | set(candidate_relation_rids):
                input_rids = set(input_relation_rids.get(relation, set()))
                candidate_rids = set(candidate_relation_rids.get(relation, set()))
                score, pairs = self._relation_score(input_rids, candidate_rids)
                total += score
                breakdown[relation] = {
                    "score": round(score, 5),
                    "input_rids": sorted(input_rids),
                    "candidate_rids": sorted(candidate_rids),
                    "best_pairs": pairs,
                }
            results.append(
                Candidate(
                    loinc_num,
                    self._playbook.long_common_name(loinc_num),
                    round(total, 5),
                    {"score_breakdown": breakdown},
                )
            )
        return _top(results, top_n)

    def _best_match(self, source: str, targets: Set[str]) -> Tuple[Optional[str], float]:
        best_rid, best_score = None, 0.0
        for target in targets:
            similarity = self._hierarchy.similarity(source, target)
            if similarity > best_score:
                best_rid, best_score = target, similarity
        return best_rid, best_score

    def _relation_score(self, input_rids: Set[str], candidate_rids: Set[str]) -> Tuple[float, List[tuple]]:
        if not input_rids and not candidate_rids:
            return 0.0, []
        if not input_rids or not candidate_rids:
            return -self._missing_penalty * max(len(input_rids), len(candidate_rids)), []
        pairs = []
        forward = []
        for rid in input_rids:
            best_rid, best = self._best_match(rid, candidate_rids)
            pairs.append((rid, best_rid, round(best, 5)))
            forward.append(best)
        backward = [self._best_match(rid, input_rids)[1] for rid in candidate_rids]
        return (sum(forward) / len(forward) + sum(backward) / len(backward)) / 2.0, pairs


# ---------------------------------------------------------------- direct baseline


class DirectRetriever:
    """Baseline: FAISS over ada-002 embeddings of the Playbook code names (requires langchain and faiss).

    Score is ``1 - distance`` as reported by LangChain's FAISS store.
    """

    _NAME_MARK = "LONG_COMMON_NAME: "

    def __init__(self, vectorstore: Any) -> None:
        self._vectorstore = vectorstore

    @classmethod
    def build(cls, imaging_codes_csv: Union[str, Path], embedding_model: str) -> DirectRetriever:
        from langchain_community.document_loaders.csv_loader import CSVLoader
        from langchain_community.vectorstores import FAISS
        from langchain_openai import OpenAIEmbeddings

        docs = CSVLoader(str(imaging_codes_csv), source_column="LOINC_NUM").load()
        return cls(FAISS.from_documents(docs, OpenAIEmbeddings(model=embedding_model)))

    def retrieve(self, procedure_name: str, top_n: int = TOP_N) -> List[Candidate]:
        candidates = []
        for doc, distance in self._vectorstore.similarity_search_with_score(procedure_name, k=top_n):
            content = doc.page_content
            if self._NAME_MARK in content:
                candidates.append(
                    Candidate(
                        loinc_num=doc.metadata.get("source", ""),
                        long_common_name=content.split(self._NAME_MARK)[1].strip(),
                        score=round(1 - distance, 5),
                    )
                )
        return candidates


# ---------------------------------------------------------------- entry points


def make_scorer(method: str, playbook: Playbook, radlex_owl: Optional[Union[str, Path]] = None) -> Any:
    if method == "weighted":
        return WeightedMatchScorer(playbook)
    if method == "jaccard":
        return JaccardScorer(playbook)
    if method == "match":
        return SimpleOverlapScorer(playbook)
    if method == "f1":
        return F1Scorer(playbook)
    if method == "lcs":
        if radlex_owl is None:
            raise ValueError("the lcs method needs a RadLex OWL file")
        return LcsScorer(playbook, load_radlex_hierarchy(radlex_owl))
    raise ValueError(f"unknown retrieval method: {method}")


def retrieve_candidates(parsed_json_texts: Sequence[object], scorer: Any, top_n: int = TOP_N) -> List[List[Candidate]]:
    """Parser outputs → Top-N candidates each; unreadable rows get an empty list."""
    lists = []
    for row, raw in enumerate(parsed_json_texts):
        try:
            lists.append(scorer.rank(ParsedProcedure.from_json_text(raw), top_n))
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the batch
            log.warning("row %d: %s (raw=%r)", row, exc, raw)
            lists.append([])
    return lists


def candidates_cell(candidates: Sequence[Candidate]) -> str:
    """``candidates`` column: every field the scorer produced (matched_rids, score_breakdown, ...)."""
    return str(
        [
            {"loinc_num": c.loinc_num, "long_common_name": c.long_common_name, "score": c.score, **c.details}
            for c in candidates
        ]
    )


def filtered_candidates_cell(candidates: Sequence[Candidate]) -> str:
    """``filtered_candidates`` column: code, name, and score only."""
    return str(
        [{"loinc_num": c.loinc_num, "long_common_name": c.long_common_name, "score": c.score} for c in candidates]
    )


def candidates_from_records(records: Sequence[Dict[str, Any]]) -> List[Candidate]:
    return [Candidate(r.get("loinc_num", ""), r.get("long_common_name", ""), r.get("score")) for r in records]
