"""Validator for the generated dataset.

It reads ONLY the CSV tables (never the generator's code or hidden values) and checks:
  keys        primary-key uniqueness, ID formats, child IDs that embed parent IDs
  joins       every foreign key points to an existing parent
  values      allowed enum values, UTC timestamp format, due-time logic in India time
  dates       ordering of dates and timestamps across related records
  arithmetic  rubric totals, grade totals, late-penalty rule, derived values
  lifecycle   status transitions, event history chain, resubmission and appeal policy
  duplicates  duplicate natural keys

Four checks also LABEL what they find with an issue_type (the four required anomalies):
  unenrolled_submission, grade_exceeds_max, double_late_penalty, appeal_without_audit

Only AFTER detection finishes is ground_truth.csv read, to score the validator
(precision / recall per anomaly type) and to confirm that nothing else was flagged.

Usage (from the project folder):
    python validator/validate.py --dataset outputs/starter_baseline
    python validator/validate.py --dataset outputs/starter
"""
import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TABLES = [
    "course", "learner", "enrollment", "assignment", "rubric", "rubric_criterion",
    "submission", "resubmission", "submission_artifact", "grade", "grade_criterion_score",
    "feedback", "appeal", "grade_event",
]
PK = {
    "course": ("course_id",), "learner": ("learner_id",), "enrollment": ("enrollment_id",),
    "assignment": ("assignment_id",), "rubric": ("rubric_id",), "rubric_criterion": ("criterion_id",),
    "submission": ("submission_id",), "resubmission": ("resubmission_id",),
    "submission_artifact": ("artifact_id",), "grade": ("grade_id",),
    "grade_criterion_score": ("grade_id", "criterion_id"), "feedback": ("feedback_id",),
    "appeal": ("appeal_id",), "grade_event": ("event_id",),
}

# ---- policy constants: these must match Design.md section 3 ----------------------
PENALTY_PCT_PER_DAY = 10
PENALTY_CAP_PCT = 50
RESUBMISSION_THRESHOLD_PCT = 60
RESUBMISSION_WINDOW_DAYS = 7
RESUBMISSION_CAP_PCT = 80
APPEAL_WINDOW_DAYS = 7
DUE_LOCAL = (23, 59)       # due time in India time
TOL = 0.011                # tolerance for scores rounded to 2 decimals

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
IST = timezone(timedelta(hours=5, minutes=30))

_ASN, _LRN = r"ASN-2026-\d{6}", r"LRN-\d{6}"
_SUB = rf"SUB-{_ASN}-{_LRN}-\d{{2}}"
ID_PATTERNS = {
    ("course", "course_id"): r"CRS-2026-\d{4}",
    ("learner", "learner_id"): _LRN,
    ("enrollment", "enrollment_id"): rf"ENR-CRS-2026-\d{{4}}-{_LRN}",
    ("assignment", "assignment_id"): _ASN,
    ("rubric", "rubric_id"): rf"RUB-{_ASN}-\d{{2}}",
    ("rubric_criterion", "criterion_id"): rf"RUB-{_ASN}-\d{{2}}-C\d{{2}}",
    ("submission", "submission_id"): _SUB,
    ("resubmission", "resubmission_id"): rf"RSB-{_SUB}-\d{{2}}",
    ("submission_artifact", "artifact_id"): rf"ART-{_SUB}-\d{{2}}",
    ("grade", "grade_id"): rf"GRD-{_SUB}",
    ("feedback", "feedback_id"): rf"FBK-GRD-{_SUB}-\d{{2}}",
    ("appeal", "appeal_id"): r"APP-2026-\d{6}",
    ("grade_event", "event_id"): r"EVT-2026-\d{6}",
}
ID_PATTERNS = {k: re.compile(f"^{v}$") for k, v in ID_PATTERNS.items()}

FOREIGN_KEYS = [  # (table, column, parent table, parent column, may be empty)
    ("enrollment", "course_id", "course", "course_id", False),
    ("enrollment", "learner_id", "learner", "learner_id", False),
    ("assignment", "course_id", "course", "course_id", False),
    ("rubric", "assignment_id", "assignment", "assignment_id", False),
    ("rubric_criterion", "rubric_id", "rubric", "rubric_id", False),
    ("submission", "assignment_id", "assignment", "assignment_id", False),
    ("submission", "learner_id", "learner", "learner_id", False),
    ("resubmission", "submission_id", "submission", "submission_id", False),
    ("submission_artifact", "submission_id", "submission", "submission_id", False),
    ("submission_artifact", "resubmission_id", "resubmission", "resubmission_id", True),
    ("grade", "submission_id", "submission", "submission_id", False),
    ("grade_criterion_score", "grade_id", "grade", "grade_id", False),
    ("grade_criterion_score", "criterion_id", "rubric_criterion", "criterion_id", False),
    ("feedback", "grade_id", "grade", "grade_id", False),
    ("feedback", "criterion_id", "rubric_criterion", "criterion_id", True),
    ("appeal", "submission_id", "submission", "submission_id", False),
    ("appeal", "grade_id", "grade", "grade_id", False),
    ("grade_event", "grade_id", "grade", "grade_id", False),
    ("grade_event", "appeal_id", "appeal", "appeal_id", True),
    ("grade_event", "resubmission_id", "resubmission", "resubmission_id", True),
]

ENUMS = {
    ("course", "status"): {"planned", "active", "completed"},
    ("learner", "status"): {"active", "inactive"},
    ("enrollment", "status"): {"active", "dropped", "completed"},
    ("assignment", "status"): {"draft", "published", "closed"},
    ("assignment", "resubmission_allowed"): {"0", "1"},
    ("submission", "status"): {"submitted", "graded", "resubmitted", "finalized"},
    ("submission", "is_late"): {"0", "1"},
    ("resubmission", "status"): {"requested", "submitted", "graded", "cancelled"},
    ("submission_artifact", "file_status"): {"present", "missing", "corrupt"},
    ("submission_artifact", "file_type"): {"pdf", "zip", "py", "ipynb", "txt"},
    ("grade", "status"): {"released", "revised", "final"},
    ("appeal", "status"): {"filed", "under_review", "upheld", "rejected"},
    ("appeal", "reason_category"): {"rubric_misapplied", "calculation_error", "late_penalty_dispute", "other"},
    ("grade_event", "event_type"): {"initial_grade", "resubmission_regrade", "appeal_adjustment"},
    ("grade_event", "actor_role"): {"instructor", "academic_admin", "support_staff", "platform_admin"},
}

# name, group, description
CHECKS = [
    ("pk_unique", "keys", "Primary keys are unique in every table"),
    ("id_format", "keys", "IDs follow the required zero-padded formats"),
    ("id_embeds_parent", "keys", "Child IDs embed their parent IDs exactly"),
    ("fk_valid", "joins", "Every foreign key points to an existing parent row"),
    ("enum_valid", "values", "Status and type columns hold allowed values only"),
    ("timestamp_format", "values", "All *_utc columns are ISO-8601 UTC ending in Z"),
    ("due_time_timezone", "values", "Due time is 23:59 India time and the zone is recorded"),
    ("course_dates", "dates", "Course start is not after its end"),
    ("assignment_dates", "dates", "Publish precedes due date, both inside the course dates"),
    ("rubric_effective", "dates", "Rubric is effective no later than publication"),
    ("enrollment_dates", "dates", "Enrollment dates and status are consistent"),
    ("submission_after_publish", "dates", "A submission is not made before publication"),
    ("is_late_consistent", "dates", "is_late and hours_late agree with the timestamps"),
    ("grade_after_submission", "dates", "A grade is released after the submission"),
    ("artifact_time", "dates", "Artifact upload time equals the (re)submission time"),
    ("feedback_after_grade", "dates", "Feedback is created at or after grading"),
    ("event_times", "dates", "Initial event matches grading time; later events come after it"),
    ("resubmission_dates", "dates", "Resubmission requested within 7 days of grade release, in order"),
    ("appeal_dates", "dates", "Appeal filed within 7 days of grade release, decided after filing"),
    ("rubric_total", "arithmetic", "Criterion maxima add up to the rubric total and assignment maximum"),
    ("grade_scores_complete", "arithmetic", "A grade has one score for each criterion of its rubric"),
    ("criterion_score_nonnegative", "arithmetic", "Criterion scores are not negative"),
    ("grade_raw_total", "arithmetic", "raw_total equals the sum of criterion scores"),
    ("late_penalty_pct_rule", "arithmetic", "Penalty % follows the late rule, computed from timestamps"),
    ("late_penalty_points_rule", "arithmetic", "Penalty points equal raw_total x penalty % (applied once)"),
    ("grade_final", "arithmetic", "final_score equals raw_total minus penalty points"),
    ("grade_within_rubric_max", "arithmetic", "No score exceeds its criterion maximum or the assignment maximum"),
    ("resubmission_cap", "arithmetic", "Resubmission-improved criterion scores respect the 80% cap"),
    ("submission_learner_enrolled", "lifecycle", "The submitting learner is enrolled in the course at that time"),
    ("submission_status_vs_grade", "lifecycle", "Submission status matches whether it has a grade"),
    ("grade_status_vs_submission", "lifecycle", "Final / revised grade statuses match the history"),
    ("event_chain", "lifecycle", "Grade events chain together and end at the current grade"),
    ("event_links", "lifecycle", "Events reference the right appeal or resubmission"),
    ("one_route", "lifecycle", "At most one resubmission or appeal, never both"),
    ("resubmission_policy", "lifecycle", "Resubmission only when allowed and the score was below 60%"),
    ("resubmission_status", "lifecycle", "Resubmission status matches its dates, files and regrade event"),
    ("appeal_status", "lifecycle", "Appeal status matches its decision fields"),
    ("appeal_audit_trail", "lifecycle", "An upheld appeal has exactly one matching audit event"),
    ("no_duplicate_natural_keys", "duplicates", "No duplicate enrollments, submissions, rubrics, emails or files"),
]


# ------------------------------------------------------------------ small helpers
def ts(s):
    if not s or not TS_RE.match(s):
        return None
    return datetime.strptime(s, TS_FORMAT).replace(tzinfo=timezone.utc)


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def ist_date(dt):
    return dt.astimezone(IST).date()


def late_seconds(submitted, due):
    return max(0, int((submitted - due).total_seconds()))


def penalty_pct(secs):
    if secs <= 0:
        return 0.0
    return float(min(PENALTY_CAP_PCT, PENALTY_PCT_PER_DAY * (-(-secs // 86400))))


class Report:
    def __init__(self):
        self.checks = {name: {"group": g, "description": d, "checked": 0, "failed": 0} for name, g, d in CHECKS}
        self.findings = []

    def check(self, name, ok, table="", rid="", msg="", sub=None, issue=None):
        c = self.checks[name]
        c["checked"] += 1
        if not ok:
            c["failed"] += 1
            self.findings.append({"check": name, "table": table, "record_id": rid,
                                  "submission_id": sub, "issue_type": issue, "message": msg})
        return ok


def load_dataset(folder):
    data = {}
    for t in TABLES:
        path = Path(folder) / "csv" / f"{t}.csv"
        if not path.exists():
            raise SystemExit(f"Missing file: {path}")
        with open(path, encoding="utf-8", newline="") as f:
            data[t] = list(csv.DictReader(f))
    return data


# ------------------------------------------------------------------ the checks
def run_checks(D, R):
    courses = {r["course_id"]: r for r in D["course"]}
    learners = {r["learner_id"]: r for r in D["learner"]}
    assignments = {r["assignment_id"]: r for r in D["assignment"]}
    rubrics = {r["rubric_id"]: r for r in D["rubric"]}
    rubric_by_asn = defaultdict(list)
    for r in D["rubric"]:
        rubric_by_asn[r["assignment_id"]].append(r)
    criteria = {r["criterion_id"]: r for r in D["rubric_criterion"]}
    criteria_by_rubric = defaultdict(list)
    for r in D["rubric_criterion"]:
        criteria_by_rubric[r["rubric_id"]].append(r)
    subs = {r["submission_id"]: r for r in D["submission"]}
    grades = {r["grade_id"]: r for r in D["grade"]}
    grade_by_sub = defaultdict(list)
    for r in D["grade"]:
        grade_by_sub[r["submission_id"]].append(r)
    scores_by_grade = defaultdict(list)
    for r in D["grade_criterion_score"]:
        scores_by_grade[r["grade_id"]].append(r)
    events_by_grade = defaultdict(list)
    for r in D["grade_event"]:
        events_by_grade[r["grade_id"]].append(r)
    for evs in events_by_grade.values():
        evs.sort(key=lambda e: (e["event_at_utc"], e["event_id"]))
    resubs_by_sub, appeals_by_sub = defaultdict(list), defaultdict(list)
    for r in D["resubmission"]:
        resubs_by_sub[r["submission_id"]].append(r)
    for r in D["appeal"]:
        appeals_by_sub[r["submission_id"]].append(r)
    resubs = {r["resubmission_id"]: r for r in D["resubmission"]}
    artifacts_by_sub = defaultdict(list)
    for r in D["submission_artifact"]:
        artifacts_by_sub[r["submission_id"]].append(r)
    enrol = {(r["course_id"], r["learner_id"]): r for r in D["enrollment"]}
    tables_by_name = {t: D[t] for t in TABLES}

    def sub_of_grade(gid):
        g = grades.get(gid)
        return g["submission_id"] if g else None

    # ============================================================ keys
    for t in TABLES:
        counts = Counter(tuple(r[k] for k in PK[t]) for r in D[t])
        for r in D[t]:
            key = tuple(r[k] for k in PK[t])
            R.check("pk_unique", counts[key] == 1, t, "|".join(key), "duplicate primary key")

    for (t, col), pat in ID_PATTERNS.items():
        for r in D[t]:
            R.check("id_format", bool(pat.match(r[col])), t, r[col], f"{col} does not match the required format")

    for r in D["enrollment"]:
        R.check("id_embeds_parent", r["enrollment_id"] == f"ENR-{r['course_id']}-{r['learner_id']}",
                "enrollment", r["enrollment_id"], "ID does not match its course and learner")
    for r in D["rubric"]:
        rno = num(r["rubric_no"])
        R.check("id_embeds_parent", rno is not None and r["rubric_id"] == f"RUB-{r['assignment_id']}-{int(rno):02d}",
                "rubric", r["rubric_id"], "ID does not match its assignment")
    for r in D["rubric_criterion"]:
        cno = num(r["criterion_no"])
        R.check("id_embeds_parent", cno is not None and r["criterion_id"] == f"{r['rubric_id']}-C{int(cno):02d}",
                "rubric_criterion", r["criterion_id"], "ID does not match its rubric")
    for r in D["submission"]:
        ano = num(r["attempt_no"])
        R.check("id_embeds_parent",
                ano is not None and r["submission_id"] == f"SUB-{r['assignment_id']}-{r['learner_id']}-{int(ano):02d}",
                "submission", r["submission_id"], "ID does not match its assignment and learner", sub=r["submission_id"])
    for r in D["grade"]:
        R.check("id_embeds_parent", r["grade_id"] == "GRD-" + r["submission_id"], "grade", r["grade_id"],
                "ID does not match its submission", sub=r["submission_id"])
    for r in D["submission_artifact"]:
        R.check("id_embeds_parent", r["artifact_id"].startswith(f"ART-{r['submission_id']}-"),
                "submission_artifact", r["artifact_id"], "ID does not match its submission", sub=r["submission_id"])
    for r in D["feedback"]:
        R.check("id_embeds_parent", r["feedback_id"].startswith(f"FBK-{r['grade_id']}-"),
                "feedback", r["feedback_id"], "ID does not match its grade", sub=sub_of_grade(r["grade_id"]))
    for r in D["resubmission"]:
        R.check("id_embeds_parent", r["resubmission_id"].startswith(f"RSB-{r['submission_id']}-"),
                "resubmission", r["resubmission_id"], "ID does not match its submission", sub=r["submission_id"])

    # ============================================================ joins
    key_sets = {t: {r[PK[t][0]] for r in D[t]} for t in TABLES if len(PK[t]) == 1}
    for t, col, parent, pcol, optional in FOREIGN_KEYS:
        valid = key_sets[parent]
        for r in D[t]:
            v = r[col]
            if optional and v == "":
                continue
            sub = r.get("submission_id") or (sub_of_grade(r.get("grade_id")) if "grade_id" in r else None)
            R.check("fk_valid", v in valid, t, "|".join(r[k] for k in PK[t]),
                    f"{col}={v!r} has no matching {parent}", sub=sub)

    # ============================================================ values
    for (t, col), allowed in ENUMS.items():
        for r in D[t]:
            R.check("enum_valid", r[col] in allowed, t, "|".join(r[k] for k in PK[t]),
                    f"{col}={r[col]!r} is not an allowed value")
    for t in TABLES:
        cols = [c for c in (D[t][0].keys() if D[t] else []) if c.endswith("_utc")]
        for r in D[t]:
            for c in cols:
                if r[c] != "":
                    R.check("timestamp_format", bool(TS_RE.match(r[c])), t, "|".join(r[k] for k in PK[t]),
                            f"{c}={r[c]!r} is not a UTC timestamp")
    for a in D["assignment"]:
        due = ts(a["due_at_utc"])
        local_ok = due is not None and (due.astimezone(IST).hour, due.astimezone(IST).minute, due.astimezone(IST).second) == (*DUE_LOCAL, 0)
        R.check("due_time_timezone", local_ok and a["due_timezone"] == "Asia/Kolkata", "assignment",
                a["assignment_id"], "due time is not 23:59 India time or the timezone is missing")

    # ============================================================ dates
    for c in D["course"]:
        R.check("course_dates", c["start_date"] <= c["end_date"], "course", c["course_id"], "start is after end")
    for a in D["assignment"]:
        pub, due, c = ts(a["published_at_utc"]), ts(a["due_at_utc"]), courses.get(a["course_id"])
        ok = pub is not None and due is not None and pub < due
        if ok and c:
            ok = c["start_date"] <= ist_date(pub).isoformat() and ist_date(due).isoformat() <= c["end_date"]
        R.check("assignment_dates", ok, "assignment", a["assignment_id"], "publish/due dates are out of order or outside the course")
    for r in D["rubric"]:
        a = assignments.get(r["assignment_id"])
        eff, pub = ts(r["effective_from_utc"]), ts(a["published_at_utc"]) if a else None
        R.check("rubric_effective", eff is not None and pub is not None and eff <= pub, "rubric", r["rubric_id"],
                "rubric becomes effective after the assignment is published")
    for e in D["enrollment"]:
        c = courses.get(e["course_id"])
        ok = c is not None and c["start_date"] <= e["enrolled_from"] <= c["end_date"]
        if e["enrolled_to"]:
            ok = ok and e["enrolled_to"] >= e["enrolled_from"]
        ok = ok and ((e["status"] == "active") == (e["enrolled_to"] == ""))
        R.check("enrollment_dates", ok, "enrollment", e["enrollment_id"], "enrollment dates or status are inconsistent")

    for s in D["submission"]:
        sid = s["submission_id"]
        a = assignments.get(s["assignment_id"])
        sub_t = ts(s["submitted_at_utc"])
        pub = ts(a["published_at_utc"]) if a else None
        due = ts(a["due_at_utc"]) if a else None
        R.check("submission_after_publish", sub_t is not None and pub is not None and sub_t >= pub,
                "submission", sid, "submitted before the assignment was published", sub=sid)
        if sub_t and due:
            secs = late_seconds(sub_t, due)
            hrs = num(s["hours_late"])
            ok = s["is_late"] == ("1" if sub_t > due else "0") and hrs is not None and abs(hrs - secs / 3600) <= 0.0001
            R.check("is_late_consistent", ok, "submission", sid, "is_late or hours_late disagrees with the timestamps", sub=sid)
        else:
            R.check("is_late_consistent", False, "submission", sid, "missing timestamps", sub=sid)
        for g in grade_by_sub.get(sid, []):
            gt = ts(g["graded_at_utc"])
            R.check("grade_after_submission", gt is not None and sub_t is not None and gt > sub_t,
                    "grade", g["grade_id"], "graded before the submission was made", sub=sid)

    for r in D["submission_artifact"]:
        sid = r["submission_id"]
        if r["resubmission_id"]:
            rs = resubs.get(r["resubmission_id"])
            expected = ts(rs["submitted_at_utc"]) if rs else None
        else:
            expected = ts(subs[sid]["submitted_at_utc"]) if sid in subs else None
        R.check("artifact_time", expected is not None and ts(r["uploaded_at_utc"]) == expected,
                "submission_artifact", r["artifact_id"], "upload time differs from the submission time", sub=sid)
    for f in D["feedback"]:
        g = grades.get(f["grade_id"])
        ft, gt = ts(f["created_at_utc"]), ts(g["graded_at_utc"]) if g else None
        R.check("feedback_after_grade", ft is not None and gt is not None and ft >= gt, "feedback",
                f["feedback_id"], "feedback is older than the grade", sub=sub_of_grade(f["grade_id"]))
    for gid, evs in events_by_grade.items():
        g = grades.get(gid)
        gt = ts(g["graded_at_utc"]) if g else None
        first = ts(evs[0]["event_at_utc"])
        R.check("event_times", gt is not None and first == gt and all(ts(e["event_at_utc"]) > first for e in evs[1:]),
                "grade_event", gid, "event times are out of order", sub=sub_of_grade(gid))
    for r in D["resubmission"]:
        sid = r["submission_id"]
        g = (grade_by_sub.get(sid) or [None])[0]
        gt, req, sub_at = (ts(g["graded_at_utc"]) if g else None), ts(r["requested_at_utc"]), ts(r["submitted_at_utc"])
        ok = gt is not None and req is not None and timedelta(0) < req - gt <= timedelta(days=RESUBMISSION_WINDOW_DAYS)
        if r["submitted_at_utc"]:
            ok = ok and sub_at is not None and req is not None and sub_at >= req
        R.check("resubmission_dates", ok, "resubmission", r["resubmission_id"], "request outside the 7-day window or out of order", sub=sid)
    for x in D["appeal"]:
        g = grades.get(x["grade_id"])
        gt, filed, dec = (ts(g["graded_at_utc"]) if g else None), ts(x["filed_at_utc"]), ts(x["decided_at_utc"])
        ok = gt is not None and filed is not None and timedelta(0) < filed - gt <= timedelta(days=APPEAL_WINDOW_DAYS)
        if x["decided_at_utc"]:
            ok = ok and dec is not None and dec >= filed
        R.check("appeal_dates", ok, "appeal", x["appeal_id"], "filing outside the 7-day window or decision before filing", sub=x["submission_id"])

    # ============================================================ arithmetic
    for rb in D["rubric"]:
        a = assignments.get(rb["assignment_id"])
        total = sum(num(c["max_points"]) or 0 for c in criteria_by_rubric.get(rb["rubric_id"], []))
        ok = a is not None and abs(total - (num(rb["total_max_points"]) or -1)) < TOL and abs(total - (num(a["max_score"]) or -1)) < TOL
        R.check("rubric_total", ok, "rubric", rb["rubric_id"], "criterion maxima do not add up to the rubric/assignment total")

    for g in D["grade"]:
        gid, sid = g["grade_id"], g["submission_id"]
        s = subs.get(sid)
        a = assignments.get(s["assignment_id"]) if s else None
        rows = scores_by_grade.get(gid, [])
        rub = (rubric_by_asn.get(a["assignment_id"]) or [None])[0] if a else None
        crit_ids = {c["criterion_id"] for c in criteria_by_rubric.get(rub["rubric_id"], [])} if rub else set()
        got = [r["criterion_id"] for r in rows]
        R.check("grade_scores_complete", sorted(got) == sorted(crit_ids) and len(got) == len(set(got)), "grade", gid,
                "scores do not cover exactly the criteria of the rubric", sub=sid)

        raw, pts, final = num(g["raw_total"]), num(g["late_penalty_points"]), num(g["final_score"])
        pct = num(g["late_penalty_pct"])
        vals = [num(r["score"]) for r in rows]
        R.check("criterion_score_nonnegative", all(v is not None and v >= 0 for v in vals), "grade", gid,
                "a criterion score is negative", sub=sid)
        R.check("grade_raw_total", raw is not None and abs(sum(v or 0 for v in vals) - raw) < TOL, "grade", gid,
                "raw_total differs from the sum of criterion scores", sub=sid)

        if s and a and raw is not None:
            secs = late_seconds(ts(s["submitted_at_utc"]), ts(a["due_at_utc"])) if ts(s["submitted_at_utc"]) and ts(a["due_at_utc"]) else 0
            exp_pct = penalty_pct(secs)
            exp_pts = round(raw * exp_pct / 100, 2)
            R.check("late_penalty_pct_rule", pct is not None and pct == exp_pct, "grade", gid,
                    f"penalty % is {g['late_penalty_pct']} but the rule gives {exp_pct:g}", sub=sid)
            if pts is None or abs(pts - exp_pts) >= TOL:
                twice = pts is not None and exp_pts > 0 and abs(pts - 2 * exp_pts) <= 0.02
                R.check("late_penalty_points_rule", False, "grade", gid,
                        f"penalty points are {g['late_penalty_points']} but the rule gives {exp_pts:g}"
                        + (" (twice the expected value: penalty applied twice)" if twice else ""),
                        sub=sid, issue="double_late_penalty" if twice else None)
            else:
                R.check("late_penalty_points_rule", True, "grade", gid)
        if None not in (raw, pts, final):
            R.check("grade_final", abs(final - (raw - pts)) < TOL, "grade", gid, "final_score is not raw_total minus penalty", sub=sid)

        if a and None not in (raw, final):
            problems = []
            for r in rows:
                c, v = criteria.get(r["criterion_id"]), num(r["score"])
                if c and v is not None and v > num(c["max_points"]) + 1e-9:
                    problems.append(f"{r['criterion_id']} score {v:g} > max {num(c['max_points']):g}")
            mx = num(a["max_score"])
            if raw > mx + 1e-9:
                problems.append(f"raw_total {raw:g} > assignment max {mx:g}")
            if final > mx + 1e-9:
                problems.append(f"final_score {final:g} > assignment max {mx:g}")
            if final < -1e-9:
                problems.append("final_score is negative")
            R.check("grade_within_rubric_max", not problems, "grade", gid, "; ".join(problems), sub=sid,
                    issue="grade_exceeds_max" if problems and not (len(problems) == 1 and problems[0].endswith("negative")) else None)

        evs = events_by_grade.get(gid, [])
        improved_by_resub = any(e["event_type"] == "resubmission_regrade" and (num(e["new_score"]) or 0) > (num(e["old_score"]) or 0) for e in evs)
        if improved_by_resub:
            ok = all((num(r["score"]) or 0) <= RESUBMISSION_CAP_PCT / 100 * num(criteria[r["criterion_id"]]["max_points"]) + 1e-9
                     for r in rows if r["criterion_id"] in criteria)
            R.check("resubmission_cap", ok, "grade", gid, "a regraded criterion score exceeds 80% of its maximum", sub=sid)

    # ============================================================ lifecycle
    for s in D["submission"]:
        sid = s["submission_id"]
        a = assignments.get(s["assignment_id"])
        e = enrol.get((a["course_id"], s["learner_id"])) if a else None
        t = ts(s["submitted_at_utc"])
        if e is None:
            R.check("submission_learner_enrolled", False, "submission", sid,
                    f"learner {s['learner_id']} has no enrollment in {a['course_id'] if a else '?'}", sub=sid, issue="unenrolled_submission")
        else:
            start = datetime.fromisoformat(e["enrolled_from"]).replace(tzinfo=IST)
            end = (datetime.fromisoformat(e["enrolled_to"]).replace(tzinfo=IST) + timedelta(days=1)) if e["enrolled_to"] else None
            ok = t is not None and t >= start and (end is None or t < end)
            R.check("submission_learner_enrolled", ok, "submission", sid,
                    "submission was made outside the learner's enrollment dates", sub=sid, issue="unenrolled_submission")

        has_grade = bool(grade_by_sub.get(sid))
        sts = s["status"]
        ok = (sts == "submitted") if not has_grade else (sts in ("graded", "resubmitted", "finalized"))
        if has_grade and sts == "resubmitted":
            ok = any(r["status"] == "submitted" for r in resubs_by_sub.get(sid, []))
        R.check("submission_status_vs_grade", ok, "submission", sid, f"status {sts!r} does not fit a submission {'with' if has_grade else 'without'} a grade", sub=sid)

        if has_grade:
            g = grade_by_sub[sid][0]
            R.check("grade_status_vs_submission", (g["status"] == "final") == (sts == "finalized"), "grade", g["grade_id"],
                    "grade 'final' and submission 'finalized' do not go together", sub=sid)
            if g["status"] == "revised":
                evs = events_by_grade.get(g["grade_id"], [])
                R.check("grade_status_vs_submission", any((num(e["new_score"]) or 0) > (num(e["old_score"]) or 0) for e in evs[1:]),
                        "grade", g["grade_id"], "grade is 'revised' but no history shows a change", sub=sid)

        nr, na = len(resubs_by_sub.get(sid, [])), len(appeals_by_sub.get(sid, []))
        R.check("one_route", nr <= 1 and na <= 1 and not (nr and na), "submission", sid,
                f"{nr} resubmission(s) and {na} appeal(s)", sub=sid)

    for gid, g in grades.items():
        evs, sid = events_by_grade.get(gid, []), g["submission_id"]
        ok = bool(evs) and evs[0]["event_type"] == "initial_grade" and evs[0]["old_score"] == ""
        msg = "history does not start with an initial_grade event"
        if ok:
            for prev, cur in zip(evs, evs[1:]):
                if num(cur["old_score"]) != num(prev["new_score"]) or (num(cur["new_score"]) or 0) < (num(cur["old_score"]) or 0):
                    ok, msg = False, "event chain is broken or a score went down"
                    break
        if ok:
            last, current = num(evs[-1]["new_score"]), num(g["final_score"])
            if last is None or current is None or abs(last - current) >= TOL:
                ok, msg = False, f"latest event says {evs[-1]['new_score']} but the grade is {g['final_score']}: grade changed without history"
        R.check("event_chain", ok, "grade", gid, msg, sub=sid)

    for e in D["grade_event"]:
        t, a_id, r_id = e["event_type"], e["appeal_id"], e["resubmission_id"]
        ok = (t == "initial_grade" and not a_id and not r_id) or (t == "appeal_adjustment" and a_id and not r_id) \
            or (t == "resubmission_regrade" and r_id and not a_id)
        R.check("event_links", bool(ok), "grade_event", e["event_id"], f"{t} has the wrong appeal/resubmission link", sub=sub_of_grade(e["grade_id"]))

    for r in D["resubmission"]:
        sid, rid = r["submission_id"], r["resubmission_id"]
        s = subs.get(sid)
        a = assignments.get(s["assignment_id"]) if s else None
        g = (grade_by_sub.get(sid) or [None])[0]
        evs = events_by_grade.get(g["grade_id"], []) if g else []
        first = num(evs[0]["new_score"]) if evs else None
        ok = bool(a) and a["resubmission_allowed"] == "1" and first is not None and first < RESUBMISSION_THRESHOLD_PCT / 100 * num(a["max_score"])
        R.check("resubmission_policy", ok, "resubmission", rid, "resubmission not allowed or the original score was not below 60%", sub=sid)

        arts = [x for x in artifacts_by_sub.get(sid, []) if x["resubmission_id"] == rid]
        regrade = [e for e in evs if e["resubmission_id"] == rid]
        st, has_sub = r["status"], r["submitted_at_utc"] != ""
        ok = (st in ("requested", "cancelled") and not has_sub and not arts and not regrade) or \
             (st == "submitted" and has_sub and arts and not regrade) or \
             (st == "graded" and has_sub and arts and len(regrade) == 1)
        R.check("resubmission_status", bool(ok), "resubmission", rid, f"status {st!r} does not match its dates, files and regrade event", sub=sid)

    for x in D["appeal"]:
        sid, aid = x["submission_id"], x["appeal_id"]
        g = grades.get(x["grade_id"])
        R.check("appeal_status", g is not None and g["submission_id"] == sid, "appeal", aid,
                "appeal's grade belongs to a different submission", sub=sid)
        st = x["status"]
        orig, rev = num(x["original_score"]), num(x["revised_score"])
        decided = x["decided_at_utc"] != ""
        ok = (st in ("filed", "under_review") and not decided and rev is None) or \
             (st == "rejected" and decided and rev is None) or \
             (st == "upheld" and decided and rev is not None and orig is not None and rev > orig)
        R.check("appeal_status", bool(ok), "appeal", aid, f"status {st!r} does not match its decision fields", sub=sid)

        evs = events_by_grade.get(x["grade_id"], [])
        linked = [e for e in evs if e["appeal_id"] == aid]
        if st == "upheld":
            match = len(linked) == 1 and num(linked[0]["old_score"]) == orig and num(linked[0]["new_score"]) == rev
            R.check("appeal_audit_trail", match, "appeal", aid,
                    "appeal upheld and the grade changed, but there is no matching appeal_adjustment event",
                    sub=sid, issue="appeal_without_audit")
        else:
            R.check("appeal_audit_trail", not linked, "appeal", aid, "a non-upheld appeal has an adjustment event", sub=sid)

    # ============================================================ duplicates
    def dup(table, keys, label):
        counts = Counter(tuple(r[k] for k in keys) for r in D[table])
        for r in D[table]:
            key = tuple(r[k] for k in keys)
            R.check("no_duplicate_natural_keys", counts[key] == 1, table, "|".join(r[k] for k in PK[table]),
                    f"duplicate {label}: {key}", sub=r.get("submission_id"))

    dup("enrollment", ("course_id", "learner_id"), "enrollment")
    dup("submission", ("assignment_id", "learner_id"), "submission")
    dup("rubric", ("assignment_id", "rubric_no"), "rubric")
    dup("rubric_criterion", ("rubric_id", "criterion_no"), "criterion")
    dup("learner", ("email",), "email")
    dup("course", ("course_code",), "course code")
    dup("submission_artifact", ("submission_id", "file_name"), "file name")
    dup("grade", ("submission_id",), "grade")


# ------------------------------------------------------------------ scoring against ground truth
def score(R, D, truth_path):
    with open(truth_path, encoding="utf-8", newline="") as f:
        truth = list(csv.DictReader(f))
    grades = {g["grade_id"]: g["submission_id"] for g in D["grade"]}
    appeals = {a["appeal_id"]: a["submission_id"] for a in D["appeal"]}
    truth_subs = set()
    for t in truth:
        if t["record_table"] == "submission":
            truth_subs.add(t["record_id"])
        elif t["record_table"] == "grade":
            truth_subs.add(grades.get(t["record_id"]))
        elif t["record_table"] == "appeal":
            truth_subs.add(appeals.get(t["record_id"]))

    truth_pairs = {(t["issue_type"], t["record_id"]) for t in truth}
    found_pairs = {(f["issue_type"], f["record_id"]) for f in R.findings if f["issue_type"]}
    per_type = {}
    for issue in sorted({t["issue_type"] for t in truth} | {p[0] for p in found_pairs}):
        tp = len({p for p in truth_pairs if p[0] == issue} & found_pairs)
        expected = len({p for p in truth_pairs if p[0] == issue})
        flagged = len({p for p in found_pairs if p[0] == issue})
        per_type[issue] = {"expected": expected, "flagged": flagged, "true_positives": tp,
                           "false_positives": flagged - tp, "false_negatives": expected - tp,
                           "precision": round(tp / flagged, 3) if flagged else None,
                           "recall": round(tp / expected, 3) if expected else None}
    unexpected = [f for f in R.findings if f["submission_id"] not in truth_subs]
    return {"ground_truth_rows": len(truth), "per_type": per_type, "unexpected_findings": unexpected}


# ------------------------------------------------------------------ report output
def write_reports(report_dir, name, folder, D, R, scoring):
    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks = [{"check": n, **v, "status": "PASS" if v["failed"] == 0 else "FAIL"} for n, v in R.checks.items()]
    summary = {
        "dataset": str(folder), "row_counts": {t: len(D[t]) for t in TABLES},
        "checks_run": len(checks), "checks_failed": sum(1 for c in checks if c["status"] == "FAIL"),
        "assertions_evaluated": sum(c["checked"] for c in checks), "findings": len(R.findings),
    }
    payload = {"summary": summary, "checks": checks, "scoring": scoring, "findings": R.findings[:5000]}
    with open(out / f"validation_{name}.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    lines = [f"# Validation report: {name}", "",
             f"- Dataset: `{folder}`",
             f"- Checks: {summary['checks_run']} run, {summary['checks_failed']} with findings",
             f"- Assertions evaluated: {summary['assertions_evaluated']:,}",
             f"- Findings: {summary['findings']}", "",
             "## Checks", "", "| Group | Check | Evaluated | Failed | Status |", "|---|---|---:|---:|---|"]
    for c in checks:
        lines.append(f"| {c['group']} | {c['check']} | {c['checked']:,} | {c['failed']} | {c['status']} |")
    if scoring:
        lines += ["", "## Detection scored against ground truth", "",
                  "| Anomaly | Expected | Flagged | Correct | False positives | Missed | Precision | Recall |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for issue, m in scoring["per_type"].items():
            lines.append(f"| {issue} | {m['expected']} | {m['flagged']} | {m['true_positives']} | {m['false_positives']} | "
                         f"{m['false_negatives']} | {m['precision']} | {m['recall']} |")
        lines += ["", f"Unexpected findings (not on a labelled record): **{len(scoring['unexpected_findings'])}**"]
        for f in scoring["unexpected_findings"][:20]:
            lines.append(f"- `{f['check']}` {f['table']} {f['record_id']}: {f['message']}")
    elif R.findings:
        lines += ["", "## First findings", ""]
        for f in R.findings[:20]:
            lines.append(f"- `{f['check']}` {f['table']} {f['record_id']}: {f['message']}")
    with open(out / f"validation_{name}.md", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="Validate a generated dataset.")
    p.add_argument("--dataset", required=True, help="dataset folder (contains csv/)")
    p.add_argument("--ground-truth", help="ground_truth.csv (default: <dataset>/ground_truth.csv if present)")
    p.add_argument("--report-dir", default="reports")
    p.add_argument("--name", help="report name (default: dataset folder name)")
    args = p.parse_args(argv)

    folder = Path(args.dataset)
    name = args.name or folder.name
    D = load_dataset(folder)
    R = Report()
    run_checks(D, R)                      # detection never sees the ground truth

    truth_path = Path(args.ground_truth) if args.ground_truth else folder / "ground_truth.csv"
    scoring = score(R, D, truth_path) if truth_path.exists() else None   # only now is it read
    summary = write_reports(args.report_dir, name, folder, D, R, scoring)

    print(f"Validated {folder}: {summary['assertions_evaluated']:,} assertions, "
          f"{summary['checks_failed']} of {summary['checks_run']} checks with findings, {summary['findings']} findings")
    for c, v in R.checks.items():
        if v["failed"]:
            print(f"  FAIL {c}: {v['failed']} of {v['checked']}")
    if scoring:
        for issue, m in scoring["per_type"].items():
            print(f"  {issue:24} expected {m['expected']:>3}  flagged {m['flagged']:>3}  "
                  f"precision {m['precision']}  recall {m['recall']}")
        print(f"  unexpected findings (not on a labelled record): {len(scoring['unexpected_findings'])}")
        perfect = all(m["false_positives"] == 0 and m["false_negatives"] == 0 for m in scoring["per_type"].values()) \
            and not scoring["unexpected_findings"]
        print("RESULT:", "all injected anomalies found, nothing else flagged" if perfect else "MISMATCH, see the report")
        return 0 if perfect else 1
    print("RESULT:", "clean, no findings" if not R.findings else "findings present, see the report")
    return 0 if not R.findings else 1


if __name__ == "__main__":
    sys.exit(main())