"""A small Playbook with the two candidates of paper Table 2 ("Foot Standing AP Rt")."""

from playbook import Playbook, PlaybookRow

STANDING_AP = "24000-1"
TWO_VIEWS = "24000-2"
CHEST = "30000-1"

_ROWS = [
    (
        STANDING_AP,
        "XR Foot - right Views AP W standing",
        [
            ("RID10345", "Rad.Modality.Modality Type", "XR"),
            ("RID2", "Rad.Anatomic Location.Region Imaged", "Lower extremity"),
            ("RID3", "Rad.Anatomic Location.Imaging Focus", "Foot"),
            ("RID49844", "Rad.Anatomic Location.Laterality.Presence", "True"),
            ("RID5825", "Rad.Anatomic Location.Laterality", "Right"),
            ("RID10357", "Rad.View.View Type", "AP"),
            ("RID7", "Rad.Maneuver.Maneuver Type", "Standing"),
            ("RID8", "Rad.Timing", "W"),
            ("RID9", "Rad.View.Aggregation", "Views"),
        ],
    ),
    (
        TWO_VIEWS,
        "XR Foot - right 2 Views",
        [
            ("RID10345", "Rad.Modality.Modality Type", "XR"),
            ("RID2", "Rad.Anatomic Location.Region Imaged", "Lower extremity"),
            ("RID3", "Rad.Anatomic Location.Imaging Focus", "Foot"),
            ("RID49844", "Rad.Anatomic Location.Laterality.Presence", "True"),
            ("RID5825", "Rad.Anatomic Location.Laterality", "Right"),
            ("RID10", "Rad.View.Aggregation", "Views 2"),
        ],
    ),
    (
        CHEST,
        "XR Chest 2 Views",
        [
            ("RID10345", "Rad.Modality.Modality Type", "XR"),
            ("RID11", "Rad.Anatomic Location.Region Imaged", "Chest"),
            ("RID10", "Rad.View.Aggregation", "Views 2"),
        ],
    ),
]


def playbook() -> Playbook:
    return Playbook(
        PlaybookRow(loinc, name, rid, part_type, part_name)
        for loinc, name, parts in _ROWS
        for rid, part_type, part_name in parts
    )


FOOT_STANDING_AP_RT = """```json
{
    "Name": "Foot Standing AP Right",
    "Parts": {
        "Rad.Modality.Modality Type": "XR",
        "Rad.Modality.Modality Subtype": "NaN",
        "Rad.Anatomic Location.Region Imaged": "Lower extremity",
        "Rad.Anatomic Location.Imaging Focus": "Foot",
        "Rad.Anatomic Location.Laterality.Presence": "True",
        "Rad.Anatomic Location.Laterality": "Right",
        "Rad.View.View Type": "AP",
        "Rad.Timing": "NaN",
        "Rad.Maneuver.Maneuver Type": "Standing"
    }
}
```"""
