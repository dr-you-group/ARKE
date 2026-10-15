# Data Objects (DTOs)

This document describes the shape of the data passed between modules and files:
- Section 1: LLM input/output formats
- Section 2: Data classes
- Section 3: Main functions
- Section 4: Excel file formats (command-line input/output)

All data classes are immutable (`@dataclass(frozen=True)`). To change one, create a new object.

---

## 1. LLM input/output formats

### 1-1. Parser output — Playbook attribute JSON (`input_text_json`)

The raw text returned for each name by `llm_parser.parse_procedures()`. It may be wrapped in a ```` ```json ```` code fence.

```json
{
  "Name": "Foot Standing AP Right",
  "Parts": {
    "Rad.Modality.Modality Type": "XR",
    "Rad.Modality.Modality Subtype": "NaN",
    "Rad.Anatomic Location.Region Imaged": "Lower extremity",
    "Rad.Anatomic Location.Imaging Focus": "Foot",
    "Rad.Anatomic Location.Laterality.Presence": "True",
    "Rad.Anatomic Location.Laterality": "Right",
    "Rad.View.Aggregation": "NaN",
    "Rad.View.View Type": "AP",
    "Rad.Timing": "NaN",
    "Rad.Maneuver.Maneuver Type": "Standing",
    "Rad.Pharmaceutical.Substance Given": "NaN",
    "Rad.Pharmaceutical.Route": "NaN",
    "Rad.Reason for Exam": "NaN",
    "Rad.Guidance for.Presence": "NaN",
    "Rad.Guidance for.Approach": "NaN",
    "Rad.Guidance for.Action": "NaN",
    "Rad.Guidance for.Object": "NaN",
    "Rad.Subject": "NaN"
  }
}
```

| Field | Type | Description |
|---|---|---|
| `Name` | string | Standardized procedure name in English, special characters removed |
| `Parts` | object | The 18 Playbook attributes; keys equal `PartTypeName` in the Playbook CSV |
| `Parts.*` values | string or array of strings | `"NaN"` when missing; an array for multiple values (e.g. `["PA", "lateral"]`) |

This format is read by `llm_parser.ParsedProcedure.from_json_text()`.

### 1-2. Selector output (`res`)

The raw text returned for each name by `llm_selector.select_candidates()`.

```json
{
  "reasoning": "<step-by-step reasoning>",
  "selected_loinc": "24000-1",
  "long_common_name": "XR Foot - right Views AP W standing"
}
```

This format is read by `llm_selector.Selection.from_json_text()`, and in the same way by `evaluation.read_predictions()`. An unreadable answer is treated as no selection (`None`).

### 1-3. Candidate text given to the Selector

```
LOINC_NUM: 24000-1
LONG_COMMON_NAME: XR Foot - right Views AP W standing
LOINC_NUM: 24000-2
LONG_COMMON_NAME: XR Foot - right 2 Views
```

Only codes and names are included; scores and matching details are not (`llm_selector.format_candidates`).

---

## 2. Data classes

### 2-1. playbook.py, llm_parser.py, retrieval.py, llm_selector.py

| Class | Fields | Description |
|---|---|---|
| `PlaybookRow` | `loinc_num: str`, `long_common_name: str`, `rid: str`, `part_type: str`, `part_name: str` | One Playbook CSV row = one knowledge-graph edge (LOINC ↔ RadLex attribute) |
| `Playbook` | (query methods only) `loinc_rids()`, `loinc_relation_rids()`, `long_common_name()`, `rid_name()`, `edge_part_type()`, `first_rid_named()`, `rid_for_value()` | Knowledge graph that preserves row order |
| `ParsedProcedure` | `name: str`, `parts: Dict[str, Any]` | Parser result; `input_rids()` looks up names globally, `relation_rids()` per attribute type |
| `AttributeWeights` | `high_weight_relations: FrozenSet[str]`, `high: float = 1.5`, `default: float = 1.0` | w(a) of the weighted score |
| `Candidate` | `loinc_num: str`, `long_common_name: str`, `score: float` (5 decimals), `details: Dict[str, Any]` | One candidate; `details` depends on the scorer (table below) |
| `Selection` | `loinc_num: str`, `long_common_name: str`, `reasoning: str` | The one code chosen by the Selector; `is_within(candidates)` |
| `RadLexHierarchy` | constructor `(nodes, edges: (parent, child))` | is-a hierarchy; `depth()`, `lowest_common_subsumer()`, `similarity()` |

Keys of `Candidate.details`:

| Scorer | `details` keys |
|---|---|
| `JaccardScorer`, `F1Scorer` | `matched_rids` |
| `SimpleOverlapScorer` | `matched_rids`, `missing_rids`, `extra_rids` |
| `WeightedMatchScorer` | `matched_rids`, `missing_rids`, `extra_rids`, `score_breakdown` = `{"matched": {relation_key: count}, "missing": {...}, "extra": {"default": count}}` |
| `LcsScorer` | `score_breakdown` = `{attribute: {"score", "input_rids", "candidate_rids", "best_pairs"}}` |
| `DirectRetriever` | (none) |

### 2-2. evaluation.py

| Class | Fields | Description |
|---|---|---|
| `RankedPrediction` | `gold: str`, `candidates: Tuple[str, ...]`, `selected: Optional[str]` | One evaluated row |
| `Estimate` | `point: float`, `low: float`, `high: float` | Point estimate and 95% CI; `format(digits)` → `"0.70 (0.63-0.75)"` |
| `RetrievalReport` | `n: int`, `final_recall_at_1: Estimate`, `recall_at: Dict[int, Estimate]` (1, 3, 5, 10), `mrr: Estimate`, `ndcg_at_10: Estimate` | Metrics of one method; `as_row()` |
| `McNemarResult` | `b: int`, `c: int`, `statistic: float`, `pvalue: float` | b = only the reference is correct, c = only the compared method is correct |
| `OverlapSummary` | `all_intersection: float`, `avg_pairwise_intersection: float`, `consensus: Dict[str, float]` | Row averages; `consensus` keys are `consensus_>=2`, …, `consensus_==N` |

### 2-3. analysis.py

| Class | Fields | Description |
|---|---|---|
| `CategoryShare` | `category: str`, `count: int`, `percent: float` | Frequency of one category |
| `ContingencyTable` | `categories: Tuple[str, ...]`, `group_a: Tuple[int, ...]`, `group_b: Tuple[int, ...]` | Two-group table; `collapse_sparse()`, `permutation_pvalue()` |
| `GroupComparison` | `raw`, `tested: ContingencyTable`, `pvalue: float`, `permutation: bool` | `tested` is the table after merging sparse categories |
| `ClassScores` | `f1_macro`, `recall_macro`, `f1_weighted`, `recall_weighted` (float) | Classification scores; NaN when nothing can be compared |
| `AgreementResult` | `accuracy: Estimate`, `scores: ClassScores` | Agreement of one attribute or attribute group (Wilson 95% CI) |

---

## 3. Main functions

| Function | Signature | Returns |
|---|---|---|
| `llm_parser.parse_procedures` | `async (names, chat, batch_size=15)` | Raw Parser answers in format 1-1 |
| `retrieval.retrieve_candidates` | `(parsed_json_texts, scorer, top_n=10)` | `List[List[Candidate]]`; an empty list for unreadable rows |
| `retrieval.DirectRetriever.retrieve` | `(procedure_name, top_n=10)` | Candidates in descending similarity |
| `llm_selector.select_candidates` | `async (items, chat, batch_size=15)` | `(raw answer, Selection or None)` per item; the answer is in format 1-2 |
| `playbook.load_playbook` | `(path, name_column="PartName")` | `Playbook`, preserving CSV row order |
| `retrieval.load_radlex_hierarchy` | `(path)` | `RadLexHierarchy` (parent → child edges) |
| `analysis.load_playbook_parts` | `(path)` | LOINC → {PartTypeName: "name1, name2"} |

---

## 4. Excel file formats (command-line input/output)

The column names and cell formats match the experiment outputs, so existing result files can be processed directly.

### 4-1. mapping

| Command | Reads | Writes |
|---|---|---|
| `parse` | `--column` (default `input_text`) | `input_text_json` |
| `retrieve` | `input_text_json` (`--column` for direct) | `candidates`, `filtered_candidates` |
| `select` | `--column`, `filtered_candidates` | `res`, `map_loinc`, `map_longname` |
| `run` | `--column` | All of the above (no `input_text_json` for direct) |

Cell formats:

| Column | Format | Example |
|---|---|---|
| `input_text_json` | Raw Parser text (1-1) | ```` ```json {...} ``` ```` |
| `candidates` | `str()` of a Python `list[dict]` (read with `ast.literal_eval`) | `[{'loinc_num': '24000-1', 'long_common_name': '...', 'score': 7.5, 'matched_rids': [...], ...}]` |
| `filtered_candidates` | Same, with only `loinc_num`, `long_common_name`, `score` | `[{'loinc_num': '24000-1', 'long_common_name': '...', 'score': 7.5}]` |
| `res` | Raw Selector text (1-2) | |
| `map_loinc`, `map_longname` | Selected code and name; `""` if unreadable | `24000-1` |

### 4-2. evaluation input

| Column | Required | Use |
|---|---|---|
| `LoincNumber` | Yes | Gold code; an empty cell becomes `"nan"` and counts as wrong (drop with `--exclude-missing-gold`) |
| `candidates` (`filtered_candidates` for overlap) | Yes | Top-10 ranking |
| `res` | No | Final selection; none if absent |

### 4-3. analysis input

| Command | Required columns |
|---|---|
| `extract` | `input_text_json` → adds nine `Rad.*` columns and `Modality`, `Anatomic Location`, `TimingPharm` |
| `compare`, `summarize` | Columns produced by `extract` |
| `region-focus` | `Rad.Anatomic Location.Region Imaged`, `Rad.Anatomic Location.Imaging Focus` |
| `agreement` | `LoincNumber`, and `filtered_candidates` (default) or `map_loinc` |

### 4-4. External data files

| File | Columns | Used by |
|---|---|---|
| `LoincRsnaRadiologyPlaybook_2025.csv` | `LoincNumber, LongCommonName, PartNumber, PartTypeName, PartName, PartSequenceOrder, RID, PreferredName, RPID, LongName` | mapping, analysis |
| `ImagingDocumentCodes_2025.csv` | `LOINC_NUM, LONG_COMMON_NAME` | Direct mapping baseline |
| `Radlex.owl` | OWL classes (`RID\d+`) and `is_a` | LCS |

### 4-5. Settings (`utils.Settings`, environment variables)

| Variable | Default |
|---|---|
| `OPENAI_API_KEY` | (required when an LLM or embeddings are used) |
| `ARKE_CHAT_MODEL` | `gpt-4o-2024-08-06` |
| `ARKE_EMBEDDING_MODEL` | `text-embedding-ada-002` |
| `ARKE_PLAYBOOK_CSV` | `LoincRsnaRadiologyPlaybook_2025.csv` |
| `ARKE_IMAGING_CODES_CSV` | `ImagingDocumentCodes_2025.csv` |
| `ARKE_RADLEX_OWL` | `Radlex.owl` |
| `ARKE_BATCH_SIZE` | `15` |
