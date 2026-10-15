"""LLM Parser: decomposes a local procedure name into the 18 Playbook attributes."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, DefaultDict, Dict, FrozenSet, List, Sequence, Set

from playbook import Playbook, normalize_relation
from prompts import PARSER_PROMPT
from utils import DEFAULT_BATCH_SIZE, OpenAIChat, run_in_batches

_EMPTY_VALUES = {"", "nan", "none", "xxx"}


class InvalidParserOutput(ValueError):
    """Parser output could not be read as Playbook-schema JSON."""


def clean_json_text(raw: object) -> str:
    """Strips the ```json fence the LLM wraps around its answer."""
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidParserOutput("Empty or invalid JSON string")
    cleaned = re.sub(r"^```json\s*", "", raw.strip())
    return re.sub(r"```$", "", cleaned.strip())


@dataclass(frozen=True)
class ParsedProcedure:
    """A procedure name decomposed into Playbook attributes."""

    name: str
    parts: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json_text(cls, raw: object) -> ParsedProcedure:
        try:
            data = json.loads(clean_json_text(raw))
        except json.JSONDecodeError as exc:
            raise InvalidParserOutput(str(exc)) from exc
        if not isinstance(data, dict):
            raise InvalidParserOutput("Parser output is not a JSON object")
        return cls(name=str(data.get("Name", "")), parts=dict(data.get("Parts", {}) or {}))

    def input_rids(self, playbook: Playbook) -> FrozenSet[str]:
        """RIDs of the parsed values, looked up by name across all attribute types.

        A value matches the first Playbook RID with the same name, regardless of attribute type.
        """
        rids: Set[str] = set()
        for value in self.parts.values():
            if not value or value == "NaN":
                continue
            for item in value if isinstance(value, list) else [value]:
                if not isinstance(item, str):
                    raise InvalidParserOutput(f"Attribute value is not text: {item!r}")
                rid = playbook.first_rid_named(item)
                if rid is not None:
                    rids.add(rid)
        return frozenset(rids)

    def relation_rids(self, playbook: Playbook) -> Dict[str, Set[str]]:
        """RIDs grouped by attribute type, looked up within that type first (used by LCS)."""
        grouped: DefaultDict[str, Set[str]] = defaultdict(set)
        for raw_key, raw_value in self.parts.items():
            relation = normalize_relation(raw_key)
            for value in _listify(raw_value):
                rid = playbook.rid_for_value(value, relation=relation)
                if rid:
                    grouped[relation].add(rid)
        return dict(grouped)


def _listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, float) and math.isnan(value):
        return []
    if isinstance(value, str) and value.strip().lower() in _EMPTY_VALUES:
        return []
    return [value]


async def parse_procedures(names: Sequence[str], chat: OpenAIChat, batch_size: int = DEFAULT_BATCH_SIZE) -> List[str]:
    """Procedure names → raw Parser answers (Playbook-schema JSON, stored as ``input_text_json``)."""

    async def parse(name: str) -> str:
        return await chat.complete(PARSER_PROMPT.format(input_text=name))

    return await run_in_batches(names, parse, batch_size)
