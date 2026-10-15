# Business Rules

This document lists the business rules that ARKE follows. Every rule matches the behavior used to produce the published results. Section 8 lists where that behavior differs from the wording of the paper.

## 1. Purpose

Map each local radiology procedure name (mixed Korean and English, with abbreviations) to **exactly one** LOINC/RSNA Radiology Playbook (v2.80) code name.

The name is not translated as a string. It is first **decomposed into ontology attributes** and then matched. The LLM is used in two places only:
- Attribute decomposition (Parser)
- Selection within the candidates (Selector)

Candidate retrieval does not use an LLM, which reduces the chance that the LLM invents non-existent codes (hallucination).

## 2. Knowledge graph (Playbook)

| Rule | Description | Code |
|---|---|---|
| G1 | One row of the Playbook CSV links one LOINC code to one RadLex attribute (RID) | `PlaybookRow` |
| G2 | The attribute set of a LOINC code is every RID it is linked to | `Playbook.loinc_rids()` |
| G3 | If the same (LOINC, RID) pair appears more than once, the attribute type of the last row is used for the edge | `Playbook._edge_part_types` |
| G4 | An RID's name comes from the `PartName` column (last row wins); `PreferredName` can be used instead | `load_playbook(name_column=)` |
| G5 | All lookups preserve CSV row order, which decides the order of tied scores | `Playbook` |

## 3. LLM Parser

| Rule | Description |
|---|---|
| P1 | Each procedure name is turned into JSON with the 18 Playbook attributes by GPT-4o (`gpt-4o-2024-08-06`, temperature 0, ARKE system prompt) |
| P2 | Special-character removal and translation into English happen in the same call |
| P3 | **Select** attributes may only take values listed in the prompt; **Extract** attributes may also take other medically appropriate values |
| P4 | A missing value is `"NaN"`; multiple values are an array |
| P5 | Calls run 15 at a time, and batches are processed in order |

The full prompt is in `prompts.py` (`PARSER_PROMPT`). It is part of the published method and is kept verbatim, including whitespace.

## 4. Candidate retrieval (no LLM)

### 4-1. Resolving input RIDs

| Rule | Description | Code |
|---|---|---|
| R1 | Attributes with an empty or `"NaN"` value are skipped | `ParsedProcedure.input_rids` |
| R2 | Each value is looked up by name **across all attribute types**, and the first RID in CSV order is used; case and outer spaces are ignored | `Playbook.first_rid_named` |
| R3 | A value with no RID of the same name is dropped | |
| R4 | If any value is not text, the row cannot be read | `InvalidParserOutput` |
| R5 | (LCS only) The lookup is made **within the same attribute type** first, then across all types; among several matches the first after sorting is used; `""`, `nan`, `none`, and `xxx` count as empty | `ParsedProcedure.relation_rids` |

### 4-2. Scores (A = input RID set, B = RID set of a candidate LOINC code)

| Method | CLI name | Score | Candidates dropped |
|---|---|---|---|
| Jaccard | `jaccard` | \|A∩B\| / \|A∪B\| | Score 0 |
| Simple overlap | `match` | \|A∩B\| − \|B−A\| − \|A−B\| | None |
| **Weighted (ARKE default)** | `weighted` | Σ w(matched) − Σ w(missing) − 1.0 × \|extra\| | None |
| F1 | `f1` | 2PR/(P+R), P = \|A∩B\|/\|A\|, R = \|A∩B\|/\|B\| | No match |
| LCS | `lcs` | Sum of per-attribute hierarchy similarities (4-4) | None |

- **Missing** = attributes in the candidate but not in the input (B−A)
- **Extra** = attributes in the input but not in the candidate (A−B)

### 4-3. Weighted-matching weights w(a)

| Rule | Description |
|---|---|
| W1 | For matched and missing attributes, w(a) depends on the attribute type of the edge |
| W2 | If the attribute type converted by `relation_key` is in the important-attribute list, w = 1.5; otherwise 1.0 |
| W3 | `relation_key`: remove `Rad.` and keep the last two dotted segments; if there is only one segment, the original string is kept |
| W4 | Important-attribute list (9): Modality Type, Modality Subtype, Region Imaged, Imaging Focus, Timing, Substance Given, View Type, Laterality Presence, Laterality |
| W5 | Because of W3, **Timing and Laterality Presence actually receive 1.0** (section 8, item 1); the other seven receive 1.5 |
| W6 | Extra attributes have no edge to the candidate, so 1.0 is always subtracted |

Example (paper Table 2, input "Foot Standing AP Rt"):

| Candidate | Matched | Missing | Extra | Score |
|---|---|---|---|---|
| XR Foot - right Views AP W standing | 1.5×5 + 1.0 (Presence) + 1.0 (Maneuver) = 9.5 | Timing 1.0 + View Aggregation 1.0 | None | **7.5** |
| XR Foot - right 2 Views | 1.5×4 + 1.0 (Presence) = 7.0 | View Aggregation 1.0 | View Type 1.0, Maneuver 1.0 | **4.0** |

### 4-4. LCS (Lowest Common Subsumer)

| Rule | Description |
|---|---|
| L1 | Depth in the RadLex is-a hierarchy is the shortest distance from a root; nodes no root reaches have depth 0 |
| L2 | Similarity of two RIDs: 1.0 if identical, otherwise 2·depth(LCS) / (depth(a) + depth(b)); 0 if there is no common ancestor or an RID is not in the hierarchy |
| L3 | Per attribute type, when both sides have values: (mean best similarity input→candidate + mean best similarity candidate→input) / 2 |
| L4 | When only one side has values: −0.5 × the larger count; when neither side has values: 0 |
| L5 | Candidate score = sum over all attribute types |

### 4-5. Ranking and failures

| Rule | Description |
|---|---|
| K1 | Scores are rounded to 5 decimals and sorted in descending order with a stable sort, so ties follow CSV order |
| K2 | The top 10 (`TOP_N`) go to the Selector |
| K3 | A row whose Parser output cannot be read gets an empty candidate list; the error is logged and processing continues |

### 4-6. Direct mapping baseline (`direct`)

| Rule | Description |
|---|---|
| D1 | Each `ImagingDocumentCodes` row (`LOINC_NUM: …\nLONG_COMMON_NAME: …`) is embedded with ada-002 and stored in FAISS |
| D2 | The top 10 are retrieved with the raw procedure name; score = 1 − FAISS distance |
| D3 | The Parser is not used |

## 5. LLM Selector

| Rule | Description |
|---|---|
| S1 | Given the procedure name and the 10 candidates (code and name only), choose **exactly one** with chain-of-thought reasoning |
| S2 | Choose only from the candidates and copy the candidate's name verbatim |
| S3 | Do not add details absent from the input (W/WO contrast, number of views, posture, and so on) |
| S4 | Keep details stated in the input (vessels, contrast, view direction, and so on); always keep "Doppler" |
| S5 | If candidates are nearly indistinguishable, choose the most general one |
| S6 | If contrast is stated, choose "W contrast" rather than "WO and W"; if no such candidate exists, choose a candidate without contrast |
| S7 | If view directions do not match exactly, choose a general candidate such as "views" or "single view" |
| S8 | If the answer cannot be read, there is no selection; the raw answer (`res`) is still stored |

S2–S7 are the instructions of the Selector prompt. The code does not prevent a selection outside the candidates; `Selection.is_within()` checks it.

## 6. Evaluation

| Rule | Description |
|---|---|
| E1 | Gold and candidate codes are compared as strings after trimming spaces |
| E2 | Recall@k: share of rows whose gold code is in the top k (k = 1, 3, 5, 10) |
| E3 | MRR: mean of 1/(gold rank); 0 if the gold code is absent |
| E4 | NDCG@10: with a single relevant item, the mean of 1/log2(rank + 1) |
| E5 | Final Recall@1: share of rows whose selected code equals the gold code |
| E6 | Rows without a gold code stay in the denominator and count as wrong (internal test set, n=237); `--exclude-missing-gold` drops them |
| E7 | 95% CI for proportions: Wilson interval |
| E8 | 95% CI for MRR and NDCG: percentile bootstrap, 10,000 resamples, seed 42, percentiles 2.5–97.5 |
| E9 | Methods are compared with the continuity-corrected McNemar test against a reference method on the same samples; NaN when b + c = 0 |
| E10 | Candidate overlap: per row, the common codes across all methods, the mean pairwise intersection, and the number of codes proposed by at least k methods, averaged over rows |

## 7. Analysis

| Rule | Description |
|---|---|
| A1 | Nine attributes are analysed: Modality Type, Modality Subtype, Region Imaged, Imaging Focus, Laterality Presence, Laterality, View Type, Timing, Substance Given |
| A2 | Combined attributes: Modality = Type_Subtype, Anatomic Location = Region_Focus, TimingPharm = Timing_Substance; blank parts are dropped |
| A3 | Multi-response: one procedure can fall into several categories; values are split on commas, lowercased, stripped of edge quotes, and nan/none/null/empty values are removed |
| A4 | Two-cohort comparison: build a table of all categories; while any expected count is below 5, merge the category with the smallest total into OTHER; stop when two categories remain or all expected counts are at least 5, then append the OTHER row |
| A5 | If expected counts below 5 remain after merging, the p-value comes from a Monte Carlo permutation test (20,000 draws, seed 42, category totals redistributed binomially, p = (exceedances + 1)/(draws + 1)) |
| A6 | If there is no sparse category to merge, the OTHER row is zero and the variable cannot be tested; it is left out of the table (for example, Laterality Presence) |
| A7 | Main-category summary: count the listed main categories and OTHER for the rest; percentages are of all tokens, rounded to one decimal |
| A8 | Region/Focus summaries keep the original case; an empty focus counts once as "(None)" |
| A9 | Attribute agreement compares the Playbook attributes of the predicted code (retrieval Top-1 by default) with those of the gold code; both sides missing counts as agreement |
| A10 | An attribute group (Pharma + Timing, Laterality) agrees only when every attribute in it agrees |
| A11 | Macro and weighted F1 and recall follow scikit-learn defaults (zero_division = 0); for single attributes, pairs with a missing side are excluded |
| A12 | The Playbook attribute table is built from the CSV: names of the same attribute type are joined with `", "` in row order, and outer braces (`{…}`) are removed |

The label of the merged category is the string `"기타"` ("other"), as it appears in the published tables.

## 8. Differences between the paper text and the implemented behavior

This repository keeps the implemented behavior so that the published results are reproduced.

| # | Paper text | Implemented behavior | Note |
|---|---|---|---|
| 1 | All nine weighted attributes get 1.5 (section 4.1) | Timing and Laterality Presence get 1.0 (W3, W5) | The paper's Table 2 example gives the same scores (7.5, 4.0) either way |
| 2 | Extra attributes subtract w(a) (formula in section 3.4) | 1.0 is always subtracted (W6) | |
| 3 | The Parser uses RAG (section 3.2) | The Parser uses the prompt only; embeddings are used only in the direct baseline | |
| 4 | Attribute agreement uses the finally selected code (section 3.5) | The analysis compares the retrieval Top-1 with the gold code | `--predicted map_loinc` uses the final selection |

## 9. Security

| Rule | Description |
|---|---|
| X1 | API keys are read only from environment variables or `.env` (git-ignored) and are never written in code |
| X2 | LLM calls use temperature 0; data handling follows the OpenAI data policy |
