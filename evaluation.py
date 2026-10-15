"""Evaluation: Recall@k, MRR, NDCG@10 with 95% CI, McNemar test, and candidate overlap."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from statistics import NormalDist
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from utils import read_cell_list

RECALL_KS = (1, 3, 5, 10)


@dataclass(frozen=True)
class RankedPrediction:
    """One evaluated procedure name: gold code, retrieved Top-10 codes, and the selected code."""

    gold: str
    candidates: Tuple[str, ...]
    selected: Optional[str] = None

    def gold_rank(self) -> Optional[int]:
        """0-based position of the gold code among the candidates, or None when absent."""
        return self.candidates.index(self.gold) if self.gold in self.candidates else None

    def hit_at(self, k: int) -> bool:
        return self.gold in self.candidates[:k]

    def reciprocal_rank(self) -> float:
        rank = self.gold_rank()
        return 0.0 if rank is None else 1 / (rank + 1)

    def ndcg(self) -> float:
        """Single relevant item, so IDCG = 1 and NDCG = 1/log2(rank + 2)."""
        rank = self.gold_rank()
        return 0.0 if rank is None else 1 / math.log2(rank + 2)

    def selection_correct(self) -> bool:
        return self.selected is not None and self.selected == self.gold


# ---------------------------------------------------------------- confidence intervals


@dataclass(frozen=True)
class Estimate:
    point: float
    low: float
    high: float

    def format(self, digits: int = 2) -> str:
        return f"{self.point:.{digits}f} ({self.low:.{digits}f}-{self.high:.{digits}f})"


def wilson_interval(successes: int, total: int, alpha: float = 0.05) -> Estimate:
    """Wilson score interval for a proportion."""
    proportion = successes / total
    z = NormalDist().inv_cdf(1 - alpha / 2)
    z2 = z * z
    denominator = 1 + z2 / total
    center = (proportion + z2 / (2 * total)) / denominator
    half_width = z * math.sqrt(proportion * (1 - proportion) / total + z2 / (4 * total**2)) / denominator
    return Estimate(proportion, center - half_width, center + half_width)


def bootstrap_mean_interval(values: Sequence[float], n_boot: int = 10000, seed: int = 42) -> Estimate:
    """Percentile bootstrap 95% CI of the mean."""
    rng = np.random.default_rng(seed)
    array = np.asarray(values)
    means = [rng.choice(array, size=len(array), replace=True).mean() for _ in range(n_boot)]
    return Estimate(float(array.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


# ---------------------------------------------------------------- metrics


@dataclass(frozen=True)
class RetrievalReport:
    """Final selection Recall@1, retrieval Recall@k, MRR, and NDCG@10 with 95% CI for one method."""

    n: int
    final_recall_at_1: Estimate
    recall_at: Dict[int, Estimate]
    mrr: Estimate
    ndcg_at_10: Estimate

    @classmethod
    def of(cls, predictions: Sequence[RankedPrediction], n_boot: int = 10000, seed: int = 42) -> RetrievalReport:
        n = len(predictions)
        return cls(
            n=n,
            final_recall_at_1=wilson_interval(sum(p.selection_correct() for p in predictions), n),
            recall_at={k: wilson_interval(sum(p.hit_at(k) for p in predictions), n) for k in RECALL_KS},
            mrr=bootstrap_mean_interval([p.reciprocal_rank() for p in predictions], n_boot, seed),
            ndcg_at_10=bootstrap_mean_interval([p.ndcg() for p in predictions], n_boot, seed),
        )

    def as_row(self, digits: int = 2) -> Dict[str, str]:
        row = {"Final selection Recall@1": self.final_recall_at_1.format(digits)}
        row.update({f"Recall@{k}": est.format(digits) for k, est in self.recall_at.items()})
        row["MRR"] = self.mrr.format(digits)
        row["NDCG@10"] = self.ndcg_at_10.format(digits)
        return row


@dataclass(frozen=True)
class McNemarResult:
    """b: reference correct and other wrong; c: reference wrong and other correct."""

    b: int
    c: int
    statistic: float
    pvalue: float


def mcnemar(reference_correct: Sequence[bool], other_correct: Sequence[bool]) -> McNemarResult:
    """Chi-square McNemar test with continuity correction."""
    if len(reference_correct) != len(other_correct):
        raise ValueError("McNemar needs paired outcomes on the same samples")
    b = sum(1 for r, o in zip(reference_correct, other_correct) if r and not o)
    c = sum(1 for r, o in zip(reference_correct, other_correct) if not r and o)
    if b + c == 0:
        return McNemarResult(b, c, math.nan, math.nan)
    statistic = (abs(b - c) - 1) ** 2 / (b + c)
    return McNemarResult(b, c, statistic, math.erfc(math.sqrt(statistic / 2)))


@dataclass(frozen=True)
class OverlapSummary:
    """Mean agreement among the Top-10 candidate sets of several retrieval methods."""

    all_intersection: float
    avg_pairwise_intersection: float
    consensus: Dict[str, float]


def candidate_overlap(candidates_by_method: Mapping[str, Sequence[Sequence[str]]]) -> OverlapSummary:
    names = list(candidates_by_method)
    if len(names) < 2:
        raise ValueError("overlap needs at least two methods")
    lengths = {len(candidates_by_method[n]) for n in names}
    if len(lengths) != 1:
        raise ValueError("every method must cover the same rows")
    rows: List[Dict[str, float]] = []
    for i in range(lengths.pop()):
        sets = [set(candidates_by_method[n][i]) for n in names]
        counter: Counter = Counter()
        for s in sets:
            counter.update(s)
        pair_sizes = [len(a & b) for a, b in combinations(sets, 2)]
        row = {"all": float(len(set.intersection(*sets))), "pairwise": sum(pair_sizes) / len(pair_sizes)}
        for k in range(2, len(names)):
            row[f">={k}"] = float(sum(1 for v in counter.values() if v >= k))
        row[f"=={len(names)}"] = float(sum(1 for v in counter.values() if v == len(names)))
        rows.append(row)
    mean = {key: sum(r[key] for r in rows) / len(rows) for key in rows[0]}
    consensus = {f"consensus_{k}": v for k, v in mean.items() if k not in ("all", "pairwise")}
    return OverlapSummary(mean["all"], mean["pairwise"], consensus)


# ---------------------------------------------------------------- result files


def _selected_code(raw: Any) -> Optional[str]:
    """Selected code in a raw Selector answer; unreadable answers count as no selection."""
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw.strip("```json").strip("```"))  # noqa: B005 - strips characters, as in the experiments
        return str(data.get("selected_loinc", "")).strip()
    except Exception:  # noqa: BLE001
        return None


def read_predictions(
    path: str, candidates_column: str = "candidates", exclude_missing_gold: bool = False
) -> List[RankedPrediction]:
    """Reads a mapping result Excel file (columns LoincNumber, candidates, res)."""
    df = pd.read_excel(path)
    if exclude_missing_gold:
        df = df[df["LoincNumber"].notna()]
    res = df["res"] if "res" in df.columns else [None] * len(df)
    return [
        RankedPrediction(
            gold=str(gold).strip(),
            candidates=tuple(str(r["loinc_num"]).strip() for r in read_cell_list(cell)),
            selected=_selected_code(raw),
        )
        for gold, cell, raw in zip(df["LoincNumber"], df[candidates_column], res)
    ]


def metrics_table(predictions_by_method: Mapping[str, Sequence[RankedPrediction]], digits: int = 2) -> pd.DataFrame:
    rows = []
    for method, predictions in predictions_by_method.items():
        report = RetrievalReport.of(predictions)
        rows.append({"Method": method, "N": report.n, **report.as_row(digits)})
    return pd.DataFrame(rows)


def compare_methods(
    reference: Sequence[RankedPrediction], others: Mapping[str, Sequence[RankedPrediction]]
) -> Dict[str, McNemarResult]:
    """McNemar test of final-selection correctness against the reference method."""
    ref = [p.selection_correct() for p in reference]
    return {name: mcnemar(ref, [p.selection_correct() for p in preds]) for name, preds in others.items()}
