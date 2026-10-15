import math

import numpy as np
import pytest

from evaluation import (
    RankedPrediction,
    RetrievalReport,
    bootstrap_mean_interval,
    candidate_overlap,
    mcnemar,
    wilson_interval,
)


def test_mrr_ndcg_and_recall_at_k_use_the_gold_rank():
    p = RankedPrediction("B", ("A", "B", "C"))

    assert (p.hit_at(1), p.hit_at(3)) == (False, True)
    assert p.reciprocal_rank() == 0.5
    assert p.ndcg() == pytest.approx(1 / math.log2(3))
    assert RankedPrediction("Z", ("A",)).reciprocal_rank() == 0.0


def test_final_selection_is_correct_only_when_equal_to_gold():
    assert RankedPrediction("A", (), "A").selection_correct()
    assert not RankedPrediction("A", (), None).selection_correct()


def test_rows_without_gold_stay_in_denominator_as_wrong():
    report = RetrievalReport.of([RankedPrediction("A", ("A",), "A"), RankedPrediction("nan", ("A",), "A")], n_boot=100)

    assert report.final_recall_at_1.point == 0.5 and report.recall_at[10].point == 0.5


def test_candidate_overlap_averages_intersections_and_consensus():
    summary = candidate_overlap({"a": [("1", "2", "3")], "b": [("1", "2", "4")], "c": [("1", "5", "6")]})

    assert summary.all_intersection == 1
    assert summary.avg_pairwise_intersection == pytest.approx(4 / 3)
    assert summary.consensus == {"consensus_>=2": 2.0, "consensus_==3": 1.0}


@pytest.mark.parametrize("successes, total", [(166, 237), (0, 10), (10, 10)])
def test_wilson_interval_matches_statsmodels(successes, total):
    sm = pytest.importorskip("statsmodels.stats.proportion")
    low, high = sm.proportion_confint(successes, total, alpha=0.05, method="wilson")

    estimate = wilson_interval(successes, total)

    assert (estimate.low, estimate.high) == pytest.approx((low, high), abs=1e-12)


def test_bootstrap_interval_is_reproducible_with_seed_42():
    values = [1.0, 0.5, 0.0, 1 / 3, 1.0, 0.25]
    rng = np.random.default_rng(42)
    means = [rng.choice(np.asarray(values), size=6, replace=True).mean() for _ in range(500)]

    estimate = bootstrap_mean_interval(values, n_boot=500, seed=42)

    assert (estimate.low, estimate.high) == (np.percentile(means, 2.5), np.percentile(means, 97.5))


@pytest.mark.parametrize("b, c", [(13, 3), (82, 7), (1, 1)])
def test_mcnemar_matches_statsmodels_corrected_chi_square(b, c):
    sm = pytest.importorskip("statsmodels.stats.contingency_tables")
    expected = sm.mcnemar([[0, b], [c, 0]], exact=False, correction=True)

    result = mcnemar([True] * b + [False] * c, [False] * b + [True] * c)

    assert (result.b, result.c) == (b, c)
    assert result.pvalue == pytest.approx(expected.pvalue, rel=1e-9)
