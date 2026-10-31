"""Inject the four required anomalies into a CLEAN baseline and label every one.

The baseline is generated first and is fully valid. Anomalies are then added in a way
that touches only the labelled records, so nothing else is silently corrupted:

  unenrolled_submission  a NEW, otherwise valid submission (with file, grade, scores,
                         feedback, event) for a learner who is not enrolled in the course
  grade_exceeds_max      one criterion score is raised so the grade passes the rubric
                         maximum; the totals and the grade event are kept consistent
  double_late_penalty    the late-penalty points are deducted twice; the percentage is
                         unchanged, so the rule-based value no longer matches
  appeal_without_audit   the audit event (appeal_adjustment) of an UPHELD appeal is
                         removed, so the grade changed with no history row

The labels go to ground_truth (a separate file). The tables themselves never contain a
label column, so ground truth cannot leak into input features.
"""
import copy
import random
import sys
from collections import defaultdict
from datetime import timedelta
import hashlib

import config
import ids
from timeutil import parse_ts, to_ts
from transactions import OVERALL_BANDS

UNENROLLED = "unenrolled_submission"
EXCEEDS_MAX = "grade_exceeds_max"
DOUBLE_PENALTY = "double_late_penalty"
NO_AUDIT = "appeal_without_audit"
ISSUE_TYPES = [UNENROLLED, EXCEEDS_MAX, DOUBLE_PENALTY, NO_AUDIT]

GROUND_TRUTH_COLUMNS = ["anomaly_id", "issue_type", "record_table", "record_id",
                        "expected_detection", "injection_detail"]

EXPECTED = {
    UNENROLLED: "The submission's learner has no enrollment in the assignment's course.",
    EXCEEDS_MAX: "A criterion score or the final score exceeds the rubric maximum.",
    DOUBLE_PENALTY: "late_penalty_points is twice the value the late-penalty rule gives for this submission.",
    NO_AUDIT: "The appeal is upheld and the grade changed, but no appeal_adjustment grade_event exists for it.",
}


def _half(x):
    return round(x * 2) / 2


def _clip(x):
    return min(1.0, max(0.0, x))


def _next_event_no(events):
    return max(int(e["event_id"].rsplit("-", 1)[1]) for e in events) + 1


# ------------------------------------------------------------------ main entry point
def inject_anomalies(scale, tables, seed=config.SEED):
    """Return (injected_tables, ground_truth_rows). `tables` is not modified."""
    rng = random.Random(f"{seed}:inject")
    t = copy.deepcopy(tables)
    n = scale.n_anomalies_each

    assignments = {a["assignment_id"]: a for a in t["assignment"]}
    courses = {c["course_id"]: c for c in t["course"]}
    rubric_to_asn = {r["rubric_id"]: r["assignment_id"] for r in t["rubric"]}
    criteria_by_asn = defaultdict(list)
    for c in t["rubric_criterion"]:
        criteria_by_asn[rubric_to_asn[c["rubric_id"]]].append(c)
    criteria = {c["criterion_id"]: c for c in t["rubric_criterion"]}

    found = {t_: [] for t_ in ISSUE_TYPES}      # issue_type -> [(table, id, detail)]
    used_submissions = set()

    # ---------------------------------------------------------- 1. unenrolled submission
    enrolled = {(e["course_id"], e["learner_id"]) for e in t["enrollment"]}
    learner_ids = sorted(l["learner_id"] for l in t["learner"])
    candidates = sorted(
        (a for a in t["assignment"] if a["status"] == "closed"
         and parse_ts(a["due_at_utc"]) <= config.AS_OF - timedelta(days=20)),
        key=lambda a: a["assignment_id"])
    event_no = _next_event_no(t["grade_event"])

    for a in rng.sample(candidates, min(n, len(candidates))):
        asn, course = a["assignment_id"], courses[a["course_id"]]
        for _ in range(100):
            lrn = rng.choice(learner_ids)
            if (a["course_id"], lrn) not in enrolled:
                break
        else:
            continue
        sid, gid = ids.submission_id(asn, lrn), None
        pub, due = parse_ts(a["published_at_utc"]), parse_ts(a["due_at_utc"])
        span = int((due - pub).total_seconds())
        submitted = pub + timedelta(seconds=int(span * rng.betavariate(4, 1.5)))
        graded_at = submitted + timedelta(days=rng.randint(*config.GRADING_DELAY_DAYS),
                                          seconds=rng.randint(0, 86399))
        instructor = course["instructor_ref"]
        gid = ids.grade_id(sid)

        t["submission"].append({
            "submission_id": sid, "assignment_id": asn, "learner_id": lrn, "attempt_no": 1,
            "submitted_at_utc": to_ts(submitted), "is_late": 0, "hours_late": 0.0, "status": "finalized"})
        name = f"{lrn}_{asn}_1.pdf"
        size = rng.randint(2_000, 5_000_000)
        t["submission_artifact"].append({
            "artifact_id": ids.artifact_id(sid, 1), "submission_id": sid, "resubmission_id": None,
            "file_name": name, "file_type": "pdf", "file_size_bytes": size,
            "sha256": hashlib.sha256(f"{name}:{size}".encode()).hexdigest(),
            "file_status": "present", "uploaded_at_utc": to_ts(submitted)})

        q = _clip(rng.betavariate(*config.QUALITY_BETA))
        raw = 0.0
        for crit in criteria_by_asn[asn]:
            score = min(_half(_clip(q + rng.gauss(0, config.GRADER_NOISE_SD)) * crit["max_points"]),
                        crit["max_points"])
            raw += score
            t["grade_criterion_score"].append({"grade_id": gid, "criterion_id": crit["criterion_id"], "score": score})
        t["grade"].append({
            "grade_id": gid, "submission_id": sid, "raw_total": raw, "late_penalty_pct": 0.0,
            "late_penalty_points": 0.0, "final_score": raw, "graded_at_utc": to_ts(graded_at),
            "graded_by": instructor, "status": "final"})
        t["feedback"].append({
            "feedback_id": ids.feedback_id(gid, 1), "grade_id": gid, "criterion_id": None,
            "comment_text": next(text for floor, text in OVERALL_BANDS if raw / a["max_score"] * 100 >= floor),
            "author_ref": instructor, "created_at_utc": to_ts(graded_at + timedelta(seconds=rng.randint(0, 3600)))})
        t["grade_event"].append({
            "event_id": ids.event_id(event_no), "grade_id": gid, "event_type": "initial_grade",
            "old_score": None, "new_score": raw, "event_at_utc": to_ts(graded_at),
            "actor_role": "instructor", "actor_ref": instructor, "appeal_id": None,
            "resubmission_id": None, "reason": "Initial grading"})
        event_no += 1
        used_submissions.add(sid)
        found[UNENROLLED].append(("submission", sid, f"learner {lrn} is not enrolled in {a['course_id']}"))

    # ---------------------------------------------------------- shared lookups (after step 1)
    events_by_grade = defaultdict(list)
    for e in t["grade_event"]:
        events_by_grade[e["grade_id"]].append(e)
    score_rows = {(r["grade_id"], r["criterion_id"]): r for r in t["grade_criterion_score"]}
    sub_by_id = {s["submission_id"]: s for s in t["submission"]}
    has_route = {r["submission_id"] for r in t["resubmission"]} | {x["submission_id"] for x in t["appeal"]}

    def simple_grades():
        """Grades with a single event and no resubmission/appeal: safe to change on their own."""
        for g in sorted(t["grade"], key=lambda g: g["grade_id"]):
            sid = g["submission_id"]
            if sid in used_submissions or sid in has_route or len(events_by_grade[g["grade_id"]]) != 1:
                continue
            yield g, assignments[sub_by_id[sid]["assignment_id"]]

    # ---------------------------------------------------------- 2. grade exceeds maximum
    pool = [(g, a) for g, a in simple_grades()
            if g["late_penalty_pct"] == 0 and 0.92 * a["max_score"] <= g["raw_total"] < a["max_score"]]
    for g, a in rng.sample(pool, min(n, len(pool))):
        gid, asn = g["grade_id"], a["assignment_id"]
        biggest = max(criteria_by_asn[asn], key=lambda c: c["max_points"])   # keeps the overshoot modest
        target = score_rows[(gid, biggest["criterion_id"])]
        extra = (a["max_score"] - g["raw_total"]) + rng.choice([1.0, 2.0, 3.0])
        old = target["score"]
        target["score"] = old + extra
        g["raw_total"] = g["raw_total"] + extra
        g["final_score"] = g["raw_total"]                      # no penalty on this grade
        events_by_grade[gid][0]["new_score"] = g["final_score"]  # keep the audit trail consistent
        used_submissions.add(g["submission_id"])
        cmax = criteria[target["criterion_id"]]["max_points"]
        found[EXCEEDS_MAX].append(("grade", gid,
            f"{target['criterion_id']} score {old:g} -> {target['score']:g} (criterion max {cmax:g}); "
            f"final_score {g['final_score']:g} > assignment max {a['max_score']:g}"))

    # ---------------------------------------------------------- 3. late penalty applied twice
    pool = [(g, a) for g, a in simple_grades()
            if 10 <= g["late_penalty_pct"] <= 40 and g["raw_total"] >= 20]
    for g, a in rng.sample(pool, min(n, len(pool))):
        once = g["late_penalty_points"]
        g["late_penalty_points"] = round(2 * once, 2)
        g["final_score"] = round(g["raw_total"] - g["late_penalty_points"], 2)
        events_by_grade[g["grade_id"]][0]["new_score"] = g["final_score"]
        used_submissions.add(g["submission_id"])
        found[DOUBLE_PENALTY].append(("grade", g["grade_id"],
            f"penalty points {once:g} -> {g['late_penalty_points']:g} at {g['late_penalty_pct']:g}% "
            f"on raw {g['raw_total']:g}"))

    # ---------------------------------------------------------- 4. appeal changes grade, no audit row
    upheld = sorted((x for x in t["appeal"] if x["status"] == "upheld"
                     and x["submission_id"] not in used_submissions), key=lambda x: x["appeal_id"])
    k = min(n, max(1, len(upheld) // 2)) if upheld else 0     # keep some upheld appeals clean
    removed = {}
    for x in rng.sample(upheld, k):
        for e in events_by_grade[x["grade_id"]]:
            if e["appeal_id"] == x["appeal_id"]:
                removed[e["event_id"]] = e
                found[NO_AUDIT].append(("appeal", x["appeal_id"],
                    f"removed {e['event_id']} (appeal_adjustment {e['old_score']:g} -> {e['new_score']:g})"))
    t["grade_event"] = [e for e in t["grade_event"] if e["event_id"] not in removed]

    # ---------------------------------------------------------- ground truth rows
    truth = []
    for issue in ISSUE_TYPES:
        for table, rid, detail in sorted(found[issue], key=lambda r: r[1]):
            truth.append({"anomaly_id": f"GT-{len(truth) + 1:04d}", "issue_type": issue,
                          "record_table": table, "record_id": rid,
                          "expected_detection": EXPECTED[issue], "injection_detail": detail})
    return t, truth


# ------------------------------------------------------------------ self-check
def _diff_check(baseline, injected, truth):
    """Prove that only the labelled records differ from the clean baseline."""
    pk = {"grade": ("grade_id",), "grade_event": ("event_id",), "submission": ("submission_id",),
          "submission_artifact": ("artifact_id",), "feedback": ("feedback_id",),
          "grade_criterion_score": ("grade_id", "criterion_id")}
    counts = {i: sum(1 for r in truth if r["issue_type"] == i) for i in ISSUE_TYPES}

    def index(rows, keys):
        return {tuple(r[k] for k in keys): r for r in rows}

    for name in baseline:
        if name in pk:
            continue
        key = {"course": "course_id", "learner": "learner_id", "enrollment": "enrollment_id",
               "assignment": "assignment_id", "rubric": "rubric_id", "rubric_criterion": "criterion_id",
               "resubmission": "resubmission_id", "appeal": "appeal_id"}[name]
        assert baseline[name] == injected[name], f"{name} changed but should be untouched (key {key})"

    result = {}
    for name, keys in pk.items():
        a, b = index(baseline[name], keys), index(injected[name], keys)
        added, removed = set(b) - set(a), set(a) - set(b)
        changed = {k for k in set(a) & set(b) if a[k] != b[k]}
        result[name] = (len(added), len(removed), len(changed))

    n_new = counts[UNENROLLED]
    assert result["submission"] == (n_new, 0, 0), result["submission"]
    assert result["submission_artifact"] == (n_new, 0, 0)
    assert result["grade"][0] == n_new and result["grade"][1] == 0
    assert result["grade"][2] == counts[EXCEEDS_MAX] + counts[DOUBLE_PENALTY]
    assert result["grade_event"][0] == n_new and result["grade_event"][1] == counts[NO_AUDIT]
    assert result["grade_event"][2] == counts[EXCEEDS_MAX] + counts[DOUBLE_PENALTY]
    assert result["grade_criterion_score"][2] == counts[EXCEEDS_MAX]
    assert result["feedback"] == (n_new, 0, 0)
    return result


if __name__ == "__main__":
    # Run: python generator/inject.py [starter|full]
    from dataclasses import replace
    from lifecycle import generate_lifecycle
    from master import generate_master
    from transactions import generate_submissions

    scale = config.get_scale(sys.argv[1] if len(sys.argv) > 1 else "starter")
    base_scale = replace(scale, n_submissions=scale.n_submissions - scale.n_anomalies_each)
    master = generate_master(base_scale)
    part1, ctx = generate_submissions(base_scale, master)
    baseline = {**master, **generate_lifecycle(base_scale, master, part1, ctx)}

    injected, truth = inject_anomalies(scale, baseline)
    again, truth_again = inject_anomalies(scale, baseline)
    assert injected == again and truth == truth_again, "same seed produced different anomalies"
    diff = _diff_check(baseline, injected, truth)

    print("anomalies injected:", {i: sum(1 for r in truth if r["issue_type"] == i) for i in ISSUE_TYPES})
    print("submissions:", len(injected["submission"]), "(baseline", len(baseline["submission"]), "+ injected unenrolled)")
    for name, (added, removed, changed) in diff.items():
        print(f"  {name:22} added {added:>3}  removed {removed:>3}  changed {changed:>3}")
    print("inject OK (only labelled records differ from the baseline, same seed gives identical anomalies)")