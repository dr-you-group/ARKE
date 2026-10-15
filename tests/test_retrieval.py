import pytest
from fixtures import CHEST, FOOT_STANDING_AP_RT, STANDING_AP, TWO_VIEWS, playbook

from llm_parser import InvalidParserOutput, ParsedProcedure, clean_json_text
from playbook import Playbook, PlaybookRow, load_playbook
from retrieval import (
    AttributeWeights,
    F1Scorer,
    JaccardScorer,
    LcsScorer,
    RadLexHierarchy,
    SimpleOverlapScorer,
    WeightedMatchScorer,
    relation_key,
    retrieve_candidates,
)


def parsed():
    return ParsedProcedure.from_json_text(FOOT_STANDING_AP_RT)


# ---------------------------------------------------------------- Playbook and parser output


def test_each_playbook_csv_row_links_a_loinc_code_to_a_radlex_attribute(tmp_path):
    path = tmp_path / "playbook.csv"
    path.write_text(
        "﻿LoincNumber,LongCommonName,PartNumber,PartTypeName,PartName,PartSequenceOrder,RID,PreferredName,RPID,LongName\n"
        "24000-1,XR Foot,LP1,Rad.Modality.Modality Type,XR,A,RID10345,radiography,,\n"
        "24000-1,XR Foot,LP2,Rad.Anatomic Location.Imaging Focus,Foot,A,RID3,foot,,\n",
        encoding="utf-8",
    )

    pb = load_playbook(path)

    assert pb.loinc_rids() == {"24000-1": {"RID10345", "RID3"}}
    assert pb.edge_part_type("24000-1", "RID3") == "Rad.Anatomic Location.Imaging Focus"
    assert load_playbook(path, name_column="PreferredName").rid_name("RID10345") == "radiography"


def test_strips_json_code_fence_from_llm_output():
    assert clean_json_text('```json\n{"a": 1}\n```').strip() == '{"a": 1}'


def test_empty_parser_output_is_unreadable():
    with pytest.raises(InvalidParserOutput):
        ParsedProcedure.from_json_text("")


def test_parsed_values_map_to_same_named_rids_and_skip_nan():
    assert parsed().input_rids(playbook()) == {"RID10345", "RID2", "RID3", "RID49844", "RID5825", "RID10357", "RID7"}


def test_name_matching_ignores_case_and_outer_spaces():
    assert ParsedProcedure("x", {"Rad.Modality.Modality Type": "  xr "}).input_rids(playbook()) == {"RID10345"}


def test_list_values_resolve_each_item():
    assert ParsedProcedure("x", {"Rad.View.View Type": ["AP", "Views 2"]}).input_rids(playbook()) == {
        "RID10357",
        "RID10",
    }


def test_non_text_attribute_value_makes_row_unreadable():
    with pytest.raises(InvalidParserOutput):
        ParsedProcedure("x", {"Rad.View.View Type": [1]}).input_rids(playbook())


def test_lcs_rids_are_grouped_by_attribute_type():
    grouped = parsed().relation_rids(playbook())

    assert grouped["Modality.Modality Type"] == {"RID10345"}
    assert "Timing" not in grouped


# ---------------------------------------------------------------- weights


@pytest.mark.parametrize(
    "part_type",
    [
        "Rad.Modality.Modality Type",
        "Rad.Anatomic Location.Region Imaged",
        "Rad.Anatomic Location.Laterality",
        "Rad.View.View Type",
        "Rad.Pharmaceutical.Substance Given",
    ],
)
def test_clinically_important_attributes_get_weight_1_5(part_type):
    assert AttributeWeights().of_part_type(part_type) == 1.5


@pytest.mark.parametrize(
    "part_type, key",
    [("Rad.Timing", "Rad.Timing"), ("Rad.Anatomic Location.Laterality.Presence", "Laterality.Presence")],
)
def test_timing_and_laterality_presence_get_default_weight_because_of_the_relation_key(part_type, key):
    assert relation_key(part_type) == key
    assert AttributeWeights().of_part_type(part_type) == 1.0


# ---------------------------------------------------------------- scorers


def test_weighted_scores_for_paper_table2_example_are_7_5_and_4_0():
    candidates = WeightedMatchScorer(playbook()).rank(parsed())

    scores = {c.loinc_num: c.score for c in candidates}
    assert (scores[STANDING_AP], scores[TWO_VIEWS]) == (7.5, 4.0)
    assert candidates[0].details["score_breakdown"]["missing"] == {"Rad.Timing": 1, "View.Aggregation": 1}


def test_simple_overlap_subtracts_missing_and_extra_from_matched():
    scores = {c.loinc_num: c.score for c in SimpleOverlapScorer(playbook()).rank(parsed())}

    assert (scores[STANDING_AP], scores[TWO_VIEWS], scores[CHEST]) == (5, 2, -7)


def test_jaccard_drops_candidates_without_shared_attributes():
    candidates = JaccardScorer(playbook()).rank_rids(frozenset({"RID3"}))

    assert [c.loinc_num for c in candidates] == [TWO_VIEWS, STANDING_AP]
    assert candidates[0].score == round(1 / 6, 5)


def test_f1_is_harmonic_mean_of_input_precision_and_candidate_recall():
    scores = {c.loinc_num: c.score for c in F1Scorer(playbook()).rank(parsed())}

    assert scores[STANDING_AP] == round(2 * 1 * (7 / 9) / (1 + 7 / 9), 5)


def test_ties_keep_playbook_row_order_and_only_top_n_is_returned():
    rows = [PlaybookRow(code, code, "RID1", "Rad.Modality.Modality Type", "XR") for code in ("B", "A", "C")]

    candidates = SimpleOverlapScorer(Playbook(rows)).rank_rids(frozenset({"RID1"}), top_n=2)

    assert [c.loinc_num for c in candidates] == ["B", "A"]


def test_unreadable_parser_output_yields_an_empty_candidate_list():
    lists = retrieve_candidates([FOOT_STANDING_AP_RT, "not json", None], WeightedMatchScorer(playbook()))

    assert lists[0][0].loinc_num == STANDING_AP
    assert lists[1] == [] and lists[2] == []


# ---------------------------------------------------------------- LCS

# root ─ anatomy ─ limb ─ foot / hand;  root ─ modality ─ xr
EDGES = [
    ("root", "anatomy"),
    ("anatomy", "limb"),
    ("limb", "foot"),
    ("limb", "hand"),
    ("root", "modality"),
    ("modality", "xr"),
]


def test_lowest_common_subsumer_and_wu_palmer_similarity():
    h = RadLexHierarchy([], EDGES)

    assert (h.depth("root"), h.depth("foot")) == (0, 3)
    assert h.lowest_common_subsumer("foot", "hand") == "limb"
    assert h.similarity("foot", "hand") == pytest.approx(4 / 6)
    assert h.similarity("foot", "xr") == 0.0


def test_lcs_score_compares_same_attribute_types_by_hierarchy_similarity():
    rows = [
        PlaybookRow("FOOT", "XR Foot", "xr", "Rad.Modality.Modality Type", "XR"),
        PlaybookRow("FOOT", "XR Foot", "foot", "Rad.Anatomic Location.Imaging Focus", "Foot"),
        PlaybookRow("HAND", "XR Hand", "xr", "Rad.Modality.Modality Type", "XR"),
        PlaybookRow("HAND", "XR Hand", "hand", "Rad.Anatomic Location.Imaging Focus", "Hand"),
    ]
    query = ParsedProcedure("x", {"Rad.Modality.Modality Type": "XR", "Rad.Anatomic Location.Imaging Focus": "Hand"})

    ranked = LcsScorer(Playbook(rows), RadLexHierarchy([], EDGES)).rank(query)

    assert [c.loinc_num for c in ranked] == ["HAND", "FOOT"]
    assert ranked[1].score == pytest.approx(1 + 4 / 6, abs=1e-5)
