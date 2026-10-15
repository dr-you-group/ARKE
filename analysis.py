"""Analysis: cohort characteristics (chi-square / permutation test), category summaries, attribute agreement."""

from __future__ import annotations

import csv
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Hashable, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

from evaluation import Estimate, wilson_interval
from utils import is_blank, read_cell_list

log = logging.getLogger(__name__)

# Label of the merged "other" category, as written in the published tables.
OTHER = "기타"
NONE_LABEL = "(None)"
REGION = "Rad.Anatomic Location.Region Imaged"
FOCUS = "Rad.Anatomic Location.Imaging Focus"

ATTRIBUTE_KEYS = (
    "Rad.Modality.Modality Type",
    "Rad.Modality.Modality Subtype",
    "Rad.Anatomic Location.Region Imaged",
    "Rad.Anatomic Location.Imaging Focus",
    "Rad.Anatomic Location.Laterality.Presence",
    "Rad.Anatomic Location.Laterality",
    "Rad.View.View Type",
    "Rad.Timing",
    "Rad.Pharmaceutical.Substance Given",
)
COMBINED_ATTRIBUTES = {
    "Modality": ("Rad.Modality.Modality Type", "Rad.Modality.Modality Subtype"),
    "Anatomic Location": ("Rad.Anatomic Location.Region Imaged", "Rad.Anatomic Location.Imaging Focus"),
    "TimingPharm": ("Rad.Timing", "Rad.Pharmaceutical.Substance Given"),
}
MAIN_CATEGORIES: Dict[str, List[str]] = {
    "Modality": ["ct", "imaging modality", "mr", "mr_angio", "nm", "pt+ct", "rf", "rf_angio", "us", "us_doppler", "xr"],
    "Anatomic Location": [
        "abdomen",
        "abdomen_kidney",
        "abdomen_liver",
        "abdomen_spine.lumbar",
        "breast",
        "chest",
        "chest_heart",
        "head",
        "head_brain",
        "lower extremity",
        "lower extremity_foot",
        "lower extremity_hip",
        "lower extremity_knee",
        "neck",
        "pelvis",
        "upper extremity",
        "upper extremity_hand",
        "upper extremity_shoulder",
        "xxx",
    ],
    "TimingPharm": ["w_contrast", "wo_contrast"],
}
COMPARED_ATTRIBUTES = (
    "Rad.Modality.Modality Type",
    "Rad.Modality.Modality Subtype",
    "Rad.Anatomic Location.Region Imaged",
    "Rad.Anatomic Location.Imaging Focus",
    "Rad.View.View Type",
)
ATTRIBUTE_GROUPS = {
    "Pharma + Timing": ("Rad.Pharmaceutical.Substance Given", "Rad.Timing"),
    "Laterality": ("Rad.Anatomic Location.Laterality.Presence", "Rad.Anatomic Location.Laterality"),
}

_MISSING = {"nan", "none", "null", ""}
_PATTERNS = {k: re.compile(rf'"{re.escape(k)}"\s*:\s*(?:\[(.*?)\]|"(.*?)")') for k in ATTRIBUTE_KEYS}
_EDGE_QUOTES = (re.compile(r'^"|"$'), re.compile(r"^'|'$"))


# ---------------------------------------------------------------- attribute extraction


def extract_value(text: object, key: str) -> Optional[str]:
    """Value of ``key`` in Parser JSON text; list values become "a, b"; NaN/none/null/empty become None."""
    if not isinstance(text, str):
        return None
    match = _PATTERNS[key].search(text)
    if not match:
        return None
    value = match.group(1) or match.group(2)
    if value is None:
        return None
    value = value.strip()
    if value and "," in value:
        value = ", ".join(v.strip().strip('"') for v in value.split(","))
    return None if value.lower() in _MISSING else value


def combine(first: Optional[str], second: Optional[str]) -> str:
    """``first_second`` with blanks dropped (e.g. "MR_Angio", or "CT" when there is no subtype)."""
    return (f"{(first or '').strip()}_{(second or '').strip()}").strip("_")


def extract_attributes(text: object) -> Dict[str, Optional[str]]:
    values: Dict[str, Optional[str]] = {k: extract_value(text, k) for k in ATTRIBUTE_KEYS}
    for name, (first, second) in COMBINED_ATTRIBUTES.items():
        values[name] = combine(values[first], values[second])
    return values


# ---------------------------------------------------------------- tokens and counts


def _strip_edge_quotes(text: str) -> str:
    for pattern in _EDGE_QUOTES:
        text = pattern.sub("", text)
    return text


def normalize_tokens(values: Iterable[object]) -> List[str]:
    """Multi-response tokens: lower-case, split on commas, drop edge quotes and missing markers."""
    tokens: List[str] = []
    for value in values:
        if is_blank(value):
            continue
        text = _strip_edge_quotes(str(value).lower().strip())
        if text in _MISSING:
            continue
        for part in text.split(","):
            token = _strip_edge_quotes(part.strip())
            if token not in _MISSING:
                tokens.append(token)
    return tokens


def split_tokens(value: object) -> List[str]:
    """Case-preserving split for Region/Focus summaries: all quotes removed, 'nan' dropped."""
    tokens = []
    for part in str(value).split(","):
        token = part.strip().replace('"', "").replace("'", "")
        if token and token.lower() != "nan":
            tokens.append(token)
    return tokens


def split_tokens_keep_none(value: object) -> List[str]:
    """Like split_tokens, but an empty value counts once as NONE_LABEL."""
    if is_blank(value):
        return [NONE_LABEL]
    return split_tokens(value) or [NONE_LABEL]


@dataclass(frozen=True)
class CategoryShare:
    category: str
    count: int
    percent: float


def count_by_frequency(tokens: Sequence[str]) -> List[CategoryShare]:
    """Category counts, most frequent first (ties keep first-seen order), percent of all tokens."""
    counts = Counter(tokens)
    total = len(tokens)
    return [CategoryShare(c, n, n / total * 100) for c, n in sorted(counts.items(), key=lambda kv: -kv[1])]


def count_main_categories(tokens: Sequence[str], main_categories: Sequence[str]) -> List[CategoryShare]:
    """Counts of the listed categories plus OTHER for everything else; percent rounded to 0.1."""
    total = len(tokens)
    mapped = Counter(t if t in main_categories else OTHER for t in tokens)
    return [
        CategoryShare(c, mapped.get(c, 0), round(mapped.get(c, 0) / total * 100, 1) if total else 0.0)
        for c in list(main_categories) + [OTHER]
    ]


# ---------------------------------------------------------------- two-cohort comparison


@dataclass(frozen=True)
class ContingencyTable:
    categories: Tuple[str, ...]
    group_a: Tuple[int, ...]
    group_b: Tuple[int, ...]

    @classmethod
    def from_tokens(cls, tokens_a: Sequence[str], tokens_b: Sequence[str]) -> ContingencyTable:
        counts_a, counts_b = Counter(tokens_a), Counter(tokens_b)
        categories = tuple(sorted(set(counts_a) | set(counts_b)))
        return cls(
            categories, tuple(counts_a.get(c, 0) for c in categories), tuple(counts_b.get(c, 0) for c in categories)
        )

    def chi_square(self) -> Tuple[float, float, np.ndarray]:
        chi2, p, _, expected = chi2_contingency(np.array([self.group_a, self.group_b]))
        return float(chi2), float(p), expected

    def collapse_sparse(self, min_expected: float = 5.0, max_iter: int = 1000) -> ContingencyTable:
        """Merges the smallest category into OTHER until all expected counts are ≥ min_expected."""
        rows: List[Tuple[str, int, int]] = list(zip(self.categories, self.group_a, self.group_b))
        other_a = other_b = 0
        existing = [r for r in rows if r[0] == OTHER]
        if existing:
            other_a, other_b = existing[0][1], existing[0][2]
            rows = [r for r in rows if r[0] != OTHER]
        iterations = 0
        while iterations < max_iter and len(rows) > 2:
            _, _, _, expected = chi2_contingency(np.array([[r[1] for r in rows], [r[2] for r in rows]]))
            if (expected >= min_expected).all():
                break
            smallest = min(range(len(rows)), key=lambda i: rows[i][1] + rows[i][2])
            other_a += rows[smallest][1]
            other_b += rows[smallest][2]
            del rows[smallest]
            iterations += 1
        rows.append((OTHER, other_a, other_b))
        return ContingencyTable(tuple(r[0] for r in rows), tuple(r[1] for r in rows), tuple(r[2] for r in rows))

    def permutation_pvalue(self, n_iter: int = 20000, seed: int = 42) -> float:
        """Redistributes each category total between the groups (binomial) and compares χ² statistics."""
        rng = np.random.default_rng(seed)
        observed, _, _ = self.chi_square()
        totals = np.array(self.group_a) + np.array(self.group_b)
        p_a = sum(self.group_a) / int(totals.sum())
        exceed = 0
        for _ in range(n_iter):
            draw_a = rng.binomial(totals, p_a)
            chi2, _, _, _ = chi2_contingency(np.array([draw_a, totals - draw_a]))
            if chi2 >= observed:
                exceed += 1
        return (exceed + 1) / (n_iter + 1)


@dataclass(frozen=True)
class GroupComparison:
    raw: ContingencyTable
    tested: ContingencyTable
    pvalue: float
    permutation: bool


def compare_groups(
    tokens_a: Sequence[str], tokens_b: Sequence[str], min_expected: float = 5.0, n_iter: int = 20000, seed: int = 42
) -> GroupComparison:
    """Merges sparse categories, then uses the chi-square p-value, or a permutation p-value if still sparse."""
    raw = ContingencyTable.from_tokens(tokens_a, tokens_b)
    tested = raw.collapse_sparse(min_expected)
    _, pvalue, expected = tested.chi_square()
    if (expected < min_expected).any():
        return GroupComparison(raw, tested, tested.permutation_pvalue(n_iter, seed), True)
    return GroupComparison(raw, tested, pvalue, False)


def _share(n: int, total: int) -> str:
    return f"{n} ({n / total * 100:.1f}%)"


def characteristics_table(
    name_a: str, df_a: pd.DataFrame, name_b: str, df_b: pd.DataFrame, n_iter: int = 20000
) -> pd.DataFrame:
    """Characteristics of two cohorts with a p-value per variable; untestable variables are skipped."""
    rows: List[Dict[str, Any]] = []
    for variable in list(ATTRIBUTE_KEYS) + list(COMBINED_ATTRIBUTES):
        try:
            result = compare_groups(
                normalize_tokens(df_a[variable].values), normalize_tokens(df_b[variable].values), n_iter=n_iter
            )
        except Exception as exc:  # noqa: BLE001 - one untestable variable must not stop the table
            log.warning("Skipped %s: %s", variable, exc)
            continue
        table = result.tested
        total_a, total_b = sum(table.group_a), sum(table.group_b)
        p_text = ("<0.001" if result.pvalue < 0.001 else f"{result.pvalue:.3f}") + (
            " (permutation)" if result.permutation else ""
        )
        for i, (category, n_a, n_b) in enumerate(zip(table.categories, table.group_a, table.group_b)):
            rows.append(
                {
                    "Variable": variable if i == 0 else "",
                    "Category": category,
                    f"{name_a} (n, %)": _share(n_a, total_a),
                    f"{name_b} (n, %)": _share(n_b, total_b),
                    "p-value": p_text if i == 0 else "",
                }
            )
    return pd.DataFrame(rows)


def category_summary(files: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Main-category counts (plus OTHER) of each dataset."""
    frames = []
    for name, df in files.items():
        for variable, categories in MAIN_CATEGORIES.items():
            if variable not in df.columns:
                continue
            shares = count_main_categories(normalize_tokens(df[variable].values), categories)
            frames.append(
                pd.DataFrame(
                    {
                        "File": name,
                        "Variable": variable,
                        "Category": [s.category for s in shares],
                        "Count": [s.count for s in shares],
                        "Percent": [s.percent for s in shares],
                        "Count (Percent%)": [f"{s.count} ({s.percent}%)" for s in shares],
                        "Total": sum(s.count for s in shares),
                    }
                )
            )
    return pd.concat(frames, ignore_index=True)


def region_focus_summary(regions: Sequence[object], focuses: Sequence[object]) -> Dict[str, List[CategoryShare]]:
    """Region Imaged occurrences ("Region_Summary") and the Imaging Focus occurrences within each region."""
    exploded = [(region, focus) for r, focus in zip(regions, focuses) for region in split_tokens(r)]
    region_shares = count_by_frequency([region for region, _ in exploded])
    summary = {"Region_Summary": region_shares}
    for share in region_shares:
        summary[share.category] = count_by_frequency(
            [token for region, focus in exploded if region == share.category for token in split_tokens_keep_none(focus)]
        )
    return summary


# ---------------------------------------------------------------- attribute agreement


def load_playbook_parts(path: Union[str, Path]) -> Dict[str, Dict[str, str]]:
    """LOINC → {PartTypeName: "name1, name2"}: names joined in row order, outer braces removed."""
    grouped: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            grouped[row["LoincNumber"]][row["PartTypeName"]].append(re.sub(r"^\{(.*)\}$", r"\1", row["PartName"]))
    return {loinc: {k: ", ".join(v) for k, v in parts.items()} for loinc, parts in grouped.items()}


@dataclass(frozen=True)
class ClassScores:
    f1_macro: float
    recall_macro: float
    f1_weighted: float
    recall_weighted: float


def class_scores(y_true: Sequence[Hashable], y_pred: Sequence[Hashable]) -> ClassScores:
    """Macro and weighted F1 and recall with zero_division=0 (scikit-learn defaults); NaN when empty."""
    labels = set(y_true) | set(y_pred)
    if not labels:
        return ClassScores(math.nan, math.nan, math.nan, math.nan)
    support, predicted = Counter(y_true), Counter(y_pred)
    true_positive = Counter(t for t, p in zip(y_true, y_pred) if t == p)
    f1s, recalls, weights = [], [], []
    for label in labels:
        tp = true_positive[label]
        precision = tp / predicted[label] if predicted[label] else 0.0
        recall = tp / support[label] if support[label] else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
        recalls.append(recall)
        weights.append(support[label])
    total = sum(weights)
    return ClassScores(
        f1_macro=sum(f1s) / len(labels),
        recall_macro=sum(recalls) / len(labels),
        f1_weighted=sum(f * w for f, w in zip(f1s, weights)) / total,
        recall_weighted=sum(r * w for r, w in zip(recalls, weights)) / total,
    )


@dataclass(frozen=True)
class AgreementResult:
    accuracy: Estimate
    scores: ClassScores


def _agreement(predicted: Sequence[Tuple], gold: Sequence[Tuple], drop_missing: bool) -> AgreementResult:
    matches = sum(1 for p, g in zip(predicted, gold) if p == g)
    pairs = list(zip(gold, predicted))
    if drop_missing:
        pairs = [(g, p) for g, p in pairs if None not in g and None not in p]
    labels_true = ["|".join("NaN" if v is None else str(v) for v in g) for g, _ in pairs]
    labels_pred = ["|".join("NaN" if v is None else str(v) for v in p) for _, p in pairs]
    return AgreementResult(wilson_interval(matches, len(predicted)), class_scores(labels_true, labels_pred))


def attribute_agreement(
    predicted_codes: Sequence[Optional[str]],
    gold_codes: Sequence[Optional[str]],
    parts: Mapping[str, Mapping[str, str]],
) -> Dict[str, AgreementResult]:
    """Agreement of five attributes and two attribute groups between predicted and gold codes.

    Both sides missing counts as agreement. For single attributes, F1/recall skip pairs with a missing
    side; a group agrees only when all of its attributes agree.
    """
    predicted = [parts.get(code, {}) if code else {} for code in predicted_codes]
    gold = [parts.get(code, {}) if code else {} for code in gold_codes]
    results = {
        key: _agreement([(p.get(key),) for p in predicted], [(g.get(key),) for g in gold], drop_missing=True)
        for key in COMPARED_ATTRIBUTES
    }
    for name, keys in ATTRIBUTE_GROUPS.items():
        results[name] = _agreement(
            [tuple(p.get(k) for k in keys) for p in predicted],
            [tuple(g.get(k) for k in keys) for g in gold],
            drop_missing=False,
        )
    return results


def _top1(cell: Any) -> Optional[str]:
    """First candidate code of a cell; an unreadable cell counts as no prediction."""
    try:
        records = read_cell_list(cell)
        return records[0].get("loinc_num") if records else None
    except Exception:  # noqa: BLE001
        return None


def agreement_table(df: pd.DataFrame, parts: Mapping[str, Mapping[str, str]], predicted: str = "top1") -> pd.DataFrame:
    """Attribute agreement of a result file; ``predicted`` is "top1" (retrieval Top-1) or "map_loinc"."""
    if predicted == "top1":
        codes = [_top1(cell) for cell in df["filtered_candidates"]]
    else:
        codes = list(df["map_loinc"])
    as_code = lambda v: None if is_blank(v) else str(v)  # noqa: E731
    results = attribute_agreement([as_code(c) for c in codes], [as_code(c) for c in df["LoincNumber"]], parts)
    return pd.DataFrame(
        [
            {
                "Attribute": name,
                "Accuracy": round(r.accuracy.point, 4),
                "95% CI": f"({r.accuracy.low:.4f}, {r.accuracy.high:.4f})",
                "F1 (macro)": round(r.scores.f1_macro, 4),
                "Recall (macro)": round(r.scores.recall_macro, 4),
                "F1 (weighted)": round(r.scores.f1_weighted, 4),
                "Recall (weighted)": round(r.scores.recall_weighted, 4),
            }
            for name, r in results.items()
        ]
    )
