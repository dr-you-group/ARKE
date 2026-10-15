# Glossary (Ubiquitous Language)

Code names use only the terms in this glossary. When a new term is needed, update this file before the code.

| Term | Code name | Definition | Module | Source |
|---|---|---|---|---|
| Local procedure name | `procedure_name`, `input_text` | Imaging procedure name as recorded in a hospital EHR (mixed Korean and English, with abbreviations) | main | Paper 3.1 |
| Playbook | `Playbook` | LOINC/RSNA Radiology Playbook (v2.80): LOINC code names combined with RadLex attributes | playbook | Paper 1 |
| Playbook row | `PlaybookRow` | One row of the Playbook CSV: one LOINC code linked to one RadLex attribute (a knowledge-graph edge) | playbook | Playbook CSV |
| Attribute type | `part_type` (PartTypeName) | One of the 18 Playbook attribute types, e.g. `Rad.Modality.Modality Type` | playbook | Supp. Table 7 |
| RID | `rid` | RadLex concept identifier, e.g. `RID10345` | playbook | RadLex |
| Relation key | `relation_key` | Edge label of the knowledge graph used for weighting | retrieval | Implementation |
| Parsed procedure | `ParsedProcedure` | A procedure name decomposed into the 18 attributes by the LLM Parser (JSON) | llm_parser | Paper 3.3 |
| Candidate | `Candidate` | A Playbook code name proposed by retrieval, with its score | retrieval | Paper 3.3 |
| Candidate list | `List[Candidate]` | The Top 10 passed to the LLM Selector | retrieval | Paper 3.3 |
| Attribute weights | `AttributeWeights` | w(a): 1.5 for important attributes, 1.0 otherwise | retrieval | Paper 3.4 |
| Scorer | `WeightedMatchScorer`, `JaccardScorer`, `SimpleOverlapScorer`, `F1Scorer`, `LcsScorer` | Ranks Playbook codes by attribute similarity (weighted / jaccard / match / f1 / lcs) | retrieval | Paper 3.3, Supp. Table 5 |
| Lowest Common Subsumer | `lowest_common_subsumer` | Deepest common ancestor of two concepts in the RadLex is-a hierarchy (LCS) | retrieval | Paper 3.3 |
| Direct mapping (baseline) | `direct`, `DirectRetriever` | Retrieval by embedding similarity between the raw name and Playbook code names only | retrieval | Paper 3.5 |
| Selection | `Selection` | The one code chosen by the LLM Selector, with its reasoning | llm_selector | Paper 3.3 |
| Gold code | `gold`, `LoincNumber` | Reference code assigned by radiologists | evaluation | Paper 3.5 |
| Ranked prediction | `RankedPrediction` | Gold code, Top 10, and final selection for one procedure name | evaluation | Paper 3.5 |
| Final Recall@1 | `final_recall_at_1` | Share of selections equal to the gold code | evaluation | Paper Table 3 |
| Candidate overlap | `candidate_overlap` | Agreement among the Top-10 sets of several methods | evaluation | Supp. Table 11 |
| Cohort comparison | `characteristics_table` | Comparison of attribute distributions between two institutions (chi-square / permutation test) | analysis | Paper Table 1 |
| Other | `OTHER` (`"기타"`) | Category that collects sparse categories; the label is kept as in the published tables | analysis | Implementation |
| Attribute agreement | `attribute_agreement` | Share of procedures whose predicted and gold codes have the same attribute value | analysis | Paper Table 4 |
