"""System, Parser, and Selector prompts of ARKE (Supplementary Table 6 of the paper).

Do not reformat: the text, including its whitespace, is part of the published method.
"""

SYSTEM_PROMPT = """
    You are an expert in medical terminology and LOINC (Logical Observation Identifiers Names and Codes) coding. 
    Your responses should be formatted strictly according to the guidelines provided by the user."""

# LLM Parser prompt (Supplementary Table 6A)
PARSER_PROMPT = """
Your task is to analyze a medical imaging term (especially in the procedure domain) provided as input and standardize it by removing special characters, and translating any non-English terms into English. The structured output should follow predefined categories consisting of 18 parts.

Here is the structure to follow:
{{
    "Name": "<Standardized Medical Imaging Term>",
    "Parts": {{
        "Rad.Modality.Modality Type": "Select: the type of modality, which is primarily represented using the two-letter DICOM modality codes. Options include: 'XR', 'CT', 'MR', 'RF', 'US', 'NM', 'MG', 'PT+CT', 'PT', 'DXA', 'NM.SPECT+CT'. If none apply, use 'Imaging modality'. Note: 'RF' stands for 'Radiofluoroscopy' and should be selected when the term describes contrast-enhanced dynamic imaging of anatomical structures. This includes procedures involving retrograde contrast flow, catheter-based contrast injection, vascular or ductal visualization, or real-time fluoroscopic guidance. Studies ending in '-graphy' (such as 'angiography', 'cystography', or 'fistulogram') typically indicate RF unless another modality like CT or MR is explicitly stated. In contrast, 'XR' should be selected for conventional radiography performed without contrast, especially when standard view types (such as AP, PA, lateral, or oblique), patient positions (such as standing or decubitus), or skeletal anatomy terms (such as chest, hip, spine, or knee) are present without any mention of real-time guidance or contrast use.        
        "Rad.Modality.Modality Subtype": "Select: a particularly common or evocative configuration of the modality. Options include: 'Angio', 'Portable', 'Doppler', 'SPECT', 'Tomography', 'tomosynthesis', 'Stereotactic', 'Perfusion', 'FFD', 'Video', 'Elastography', 'stereoscopic', 'Functional', 'Cone beam', 'Spectroscopy', 'Densitometry', 'Scanogram', 'Slot radiography', 'Tractography', 'A-scan'. If none apply, return 'NaN'.",
        "Rad.Anatomic Location.Region Imaged": "Select: the coarse-grained descriptor of the area imaged, which may also serve as a grouper for finding related imaging exams. Options include: 'Lower extremity', 'Abdomen', 'Upper extremity', 'Chest', 'Head', 'Pelvis', 'Neck', 'Breast', 'Extremity', 'Whole Body', 'Umbilical artery', 'Umbilical vessels', 'Umbilical cord', 'Cerebral artery middle'. If none apply, use 'XXX'. Note: If the term includes 'torso' or suggests the trunk of the body, select 'Whole Body'. If the term mentions 'spine', extract all applicable regions that correspond to its parts (e.g., 'Spine.cervical' → 'Neck', 'Spine.thoracic' → 'Chest', 'Spine.lumbar' → 'Abdomen') and return them as a list if more than one applies.",
        "Rad.Anatomic Location.Imaging Focus": "Extract: a more fine-grained descriptor of the specific target structure of the imaging exam. This could include:
          - Bony structures: 'Shoulder', 'Knee', 'Hip', 'Spine.lumbar', 'Spine.thoracic', 'Spine.cervical', 'Elbow', 'Hand', 'Foot', 'Finger', 'Toes', 'Skull', 'Temporal bone', 'Clavicle', 'Fibula', 'Fibia', 'Femur', 'Calcaneus', 'Bone', 'Lower leg', 'Joint'
          - Organs & soft tissues: 'Brain', 'Heart', 'Kidney', 'Liver', 'Pancreas', 'Uterus', 'Urinary bladder', 'Colon', 'Prostate', 'Ureter', 'Thyroid gland', 'Sinuses', 'Spine', 'Sacrum', 'Orbit'
          - Vascular structures: 'Vein', 'Head vessels', 'Neck vessels', 'Renal vessels', 'Lower extremity arteries', 'Lower extremity veins', 'Extremity vessels', 'Hepatic veins', 'Hepatic artery', 'Portal vein', 'Splenic vein', 'Spine vessel', 'Vertebral vessels', 'Foot vessels'
          If not mentioned, return 'NaN'. Note: Always extract the most specific anatomical focus available. For example, prefer 'Spine.cervical' over just 'Spine', or 'Calcaneus' over 'Foot'.",
        "Rad.Anatomic Location.Laterality.Presence": "Select: determine whether laterality is mentioned in the imaging term. If the imaging exam requires laterality to be specified, set this attribute to 'True'. Otherwise, return 'NaN'.",
        "Rad.Anatomic Location.Laterality": "Select: the laterality of the anatomical site, only if 'Laterality.Presence' is 'True'. Options include: 'Unspecified', 'Right', 'Left', 'Bilateral', 'Unilateral'. If Laterality Presence is not indicated, return 'NaN'.",
        "Rad.View.Aggregation": "Extract: the extent of the imaging performed, described either in quantitative terms (such as number of views) or in subjective terms (such as 'Complete' or 'Diagnostic'). This could include: 'Views', 'View', 'Views 2', 'Limited', 'Views 3', 'Views GE 2', 'Views GE 3', 'Additional', 'Perfusion', 'Views 4', 'Views 1 or 2', 'Views GE 4', 'Views 5', 'Diagnostic', 'Gated', 'First pass', 'Views 2 or 3', 'Wall motion', 'Ejection fraction', 'Multiple areas', 'Dynamic'. If not mentioned, return 'NaN'. Note: If multiple distinct view types (e.g., 'pa view', 'lateral view', 'oblique view') are present, this should be interpreted as 'Views'.",
        "Rad.View.View Type": "Extract: the specific view name used in the imaging exam, indicating patient orientation or image acquisition direction. This could include: 'AP', 'lateral', 'oblique', 'PA', 'axillary', 'Sunrise', 'tunnel', 'Y', 'outlet', 'lateral crosstable', 'Grashey', 'Internal rotation', 'L-oblique', 'upright', 'R-oblique', 'External rotation', 'West Point', 'Mortise', 'Waters', 'lateral frog'. If not mentioned, return 'NaN'. Note: Abbreviations like 'pa', 'ap', 'lat', and 'obl' should be normalized to match the example terms exactly (e.g., use 'PA' instead of 'posteroanterior').",
        "Rad.Timing": "Select: the timing of image acquisition in relation to the use or non-use of a pharmaceutical or maneuver. This may indicate a single state (e.g., 'WO', 'W') or a before-and-after combination (e.g., 'WO & W'). Options include: 'W', 'WO', 'WO & W', 'during surgery', 'Post fatty meal', '48H post', '10M post', '2H post', '15M post', '30M post', '45M post', '1H post', '1.5H post'. If none apply, return 'NaN'. Note: Terms such as 'noncontrast', 'wo contrast', 'without contrast', and 'no contrast' should all be interpreted as indicating 'WO'. If the term simply includes the word 'contrast' without a negation, it should be interpreted as indicating 'W'.",
        "Rad.Maneuver.Maneuver Type": "Select: the type of patient-performed maneuver used during the imaging, typically to test or demonstrate a dynamic anatomical or physiological function. Options include: 'Standing', 'Stress', 'At rest', 'Extension', 'Flexion', 'R-bending', 'L-bending', 'Weight', 'Bending', 'Inspiration', 'Expiration', 'Single state of exercise', 'Multiple states of exercise', 'Clenched fist', 'Sitting', 'Valgus', 'Voiding', 'Defecation', 'Hyperextension', 'Standing in brace'. If none apply, return 'NaN'.",
        "Rad.Pharmaceutical.Substance Given": "Extract: the pharmaceutical agent, contrast agent, or radiopharmaceutical administered during the imaging procedure, as indicated at a clinically relevant level. It is often sufficient to record general terms like 'Contrast' without requiring the specific substance. This could include: 'Contrast', 'Radionuclide', 'Tc-99m Sestamibi', 'Tl-201', 'Ga-67', 'Tc-99m', 'Air contrast', 'Tc-99m DTPA', 'Reduced contrast volume', '18F-FDG', 'Tc-99m SC', 'Adenosine', 'Tc-99m pertechnetate', 'Dipyridamole', 'In-111 satumomab', 'I-131 MIBG', 'Tc-99m glucoheptonate', 'I-131', 'Xe-133', 'Tc-99m MAA', '18F-NaF'. If not mentioned, return 'NaN'. Note: Terms like 'with contrast' or 'noncontrast' imply the presence or consideration of a contrast agent, so 'Contrast' should be included even if not administered.",
        "Rad.Pharmaceutical.Route": "Extract: the route of pharmaceutical administration during the imaging, represented using standard abbreviations (e.g., 'IV', 'PO') where applicable. This could include: 'IV', 'IA', 'IS', 'PO', 'IT', 'PR', 'Intra lymphatic', 'Retrograde', 'IH', 'Intra salivary duct', 'Intra duct', 'Intradisc', 'Intra bladder', 'Retrograde intrabiliary', 'Intra lacrimal duct', 'Antegrade', 'Intra multiple ducts', 'Existing catheter', 'Via fistula', 'IU'. If not mentioned, return 'NaN'.",
        "Rad.Reason for Exam": "Extract: the clinical indication or purpose for the imaging exam, such as a diagnosis, clinical status (e.g., post-op), altered anatomy (e.g., graft or implant), or the intended use of the study (e.g., screening). This could include: 'Cyst', 'Tumor', 'Blood flow', 'Implant', 'Screening', 'Scoliosis', 'Reconstruction', 'Bone density', 'Transplanted kidney', 'Pregnancy', 'infarct', '3D post processing', 'Graft', 'Function', 'Shunt patency', 'Fistula', 'Pulmonary embolus', 'Calcium score', 'Metastasis', 'Bone age', 'Multiple gestation pregnancy', 'First trimester', 'Second or third trimester'. If not mentioned, return 'NaN'.",
        "Rad.Guidance for.Presence": "Select: determine whether the imaging procedure includes an image-guided intervention. Return 'Guidance' if a guided action is described. Otherwise, return 'NaN'.",
        "Rad.Guidance for.Approach": "Select: the primary route of access used to perform the image-guided intervention. Options include: 'Percutaneous', 'Transjugular', 'Transhepatic', 'Deep', 'Superficial', 'Transcatheter', 'Transurethral', 'Intrathecal'. If none apply, return 'NaN'.",
        "Rad.Guidance for.Action": "Extract: the image-guided intervention performed during the procedure. This could include: 'Placement', 'Biopsy', 'Aspiration', 'Drainage', 'Injection', 'Aspiration.fine needle', 'Localization', 'Angioplasty', 'Needle localization', 'Removal', 'Transluminal angioplasty', 'Exchange', 'Embolization', 'Biopsy.core needle', 'Vertebroplasty', 'Infusion', 'Endoscopy', 'Radiation treatment', 'Nerve block', 'Atherectomy', 'Ablation', 'Radiofrequency ablation'. If not mentioned, return 'NaN'.",
        "Rad.Guidance for.Object": "Extract: the target of the image-guided intervention. This could include: 'Drainage catheter', 'Abscess', 'Fluid', 'Stent', 'Central venous catheter', 'Catheter', 'Chest tube', 'Tube', 'Foreign body', 'Tissue', 'Nephrostomy tube', 'Thrombolytic', 'Peripherally-inserted central venous catheter', 'Venous filter', 'Needle', 'Nephroureteral stent', 'Central venous catheter with port', 'Clip', 'Mass', 'Gastrojejunostomy tube', 'Amniotic fluid'. If not mentioned, return 'NaN'.",
        "Rad.Subject": "Select: the subject of the imaging when it differs from the patient, such as in prenatal imaging or specimen radiographs. Options include: 'Fetus', 'Breast specimen', 'Surgical specimen'. If none apply, return 'NaN'."
    }}
}}

Instructions:
- 'Name' should be a clear, standardized description of the imaging technique and context in English, with special characters removed.
- For fields marked **Select**, choose only from the provided list. Do not generate or infer new values.
- For fields marked **Extract**, use the provided examples if found, but you may also extract other medically appropriate values based on the input.
- If a field contains multiple applicable values, return them as an array of strings (e.g., ["value1", "value2"]).
- Return only valid JSON that can be parsed by `json.loads`, with all keys and strings enclosed in double quotes.

Medical Imaging Term: {input_text}
"""

# LLM Selector prompt (Supplementary Table 6B)
SELECTOR_PROMPT = """
Multiple LOINC codes are potential candidates.
Input Imaging Term: "{input_text}"
Top candidate LOINC codes with their Long Common Names:
{top_candidates_str}
Use clinical reasoning with a chain-of-thought approach to select the single most appropriate LOINC code based on the input term.

General instructions:
- Select only from the provided candidates, and copy the "long_common_name" verbatim from the chosen candidate.
- Do not add or expand details that are not present in the input term (e.g., WO/W phrasing, number of views, posture/breathing phases, multiple gestation, etc.).
- Preserve any specificity explicitly present in the input term (e.g., target vessel, fetal designation, contrast/route, views/posture). For Doppler studies, ensure that "Doppler" is explicitly preserved and pay close attention to the specified vessels.
- If multiple candidates are very similar and difficult to distinguish, choose the most general term among them. The clinical purpose of the exam (e.g., screening for specific conditions) is generally not critical for code selection.
- Do not change modality/type (or subtype).
- Contrast information is critical. If contrast is specified, always choose the "W contrast" candidate, not "WO and W contrast". If no "W contrast" candidate is available, select a candidate without contrast.
- If directions (AP, LT, RT, PA, LAT, etc.) do not exactly match the input term, choose a generalized candidate such as "views" or "single view", and do not select candidates with direction information added arbitrarily.

Return only valid JSON in the following format:

```json
{{
  "reasoning": "<step-by-step reasoning>",
  "selected_loinc": "<Chosen LOINC_NUM>",
  "long_common_name": "<Corresponding LONG_COMMON_NAME>"
}}
"""
