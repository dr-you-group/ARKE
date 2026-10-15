"""Settings, OpenAI calls, batching, and Excel cell helpers shared by the ARKE modules."""

from __future__ import annotations

import ast
import asyncio
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, TypeVar

from prompts import SYSTEM_PROMPT

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_CHAT_MODEL = "gpt-4o-2024-08-06"
DEFAULT_EMBEDDING_MODEL = "text-embedding-ada-002"
DEFAULT_BATCH_SIZE = 15


@dataclass(frozen=True)
class Settings:
    chat_model: str
    embedding_model: str
    playbook_csv: Path
    imaging_codes_csv: Path
    radlex_owl: Path
    batch_size: int


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal KEY=VALUE reader; variables already set in the environment win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_settings() -> Settings:
    load_dotenv()
    env = os.environ.get
    return Settings(
        chat_model=env("ARKE_CHAT_MODEL", DEFAULT_CHAT_MODEL),
        embedding_model=env("ARKE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        playbook_csv=Path(env("ARKE_PLAYBOOK_CSV", "LoincRsnaRadiologyPlaybook_2025.csv")),
        imaging_codes_csv=Path(env("ARKE_IMAGING_CODES_CSV", "ImagingDocumentCodes_2025.csv")),
        radlex_owl=Path(env("ARKE_RADLEX_OWL", "Radlex.owl")),
        batch_size=int(env("ARKE_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))),
    )


def require_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set (export it or put it in .env)")


class OpenAIChat:
    """One chat completion per prompt with the ARKE system prompt at temperature 0."""

    def __init__(self, client: Optional[Any] = None, model: str = DEFAULT_CHAT_MODEL) -> None:
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI()
        self._client = client
        self._model = model

    async def complete(self, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""


async def run_in_batches(
    items: Sequence[T], call: Callable[[T], Awaitable[R]], batch_size: int = DEFAULT_BATCH_SIZE
) -> List[R]:
    """Run ``call`` concurrently within each batch, and batches one after another."""
    results: List[R] = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        results.extend(await asyncio.gather(*(call(item) for item in batch)))
    return results


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def read_cell_list(cell: Any) -> List[Dict[str, Any]]:
    """Reads a ``candidates``/``filtered_candidates`` cell written as a Python list of dicts."""
    if is_blank(cell):
        return []
    return ast.literal_eval(cell) if isinstance(cell, str) else list(cell)
