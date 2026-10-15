"""Regression tests against the published experiment results (run when ARKE_DATA_DIR is set)."""

import pytest

from analysis import characteristics_table
from evaluation import RetrievalReport, compare_methods, read_predictions
from playbook import load_playbook
from retrieval import F1Scorer, JaccardScorer, SimpleOverlapScorer, WeightedMatchScorer, retrieve_candidates
from utils import read_cell_list

pd = pytest.importorskip("pandas")
SCORERS = {"jaccard": JaccardScorer, "match": SimpleOverlapScorer, "weighted": WeightedMatchScorer, "f1": F1Scorer}


@pytest.fixture(scope="module")
def playbook(data_dir):
    return load_playbook(data_dir / "LoincRsnaRadiologyPlaybook_2025.csv")


@pytest.mark.parametrize("site", ["SEV", "SNUH"])
@pytest.mark.parametrize("method", sorted(SCORERS))
def test_candidate_codes_and_scores_match_saved_experiment_results(data_dir, playbook, site, method):
    df = pd.read_excel(data_dir / "res_1029" / f"{site}_valid_json_goldlabel_{method}candidate.xlsx")

    lists = retrieve_candidates(list(df["input_text_json"].values), SCORERS[method](playbook))

    for candidates, cell in zip(lists, df["candidates"]):
        stored = read_cell_list(cell)
        assert [c.loinc_num for c in candidates] == [c["loinc_num"] for c in stored]
        assert [c.score for c in candidates] == [c["score"] for c in stored]


TABLE3_INTERNAL = {
    "weighted": ("0.70 (0.63-0.75)", "0.49 (0.43-0.55)", "0.78 (0.73-0.83)", "0.90 (0.85-0.93)"),
    "match": ("0.65 (0.59-0.71)", "0.49 (0.43-0.56)", "0.76 (0.71-0.81)", "0.87 (0.83-0.91)"),
    "jaccard": ("0.68 (0.61-0.73)", "0.47 (0.41-0.54)", "0.77 (0.71-0.82)", "0.88 (0.83-0.91)"),
    "loinc": ("0.48 (0.42-0.54)", "0.24 (0.19-0.30)", "0.51 (0.45-0.57)", "0.62 (0.55-0.68)"),
}


@pytest.mark.parametrize("method", sorted(TABLE3_INTERNAL))
def test_internal_test_recall_and_ci_match_paper(data_dir, method):
    report = RetrievalReport.of(read_predictions(str(data_dir / "res_1029" / f"SEV_{method}.xlsx")), n_boot=200)

    final, r1, r5, r10 = TABLE3_INTERNAL[method]
    assert report.n == 237 and report.final_recall_at_1.format() == final
    assert (report.recall_at[1].format(), report.recall_at[5].format(), report.recall_at[10].format()) == (r1, r5, r10)


def test_internal_test_mcnemar_p_values_match_paper(data_dir):
    load = lambda m: read_predictions(str(data_dir / "res_1029" / f"SEV_{m}.xlsx"))  # noqa: E731

    results = compare_methods(load("weighted"), {m: load(m) for m in ("match", "jaccard", "f1", "loinc")})

    assert [round(results[m].pvalue, 3) for m in ("match", "jaccard", "f1")] == [0.024, 0.302, 0.267]
    assert results["loinc"].pvalue < 0.001


def test_sev_snuh_characteristics_table_matches_saved_table(data_dir):
    folder = data_dir / "baselinecharacteristic_1031"

    table = characteristics_table(
        "SEV",
        pd.read_excel(folder / "SEV_json3036_parsed_2.xlsx"),
        "SNUH",
        pd.read_excel(folder / "SNUH_json290_parsed_2.xlsx"),
    )

    saved = pd.read_excel(folder / "Baseline_Table_final_2.xlsx").fillna("").astype(str)
    assert table.fillna("").astype(str).equals(saved)
