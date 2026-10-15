"""ARKE command line.

Mapping:     python main.py run | parse | retrieve | select --input X.xlsx --output Y.xlsx
Evaluation:  python main.py metrics | mcnemar | overlap --file NAME=PATH ...
Analysis:    python main.py extract | compare | summarize | region-focus | agreement ...
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from typing import List, Optional, Tuple

import pandas as pd

from analysis import (
    ATTRIBUTE_KEYS,
    COMBINED_ATTRIBUTES,
    FOCUS,
    REGION,
    agreement_table,
    category_summary,
    characteristics_table,
    extract_attributes,
    load_playbook_parts,
    region_focus_summary,
)
from evaluation import candidate_overlap, compare_methods, metrics_table, read_predictions
from llm_parser import parse_procedures
from llm_selector import select_candidates
from playbook import load_playbook
from retrieval import (
    METHODS,
    Candidate,
    DirectRetriever,
    candidates_cell,
    candidates_from_records,
    filtered_candidates_cell,
    make_scorer,
    retrieve_candidates,
)
from utils import OpenAIChat, Settings, get_settings, is_blank, read_cell_list, require_api_key


def named(value: str) -> Tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("use NAME=PATH, e.g. weighted=result.xlsx")
    name, path = value.split("=", 1)
    return name, path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ARKE: map local radiology procedure names to Playbook codes")
    sub = parser.add_subparsers(dest="command", required=True)

    def io(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--input", required=True, help="input Excel file")
        p.add_argument("--output", required=True, help="output Excel file")
        return p

    # mapping
    run = io(sub.add_parser("run", help="parse + retrieve + select"))
    run.add_argument("--column", default="input_text", help="procedure name column")
    run.add_argument("--method", choices=METHODS, default="weighted")
    io(sub.add_parser("parse", help="LLM Parser → input_text_json")).add_argument("--column", default="input_text")
    retrieve = io(sub.add_parser("retrieve", help="Top-10 candidates → candidates, filtered_candidates"))
    retrieve.add_argument("--method", choices=METHODS, default="weighted")
    retrieve.add_argument("--column", default="input_text", help="procedure name column (direct only)")
    retrieve.add_argument("--json-column", default="input_text_json")
    io(sub.add_parser("select", help="LLM Selector → res, map_loinc, map_longname")).add_argument(
        "--column", default="input_text"
    )

    # evaluation
    metrics = sub.add_parser("metrics", help="Recall@1/3/5/10, MRR, NDCG@10, final Recall@1 with 95% CI")
    metrics.add_argument("--file", type=named, action="append", required=True)
    metrics.add_argument("--digits", type=int, default=2)
    metrics.add_argument("--output")
    mcnemar = sub.add_parser("mcnemar", help="McNemar test of final selection against a reference method")
    mcnemar.add_argument("--reference", type=named, required=True)
    mcnemar.add_argument("--file", type=named, action="append", required=True)
    overlap = sub.add_parser("overlap", help="agreement among Top-10 candidate sets")
    overlap.add_argument("--file", type=named, action="append", required=True)
    overlap.add_argument("--column", default="filtered_candidates")
    for p in (metrics, mcnemar, overlap):
        p.add_argument("--exclude-missing-gold", action="store_true", help="drop rows without LoincNumber")

    # analysis
    extract = io(sub.add_parser("extract", help="Parser JSON → attribute columns"))
    extract.add_argument("--json-column", default="input_text_json")
    compare = sub.add_parser("compare", help="characteristics of two cohorts with p-values")
    compare.add_argument("--a", type=named, required=True)
    compare.add_argument("--b", type=named, required=True)
    compare.add_argument("--output", required=True)
    compare.add_argument("--n-iter", type=int, default=20000)
    summarize = sub.add_parser("summarize", help="main-category counts per dataset")
    summarize.add_argument("--file", type=named, action="append", required=True)
    summarize.add_argument("--output", required=True)
    io(sub.add_parser("region-focus", help="Imaging Focus distribution within each Region Imaged"))
    agreement = sub.add_parser("agreement", help="attribute-wise agreement of predicted and gold codes")
    agreement.add_argument("--input", required=True)
    agreement.add_argument("--playbook", required=True, help="LoincRsnaRadiologyPlaybook CSV")
    agreement.add_argument("--predicted", choices=("top1", "map_loinc"), default="top1")
    agreement.add_argument("--output")
    return parser


# ---------------------------------------------------------------- mapping


def chat(settings: Settings) -> OpenAIChat:
    require_api_key()
    return OpenAIChat(model=settings.chat_model)


def retrieve(df: pd.DataFrame, method: str, settings: Settings, column: str, json_column: str) -> List[List[Candidate]]:
    if method == "direct":
        require_api_key()
        retriever = DirectRetriever.build(settings.imaging_codes_csv, settings.embedding_model)
        return [retriever.retrieve(str(name)) for name in df[column].values]
    scorer = make_scorer(method, load_playbook(settings.playbook_csv), settings.radlex_owl)
    return retrieve_candidates(list(df[json_column].values), scorer)


def write_candidates(df: pd.DataFrame, lists: List[List[Candidate]]) -> None:
    df["candidates"] = [candidates_cell(c) for c in lists]
    df["filtered_candidates"] = [filtered_candidates_cell(c) for c in lists]


def write_selections(df: pd.DataFrame, indices: List[int], answers: list) -> None:
    for column in ("res", "map_loinc", "map_longname"):
        df[column] = pd.Series([None] * len(df), dtype=object)
    for idx, (raw, selection) in zip(indices, answers):
        df.at[idx, "res"] = raw
        df.at[idx, "map_loinc"] = selection.loinc_num if selection else ""
        df.at[idx, "map_longname"] = selection.long_common_name if selection else ""


def run_mapping(args: argparse.Namespace, settings: Settings) -> None:
    df = pd.read_excel(args.input)
    needs_parsing = args.command == "parse" or (args.command == "run" and args.method != "direct")
    if needs_parsing:
        names = df[args.column].dropna()
        parsed = asyncio.run(parse_procedures([str(n) for n in names.values], chat(settings), settings.batch_size))
        df["input_text_json"] = pd.Series([None] * len(df), dtype=object)
        for idx, raw in zip(names.index, parsed):
            df.at[idx, "input_text_json"] = raw
    if args.command in ("retrieve", "run"):
        json_column = getattr(args, "json_column", "input_text_json")
        write_candidates(df, retrieve(df, args.method, settings, args.column, json_column))
    if args.command in ("select", "run"):
        rows = [
            (idx, str(name), candidates_from_records(read_cell_list(cell)))
            for idx, name, cell in zip(df.index, df[args.column], df["filtered_candidates"])
            if not is_blank(name) and not is_blank(cell)
        ]
        answers = asyncio.run(
            select_candidates([(name, cands) for _, name, cands in rows], chat(settings), settings.batch_size)
        )
        write_selections(df, [idx for idx, _, _ in rows], answers)
    df.to_excel(args.output, index=False)


# ---------------------------------------------------------------- evaluation


def run_evaluation(args: argparse.Namespace) -> None:
    load = lambda path, column="candidates": read_predictions(path, column, args.exclude_missing_gold)  # noqa: E731
    if args.command == "metrics":
        table = metrics_table({name: load(path) for name, path in args.file}, args.digits)
        print(table.to_string(index=False))
        if args.output:
            table.to_excel(args.output, index=False)
    elif args.command == "mcnemar":
        ref_name, ref_path = args.reference
        results = compare_methods(load(ref_path), {name: load(path) for name, path in args.file})
        for name, r in results.items():
            print(f"{name} vs {ref_name} → b={r.b}, c={r.c}, p-value={r.pvalue:.5f}")
    else:
        summary = candidate_overlap({name: [p.candidates for p in load(path, args.column)] for name, path in args.file})
        print(f"all_intersection: {summary.all_intersection:.4f}")
        print(f"avg_pairwise_intersection: {summary.avg_pairwise_intersection:.4f}")
        for key, value in summary.consensus.items():
            print(f"{key}: {value:.4f}")


# ---------------------------------------------------------------- analysis


def run_analysis(args: argparse.Namespace) -> None:
    if args.command == "extract":
        df = pd.read_excel(args.input)
        rows = [extract_attributes(text) for text in df[args.json_column].values]
        for column in list(ATTRIBUTE_KEYS) + list(COMBINED_ATTRIBUTES):
            df[column] = [row[column] for row in rows]
        df.to_excel(args.output, index=False)
    elif args.command == "compare":
        (name_a, path_a), (name_b, path_b) = args.a, args.b
        table = characteristics_table(name_a, pd.read_excel(path_a), name_b, pd.read_excel(path_b), args.n_iter)
        table.to_excel(args.output, index=False)
    elif args.command == "summarize":
        category_summary({name: pd.read_excel(path) for name, path in args.file}).to_excel(args.output, index=False)
    elif args.command == "region-focus":
        df = pd.read_excel(args.input)
        summary = region_focus_summary(list(df[REGION].values), list(df[FOCUS].values))
        with pd.ExcelWriter(args.output) as writer:
            for sheet, shares in summary.items():
                frame = pd.DataFrame(
                    {"count": [s.count for s in shares], "percent": [s.percent for s in shares]},
                    index=pd.Index([s.category for s in shares], name=REGION if sheet == "Region_Summary" else FOCUS),
                )
                name = sheet if sheet == "Region_Summary" else f"Focus_{sheet}"
                frame.to_excel(writer, sheet_name=re.sub(r"[:\\/?*\[\]]", "_", name)[:31])
    else:
        table = agreement_table(pd.read_excel(args.input), load_playbook_parts(args.playbook), args.predicted)
        print(table.to_string(index=False))
        if args.output:
            table.to_excel(args.output, index=False)


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.command in ("run", "parse", "retrieve", "select"):
        run_mapping(args, get_settings())
    elif args.command in ("metrics", "mcnemar", "overlap"):
        run_evaluation(args)
    else:
        run_analysis(args)


if __name__ == "__main__":
    main()
