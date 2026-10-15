import pytest

from analysis import (
    OTHER,
    ContingencyTable,
    class_scores,
    combine,
    compare_groups,
    count_main_categories,
    extract_attributes,
    extract_value,
    load_playbook_parts,
    normalize_tokens,
    split_tokens,
    split_tokens_keep_none,
)

JSON = (
    '{"Parts": {"Rad.Modality.Modality Type": "MR", "Rad.Modality.Modality Subtype": "Angio", '
    '"Rad.View.View Type": ["PA", "lateral"], "Rad.Timing": "NaN"}}'
)


def test_attribute_values_are_extracted_and_combined():
    values = extract_attributes(JSON)

    assert extract_value(JSON, "Rad.View.View Type") == "PA, lateral"
    assert extract_value(JSON, "Rad.Timing") is None
    assert values["Modality"] == "MR_Angio" and values["TimingPharm"] == ""
    assert combine("CT", None) == "CT"


def test_multi_response_tokens_are_lowercased_split_and_cleaned():
    assert normalize_tokens(['"PA", "Lateral"', "NaN", None, float("nan"), "CT"]) == ["pa", "lateral", "ct"]
    assert split_tokens('Chest, "Abdomen", nan') == ["Chest", "Abdomen"]
    assert split_tokens_keep_none(float("nan")) == ["(None)"]


def test_sparse_categories_merge_into_other_smallest_first():
    collapsed = ContingencyTable(("a", "b", "c", "d"), (50, 40, 1, 2), (60, 35, 0, 1)).collapse_sparse()

    assert collapsed.categories == ("a", "b", OTHER)
    assert collapsed.group_a == (50, 40, 3) and collapsed.group_b == (60, 35, 1)


def test_uses_chi_square_p_value_when_expected_counts_suffice():
    result = compare_groups(
        ["ct"] * 40 + ["mr"] * 60 + ["x"] * 3 + ["y"] * 3, ["ct"] * 60 + ["mr"] * 40 + ["x"] * 3 + ["y"] * 3
    )

    assert result.tested.categories == ("ct", "mr", OTHER)
    assert not result.permutation and result.pvalue < 0.05


def test_uses_seeded_permutation_p_value_when_still_sparse():
    a, b = ["ct"] * 300 + ["mr"] * 30 + ["us"], ["ct"] * 20 + ["mr"] * 20 + ["us"]

    first, second = compare_groups(a, b, n_iter=500), compare_groups(a, b, n_iter=500)

    assert first.permutation and first.pvalue == second.pvalue


def test_cannot_test_when_other_row_is_empty():
    with pytest.raises(ValueError):
        compare_groups(["true"] * 50, ["true"] * 40)


def test_main_category_summary_groups_rest_as_other_with_share_of_all_tokens():
    shares = count_main_categories(["ct", "ct", "mr", "us"], ["ct", "mr"])

    assert [(s.category, s.count, s.percent) for s in shares] == [("ct", 2, 50.0), ("mr", 1, 25.0), (OTHER, 1, 25.0)]


def test_playbook_parts_join_in_row_order_and_strip_braces(tmp_path):
    path = tmp_path / "playbook.csv"
    path.write_text(
        "LoincNumber,PartTypeName,PartName\n"
        "1,Rad.Anatomic Location.Imaging Focus,Radius\n1,Rad.Anatomic Location.Imaging Focus,Ulna\n"
        "2,Rad.Modality.Modality Type,{Imaging modality}\n",
        encoding="utf-8",
    )

    assert load_playbook_parts(path) == {
        "1": {"Rad.Anatomic Location.Imaging Focus": "Radius, Ulna"},
        "2": {"Rad.Modality.Modality Type": "Imaging modality"},
    }


def test_macro_and_weighted_f1_and_recall_match_scikit_learn():
    metrics = pytest.importorskip("sklearn.metrics")
    y_true, y_pred = ["a", "a", "b", "c", "c", "c"], ["a", "b", "b", "c", "a", "d"]

    scores = class_scores(y_true, y_pred)

    assert scores.f1_macro == pytest.approx(metrics.f1_score(y_true, y_pred, average="macro", zero_division=0))
    assert scores.recall_weighted == pytest.approx(
        metrics.recall_score(y_true, y_pred, average="weighted", zero_division=0)
    )
