# Flowcharts

Mermaid diagrams of how data and calls flow. They render as diagrams on GitHub and in VS Code (with the Markdown Preview Mermaid Support extension).

## 1. ARKE pipeline (paper Fig. 1)

```mermaid
flowchart LR
    IN["Local procedure name<br/>e.g. Foot Standing AP Rt"]

    subgraph ARKE["ARKE"]
        direction LR
        P["LLM Parser<br/>GPT-4o<br/>18 Playbook attributes (JSON)"]
        R["Attribute-based scoring retrieval<br/>no LLM<br/>Jaccard · Match · Weighted · F1 · LCS"]
        S["LLM Selector<br/>GPT-4o, chain-of-thought<br/>one of the Top 10"]
        P --> R --> S
    end

    KG[("Playbook knowledge graph<br/>LOINC ↔ RadLex RID<br/>LoincRsnaRadiologyPlaybook_2025.csv")]
    OWL[("RadLex is-a hierarchy<br/>Radlex.owl<br/>LCS only")]

    IN --> P
    KG --> R
    OWL -.-> R
    S --> OUT["One Playbook code<br/>e.g. XR Foot - right Views AP W standing"]

    IN -. baseline .-> D["Direct mapping<br/>ada-002 embeddings + FAISS"]
    D -.-> S
```

## 2. CLI stages and Excel columns

Each stage adds columns to the Excel file.

```mermaid
flowchart TD
    X0["input.xlsx<br/>input_text"]
    X1["+ input_text_json"]
    X2["+ candidates<br/>+ filtered_candidates"]
    X3["+ res, map_loinc, map_longname"]
    E["Evaluation<br/>metrics · mcnemar · overlap"]
    A["Analysis<br/>extract · compare · summarize · region-focus · agreement"]

    X0 -- "python main.py parse" --> X1
    X1 -- "python main.py retrieve --method weighted|jaccard|match|f1|lcs" --> X2
    X0 -- "python main.py retrieve --method direct" --> X2
    X2 -- "python main.py select" --> X3
    X0 -- "python main.py run (parse + retrieve + select)" --> X3
    X3 --> E
    X1 --> A
    X3 --> A
```

## 3. Module calls: `python main.py run --method weighted`

Solid arrows are calls and dashed arrows are returns.

```mermaid
sequenceDiagram
    autonumber
    participant M as main.py
    participant P as llm_parser.py
    participant PB as playbook.py
    participant R as retrieval.py
    participant S as llm_selector.py
    participant U as utils.py (OpenAIChat)
    participant API as OpenAI API

    M->>PB: load_playbook(ARKE_PLAYBOOK_CSV)
    M->>P: parse_procedures(names)
    loop batches of 15
        P->>U: complete(PARSER_PROMPT)
        U->>API: chat.completions
        API-->>U: raw JSON
        U-->>P: input_text_json
    end
    P-->>M: input_text_json
    M->>R: retrieve_candidates(input_text_json, WeightedMatchScorer)
    R->>P: ParsedProcedure.from_json_text → input_rids
    R-->>M: Top-10 candidates (empty for unreadable rows)
    M->>S: select_candidates((name, candidates))
    loop batches of 15
        S->>U: complete(SELECTOR_PROMPT)
        U->>API: chat.completions
        API-->>U: raw selection JSON
        U-->>S: res
    end
    S-->>M: (res, Selection)
    M->>M: write Excel columns
```

## 4. Candidate retrieval (retrieval.py)

```mermaid
flowchart TD
    J["input_text_json"] --> CL{"Strip code fence<br/>JSON readable?"}
    CL -- no --> EMPTY["Empty candidate list<br/>(warning logged)"]
    CL -- yes --> PARTS["Parts: 18 attribute values"]
    PARTS --> MODE{"Scoring method"}

    MODE -- "jaccard / match / weighted / f1" --> G["For each value, find the RID with the same name<br/>across all types (first in CSV order)<br/>skip NaN and empty values"]
    MODE -- lcs --> RL["Look up within the same attribute type first,<br/>then across all types"]

    G --> A["Input RID set A"]
    A --> LOOP["For every LOINC in the Playbook<br/>B = its RID set"]
    LOOP --> SCORE{"Score"}
    SCORE -- jaccard --> SJ["|A∩B| / |A∪B|  (score 0 dropped)"]
    SCORE -- match --> SM["|A∩B| − |B−A| − |A−B|"]
    SCORE -- weighted --> SW["Σw(matched) − Σw(missing) − 1.0×|extra|<br/>w = 1.5 if relation_key is in the important list, else 1.0"]
    SCORE -- f1 --> SF["2PR/(P+R)  (no match dropped)"]

    RL --> LCS["Wu-Palmer similarity per attribute type<br/>mean of best matches both ways, −0.5 per item on one side only"]

    SJ & SM & SW & SF & LCS --> RANK["Round to 5 decimals<br/>stable sort (ties keep CSV order)<br/>top 10"]
    RANK --> OUT["CandidateList"]
```

## 5. Weighted-matching weight

How `relation_key` makes Timing and Laterality Presence receive 1.0 (business.md, section 8, item 1).

```mermaid
flowchart LR
    T["PartTypeName of the edge"] --> RM["Remove 'Rad.' and split on '.'"]
    RM --> N{"At least 2 segments?"}
    N -- yes --> L2["Last two segments<br/>e.g. Modality.Modality Type<br/>e.g. Laterality.Presence"]
    N -- no --> RAW["Original string<br/>e.g. Rad.Timing"]
    L2 --> HW{"In the important-attribute list?"}
    RAW --> HW
    HW -- yes --> W15["w = 1.5"]
    HW -- no --> W10["w = 1.0<br/>(including Rad.Timing and Laterality.Presence)"]
```

## 6. Evaluation

```mermaid
flowchart TD
    F["Result Excel per method<br/>LoincNumber · candidates · res"] --> RP["RankedPrediction list<br/>missing gold → 'nan' (counted as wrong)"]
    RP --> MET["metrics"]
    RP --> MC["mcnemar"]
    RP --> OV["overlap"]

    MET --> W["Recall@1/3/5/10, final Recall@1<br/>→ Wilson 95% CI"]
    MET --> B["MRR, NDCG@10<br/>→ bootstrap, 10,000 resamples, seed 42"]
    W & B --> T3["Metrics table"]

    MC --> MN["b, c against the reference method<br/>(|b−c|−1)²/(b+c) → p-value"]
    OV --> OS["Mean intersection and consensus of Top-10 sets"]
```

## 7. Analysis

```mermaid
flowchart TD
    J["input_text_json"] -- extract --> P9["Nine attribute columns<br/>+ Modality / Anatomic Location / TimingPharm"]

    P9 -- compare --> TOK["Multi-response tokens<br/>split on commas · lowercase · drop quotes and missing values"]
    TOK --> CT["Two-cohort table (all categories)"]
    CT --> COL{"Any expected count < 5<br/>and more than 2 categories?"}
    COL -- yes --> MERGE["Smallest category → OTHER"] --> COL
    COL -- no --> ADD["Append OTHER row"]
    ADD --> Z{"OTHER = 0?"}
    Z -- yes --> SKIP["Cannot be tested → left out of the table"]
    Z -- no --> E{"Expected count < 5 remains?"}
    E -- yes --> PERM["Permutation p-value<br/>20,000 draws, seed 42"]
    E -- no --> CHI["Chi-square p-value"]
    PERM & CHI --> BT["Characteristics table"]

    P9 -- summarize --> SUM["Main categories + OTHER counts and shares"]
    P9 -- region-focus --> RF["Imaging focus distribution per region<br/>(one sheet each)"]

    R["Result Excel<br/>Top-1 or map_loinc, LoincNumber"] -- agreement --> PB["Playbook CSV → attributes per LOINC"]
    PB --> AG["Agreement of 5 attributes and 2 groups<br/>Wilson CI, macro/weighted F1 and recall"]
```
