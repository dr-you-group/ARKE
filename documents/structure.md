# Structure

This document describes the files of the repository and what each module contains.

## 1. Layout

```
ARKE/
├── main.py            Command line: mapping, evaluation, analysis
├── utils.py           Settings (.env), OpenAI chat call, batching, Excel cell helpers
├── prompts.py         System, Parser, and Selector prompts
├── playbook.py        Playbook knowledge graph (LOINC ↔ RadLex) and RID lookups
├── llm_parser.py      LLM Parser: procedure name → Playbook attributes
├── retrieval.py       Scoring retrieval (weighted, jaccard, match, f1, lcs) and direct baseline
├── llm_selector.py    LLM Selector: one code from the Top-10 candidates
├── evaluation.py      Recall@k, MRR, NDCG@10, 95% CI, McNemar test, candidate overlap
├── analysis.py        Cohort characteristics, category summaries, attribute agreement
├── requirements.txt   Python packages
├── ruff.toml          Lint settings
├── .env.example       Example environment variables (the real .env is git-ignored)
├── documents/         These documents
├── images/            README figure
└── tests/             Unit and regression tests
```

The mapping pipeline follows the order of the paper:

```
main.py → llm_parser.py → retrieval.py → llm_selector.py
              │              │
              └── playbook.py┘          (utils.py and prompts.py are shared)
```

## 2. Modules

### `main.py`

| Command | Function | Description |
|---|---|---|
| `run`, `parse`, `retrieve`, `select` | `run_mapping` | Reads the input Excel, runs the requested stages, writes the result columns |
| `metrics`, `mcnemar`, `overlap` | `run_evaluation` | Reads result files and prints or saves the evaluation |
| `extract`, `compare`, `summarize`, `region-focus`, `agreement` | `run_analysis` | Reads attribute or result files and writes the analysis tables |

### `utils.py`

| Name | Description |
|---|---|
| `get_settings`, `Settings` | Reads environment variables and `.env` |
| `require_api_key` | Stops with an error when `OPENAI_API_KEY` is missing |
| `OpenAIChat` | One GPT-4o call per prompt with the system prompt at temperature 0 |
| `run_in_batches` | Runs calls concurrently within each batch (15 by default), batches in order |
| `read_cell_list`, `is_blank` | Read `candidates` cells and detect empty cells |

### `prompts.py`

`SYSTEM_PROMPT`, `PARSER_PROMPT`, and `SELECTOR_PROMPT`, kept verbatim because they are part of the published method.

### `playbook.py`

| Name | Description |
|---|---|
| `PlaybookRow` | One CSV row: a LOINC code linked to one RadLex attribute |
| `Playbook` | Knowledge graph that keeps CSV row order; `loinc_rids()`, `edge_part_type()`, `first_rid_named()`, `rid_for_value()` |
| `load_playbook` | Loads `LoincRsnaRadiologyPlaybook_<version>.csv` |

### `llm_parser.py`

| Name | Description |
|---|---|
| `parse_procedures` | Procedure names → raw Parser answers (`input_text_json`) |
| `ParsedProcedure` | Reads the Parser JSON; `input_rids()` (lookup across all attribute types), `relation_rids()` (per attribute type, for LCS) |
| `InvalidParserOutput` | Raised when the Parser answer cannot be read |

### `retrieval.py`

| Name | Description |
|---|---|
| `Candidate` | A proposed Playbook code with its score and details |
| `AttributeWeights`, `relation_key` | Weights for weighted matching |
| `WeightedMatchScorer`, `JaccardScorer`, `SimpleOverlapScorer`, `F1Scorer` | Ontology-grounded scorers |
| `RadLexHierarchy`, `LcsScorer`, `load_radlex_hierarchy` | Lowest Common Subsumer method (needs owlready2) |
| `DirectRetriever` | Direct embedding baseline (needs langchain and faiss) |
| `make_scorer`, `retrieve_candidates` | Pick a scorer by name; rank Parser outputs, giving unreadable rows an empty list |
| `candidates_cell`, `filtered_candidates_cell` | Write candidates into Excel cells |

### `llm_selector.py`

| Name | Description |
|---|---|
| `select_candidates` | (name, candidates) pairs → (raw answer, `Selection`) pairs |
| `Selection` | Reads the Selector answer; `is_within(candidates)` |
| `format_candidates` | Candidate text given to the Selector (code and name only) |

### `evaluation.py`

| Name | Description |
|---|---|
| `RankedPrediction` | Gold code, Top-10 codes, and selected code of one row |
| `RetrievalReport`, `metrics_table` | Final Recall@1, Recall@1/3/5/10, MRR, NDCG@10 with 95% CI |
| `wilson_interval`, `bootstrap_mean_interval` | Confidence intervals |
| `mcnemar`, `compare_methods` | McNemar test against a reference method |
| `candidate_overlap` | Agreement among the Top-10 sets of several methods |
| `read_predictions` | Reads a result Excel file |

### `analysis.py`

| Name | Description |
|---|---|
| `extract_attributes` | Nine analysed attributes and three combined attributes from Parser JSON |
| `normalize_tokens`, `split_tokens` | Multi-response tokenisation |
| `ContingencyTable`, `compare_groups`, `characteristics_table` | Two-cohort comparison with chi-square or permutation p-values |
| `category_summary`, `region_focus_summary` | Category and region/focus summaries |
| `load_playbook_parts`, `attribute_agreement`, `agreement_table` | Attribute agreement between predicted and gold codes |

## 3. Tests

| File | Covers |
|---|---|
| `tests/test_retrieval.py` | Playbook loading, Parser output reading, weights, scorers, LCS |
| `tests/test_llm.py` | Parser and Selector calls (OpenAI stubbed), selection reading, batching |
| `tests/test_evaluation.py` | Metrics, confidence intervals, McNemar test, candidate overlap |
| `tests/test_analysis.py` | Attribute extraction, tokens, contingency tables, attribute agreement |
| `tests/test_regression.py` | Saved experiment results, paper Table 3, cohort table (needs `ARKE_DATA_DIR`) |
| `tests/fixtures.py` | Small Playbook with the paper's Table 2 example |

Test names are written as business-rule sentences, for example `test_timing_and_laterality_presence_get_default_weight_because_of_the_relation_key`.
