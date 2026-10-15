"""LOINC/RSNA Radiology Playbook as an ontology knowledge graph (LOINC codes ↔ RadLex attributes)."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, Iterator, Optional, Set, Tuple, Union


@dataclass(frozen=True)
class PlaybookRow:
    """One row of the Playbook CSV: a LOINC code linked to one RadLex attribute."""

    loinc_num: str
    long_common_name: str
    rid: str
    part_type: str
    part_name: str


def normalize_relation(part_type: object) -> str:
    """PartTypeName without the "Rad." prefix."""
    if part_type is None:
        return ""
    text = re.sub(r"^\s*Rad\.", "", str(part_type).strip())
    return re.sub(r"\s+", " ", text)


def normalize_name(text: object) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text).strip().lower())


class Playbook:
    """Knowledge graph of LOINC codes (central nodes) and RadLex attributes (RID nodes).

    Lookups keep the order of the source rows, so ranking ties resolve in Playbook row order.
    """

    def __init__(self, rows: Iterable[PlaybookRow]) -> None:
        self._loinc_rids: Dict[str, Set[str]] = {}
        self._long_common_names: Dict[str, str] = {}
        self._rid_names: Dict[str, str] = {}
        self._edge_part_types: Dict[Tuple[str, str], str] = {}
        self._loinc_relation_rids: Dict[str, DefaultDict[str, Set[str]]] = {}
        self._name_to_rids: DefaultDict[str, Set[str]] = defaultdict(set)
        self._name_to_rids_by_relation: DefaultDict[str, DefaultDict[str, Set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for row in rows:
            self._add(row)
        self._first_rid_by_name: Dict[str, str] = {}
        for rid, name in self._rid_names.items():
            self._first_rid_by_name.setdefault(name.strip().lower(), rid)

    def _add(self, row: PlaybookRow) -> None:
        self._loinc_rids.setdefault(row.loinc_num, set()).add(row.rid)
        self._long_common_names[row.loinc_num] = row.long_common_name
        self._rid_names[row.rid] = row.part_name
        self._edge_part_types[(row.loinc_num, row.rid)] = row.part_type

        relation = normalize_relation(row.part_type)
        self._loinc_relation_rids.setdefault(row.loinc_num, defaultdict(set))[relation].add(row.rid)
        name = normalize_name(row.part_name)
        self._name_to_rids[name].add(row.rid)
        self._name_to_rids_by_relation[relation][name].add(row.rid)

    def loinc_rids(self) -> Dict[str, Set[str]]:
        return self._loinc_rids

    def loinc_relation_rids(self) -> Dict[str, DefaultDict[str, Set[str]]]:
        return self._loinc_relation_rids

    def long_common_name(self, loinc_num: str) -> str:
        return self._long_common_names.get(loinc_num, "Unknown")

    def rid_name(self, rid: str) -> str:
        return self._rid_names.get(rid, "Unknown")

    def edge_part_type(self, loinc_num: str, rid: str) -> Optional[str]:
        return self._edge_part_types.get((loinc_num, rid))

    def first_rid_named(self, value: str) -> Optional[str]:
        """First RID (in source order) whose name equals ``value`` ignoring case and outer spaces."""
        return self._first_rid_by_name.get(value.strip().lower())

    def rid_for_value(self, value: object, relation: Optional[str] = None) -> Optional[str]:
        """Lookup within the attribute type first, then across all types (used by LCS)."""
        key = normalize_name(value)
        if not key:
            return None
        if relation:
            candidates = sorted(self._name_to_rids_by_relation[normalize_relation(relation)].get(key, ()))
            if candidates:
                return candidates[0]
        candidates = sorted(self._name_to_rids.get(key, ()))
        return candidates[0] if candidates else None


def read_playbook_rows(path: Union[str, Path], name_column: str = "PartName") -> Iterator[PlaybookRow]:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            yield PlaybookRow(
                loinc_num=row["LoincNumber"],
                long_common_name=row["LongCommonName"],
                rid=row["RID"],
                part_type=row["PartTypeName"],
                part_name=row[name_column],
            )


def load_playbook(path: Union[str, Path], name_column: str = "PartName") -> Playbook:
    """Loads LoincRsnaRadiologyPlaybook_<version>.csv (one row per LOINC-RadLex attribute edge)."""
    return Playbook(read_playbook_rows(path, name_column))
