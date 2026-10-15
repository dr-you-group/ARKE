"""LLM Selector: chooses exactly one Playbook code from the Top-10 candidates."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from prompts import SELECTOR_PROMPT
from retrieval import Candidate
from utils import DEFAULT_BATCH_SIZE, OpenAIChat, run_in_batches

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Selection:
    """The code chosen by the Selector, with its chain-of-thought reasoning."""

    loinc_num: str
    long_common_name: str
    reasoning: str = ""

    @classmethod
    def from_json_text(cls, raw: object) -> Selection:
        if not isinstance(raw, str):
            raise ValueError("Selector output is not text")
        data = json.loads(raw.strip("```json").strip("```"))  # noqa: B005 - strips characters, as in the experiments
        if not isinstance(data, dict):
            raise ValueError("Selector output is not a JSON object")
        return cls(
            loinc_num=str(data.get("selected_loinc", "")).strip(),
            long_common_name=str(data.get("long_common_name", "")).strip(),
            reasoning=str(data.get("reasoning", "")),
        )

    def is_within(self, candidates: Sequence[Candidate]) -> bool:
        """True when the choice stays inside the candidate set."""
        return self.loinc_num in [c.loinc_num for c in candidates]


def format_candidates(candidates: Sequence[Candidate]) -> str:
    """Candidates as given to the Selector: code and name only."""
    return "\n".join(f"LOINC_NUM: {c.loinc_num}\nLONG_COMMON_NAME: {c.long_common_name}" for c in candidates)


def read_selection(raw: str) -> Optional[Selection]:
    """The selection in a raw answer, or None when the answer cannot be read."""
    try:
        return Selection.from_json_text(raw)
    except Exception as exc:  # noqa: BLE001 - an unreadable answer counts as no selection
        log.warning("selector output unreadable: %s", exc)
        return None


async def select_candidates(
    items: Sequence[Tuple[str, List[Candidate]]], chat: OpenAIChat, batch_size: int = DEFAULT_BATCH_SIZE
) -> List[Tuple[str, Optional[Selection]]]:
    """(procedure name, candidates) pairs → (raw answer, selection) pairs."""

    async def select(item: Tuple[str, List[Candidate]]) -> str:
        name, candidates = item
        prompt = SELECTOR_PROMPT.format(input_text=name, top_candidates_str=format_candidates(candidates))
        return await chat.complete(prompt)

    answers = await run_in_batches(items, select, batch_size)
    return [(raw, read_selection(raw)) for raw in answers]
