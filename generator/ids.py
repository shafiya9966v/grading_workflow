"""ID helpers. Every ID in the dataset is built here, so the formats stay identical
in every table and every file.

Rules from the task: zero-padded counters, immutable IDs, and a referenced ID must
match its parent's ID exactly. Child IDs embed the parent ID, so a join can be
checked from the string alone.
"""
import re

from config import YEAR


def _counter(n: int, width: int) -> str:
    """Zero-pad a positive counter, and refuse values that would not fit."""
    if not isinstance(n, int) or n < 1 or n >= 10 ** width:
        raise ValueError(f"counter {n!r} must be an integer from 1 to {10 ** width - 1}")
    return f"{n:0{width}d}"


# ---- master data -----------------------------------------------------------
def course_id(n: int) -> str:                 # CRS-2026-0001  (format is my choice)
    return f"CRS-{YEAR}-{_counter(n, 4)}"


def learner_id(n: int) -> str:                # LRN-000001     (format is my choice)
    return f"LRN-{_counter(n, 6)}"


def enrollment_id(course: str, learner: str) -> str:
    return f"ENR-{course}-{learner}"


def assignment_id(n: int) -> str:             # ASN-2026-000001  (given by the task)
    return f"ASN-{YEAR}-{_counter(n, 6)}"


def rubric_id(assignment: str, rubric_no: int = 1) -> str:   # RUB-<assignment-id>-01
    return f"RUB-{assignment}-{_counter(rubric_no, 2)}"


def criterion_id(rubric: str, criterion_no: int) -> str:     # <rubric-id>-C01
    return f"{rubric}-C{_counter(criterion_no, 2)}"


# ---- transactions ----------------------------------------------------------
def submission_id(assignment: str, learner: str, attempt_no: int = 1) -> str:
    return f"SUB-{assignment}-{learner}-{_counter(attempt_no, 2)}"   # SUB-<asn>-<lrn>-01


def artifact_id(submission: str, n: int) -> str:
    return f"ART-{submission}-{_counter(n, 2)}"


def grade_id(submission: str) -> str:                         # GRD-<submission-id>
    return f"GRD-{submission}"


def feedback_id(grade: str, n: int) -> str:
    return f"FBK-{grade}-{_counter(n, 2)}"


def resubmission_id(submission: str, n: int = 1) -> str:
    return f"RSB-{submission}-{_counter(n, 2)}"


def appeal_id(n: int) -> str:                                 # APP-2026-000001 (given)
    return f"APP-{YEAR}-{_counter(n, 6)}"


def event_id(n: int) -> str:
    return f"EVT-{YEAR}-{_counter(n, 6)}"


# ---- patterns, reused later by the validator --------------------------------
_ASN = rf"ASN-{YEAR}-\d{{6}}"
_LRN = r"LRN-\d{6}"
_SUB = rf"SUB-{_ASN}-{_LRN}-\d{{2}}"

ID_PATTERNS = {
    "course_id": re.compile(rf"^CRS-{YEAR}-\d{{4}}$"),
    "learner_id": re.compile(rf"^{_LRN}$"),
    "enrollment_id": re.compile(rf"^ENR-CRS-{YEAR}-\d{{4}}-{_LRN}$"),
    "assignment_id": re.compile(rf"^{_ASN}$"),
    "rubric_id": re.compile(rf"^RUB-{_ASN}-\d{{2}}$"),
    "criterion_id": re.compile(rf"^RUB-{_ASN}-\d{{2}}-C\d{{2}}$"),
    "submission_id": re.compile(rf"^{_SUB}$"),
    "grade_id": re.compile(rf"^GRD-{_SUB}$"),
    "appeal_id": re.compile(rf"^APP-{YEAR}-\d{{6}}$"),
    "event_id": re.compile(rf"^EVT-{YEAR}-\d{{6}}$"),
}


if __name__ == "__main__":
    # Quick self-test: run `python generator/ids.py` from the project folder.
    crs, lrn, asn = course_id(1), learner_id(42), assignment_id(1)
    rub = rubric_id(asn)
    sub = submission_id(asn, lrn)
    examples = {
        "course_id": crs,
        "learner_id": lrn,
        "enrollment_id": enrollment_id(crs, lrn),
        "assignment_id": asn,
        "rubric_id": rub,
        "criterion_id": criterion_id(rub, 1),
        "submission_id": sub,
        "grade_id": grade_id(sub),
        "appeal_id": appeal_id(1),
        "event_id": event_id(1),
    }
    for name, value in examples.items():
        assert ID_PATTERNS[name].match(value), f"{name} does not match its pattern: {value}"
        print(f"{name:14} {value}")
    print("ids OK")