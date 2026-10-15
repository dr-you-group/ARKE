import asyncio
import json
from types import SimpleNamespace

import pytest
from fixtures import FOOT_STANDING_AP_RT

from llm_parser import parse_procedures
from llm_selector import Selection, format_candidates, select_candidates
from prompts import PARSER_PROMPT, SELECTOR_PROMPT, SYSTEM_PROMPT
from retrieval import Candidate
from utils import OpenAIChat, run_in_batches

CANDIDATES = [Candidate("24000-1", "XR Foot - right Views AP W standing", 7.5, {"matched_rids": ["RID1"]})]


class StubClient:
    """Stands in for AsyncOpenAI: records requests and answers with fixed content."""

    def __init__(self, content):
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._content = content

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))])


def test_parser_calls_gpt_4o_once_with_system_prompt_and_temperature_0():
    client = StubClient(FOOT_STANDING_AP_RT)

    [answer] = asyncio.run(parse_procedures(["Foot Standing AP Rt"], OpenAIChat(client=client)))

    [request] = client.requests
    assert answer == FOOT_STANDING_AP_RT
    assert request["model"] == "gpt-4o-2024-08-06" and request["temperature"] == 0
    assert request["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert request["messages"][1]["content"] == PARSER_PROMPT.format(input_text="Foot Standing AP Rt")


def test_selector_prompt_contains_only_candidate_codes_and_names():
    answer = (
        "```json\n"
        + json.dumps({"reasoning": "AP", "selected_loinc": "24000-1", "long_common_name": "XR Foot"})
        + "\n```"
    )
    client = StubClient(answer)

    [(raw, selection)] = asyncio.run(
        select_candidates([("Foot Standing AP Rt", CANDIDATES)], OpenAIChat(client=client))
    )

    prompt = client.requests[0]["messages"][1]["content"]
    assert prompt == SELECTOR_PROMPT.format(
        input_text="Foot Standing AP Rt", top_candidates_str=format_candidates(CANDIDATES)
    )
    assert "RID1" not in prompt and "7.5" not in format_candidates(CANDIDATES)
    assert raw == answer and selection == Selection("24000-1", "XR Foot", "AP")
    assert selection.is_within(CANDIDATES)


def test_non_json_selector_answer_leaves_no_selection():
    [(raw, selection)] = asyncio.run(select_candidates([("x", [])], OpenAIChat(client=StubClient("sorry"))))

    assert (raw, selection) == ("sorry", None)


def test_non_json_answer_is_not_a_selection():
    with pytest.raises(ValueError):
        Selection.from_json_text("I think 24000-1")


def test_calls_run_concurrently_within_a_batch_and_batches_run_in_order():
    running, peak = 0, 0

    async def call(item):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0)
        running -= 1
        return item * 2

    results = asyncio.run(run_in_batches(list(range(7)), call, batch_size=3))

    assert results == [0, 2, 4, 6, 8, 10, 12] and peak == 3
