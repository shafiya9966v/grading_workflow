"""Transactions, part 1: submissions, artifacts, grades, criterion scores, feedback and
the initial grade events. (Resubmissions and appeals come in part 2.)

Key ideas
- A submission can only exist for a learner who was ENROLLED at the moment of submission.
- Every submission has a hidden "true quality" (0 to 1). Grades are derived from it
  (plus a little grader noise), so outcomes follow rules, not independent random numbers.
- Every derived value (hours late, penalty, totals, statuses) is calculated from source
  records, never generated separately.
- The hidden quality is returned in `ctx`, NOT written to any table, so it can never
  leak into the data files.
"""
import hashlib
import math
import random
import sys
from datetime import date, timedelta

import config
import ids
from master import generate_master, weighted_choice
from timeutil import ist_to_utc, parse_ts, to_ts

ONE_SECOND = timedelta(seconds=1)

OVERALL_BANDS = [  # (minimum percent, comment)
    (85, "Excellent work that meets almost every criterion."),
    (70, "Good work with a few areas to strengthen."),
    (50, "Satisfactory. Several criteria need more depth."),
    (0, "Needs significant improvement. Please review the rubric and seek help."),
]
STRENGTH = ["Strong result on this criterion.", "Clear and well executed."]
WEAKNESS = ["This criterion needs more work.", "Below the expected level here; see the rubric."]


# ------------------------------------------------------------------ helpers
def late_penalty(hours_late_seconds: int, raw_total: float):
    """Late penalty rule from Design.md. Input: seconds late (0 if on time).

    pct = min(cap, per_day x started days late); points = round(raw x pct / 100, 2).
    """
    if hours_late_seconds <= 0:
        return 0.0, 0.0
    days_started = -(-hours_late_seconds // 86400)     # ceiling division on whole seconds
    pct = float(min(config.PENALTY_CAP_PCT, config.PENALTY_PCT_PER_DAY * days_started))
    return pct, round(raw_total * pct / 100, 2)


def _enrolment_window(enrolment):
    """(start, last allowed instant) in UTC for an enrolment row."""
    start = ist_to_utc(date.fromisoformat(enrolment["enrolled_from"]), 0, 0)
    if enrolment["enrolled_to"] is None:
        return start, config.AS_OF
    after = date.fromisoformat(enrolment["enrolled_to"]) + timedelta(days=1)
    return start, min(ist_to_utc(after, 0, 0) - ONE_SECOND, config.AS_OF)


def _eligible_pairs(master):
    """All (assignment, enrolment) pairs where a submission could legitimately exist."""
    by_course = {}
    for e in master["enrollment"]:
        by_course.setdefault(e["course_id"], []).append(e)

    pairs = []
    for a in master["assignment"]:
        if a["status"] == "draft":
            continue                                   # not published yet
        pub, due = parse_ts(a["published_at_utc"]), parse_ts(a["due_at_utc"])
        for e in by_course.get(a["course_id"], []):
            enrol_start, hard_end = _enrolment_window(e)
            window_start = max(pub, enrol_start)
            if window_start < min(due, hard_end):
                pairs.append((a, e))
    return pairs


def _pick_submission_time(rng, a, e):
    """Return the submission instant (UTC) for this pair, following the timing rules."""
    pub, due = parse_ts(a["published_at_utc"]), parse_ts(a["due_at_utc"])
    enrol_start, hard_end = _enrolment_window(e)
    window_start = max(pub, enrol_start)
    on_time_end = min(due, hard_end)

    roll = rng.random()
    if roll < config.BOUNDARY_RATE / 2 and on_time_end == due:
        return due                                      # exactly at the deadline: on time
    if config.BOUNDARY_RATE / 2 <= roll < config.BOUNDARY_RATE and due + ONE_SECOND <= hard_end:
        return due + ONE_SECOND                         # 1 second after: late

    late_end = min(due + timedelta(days=config.LATE_MAX_DAYS), hard_end)
    if rng.random() < config.LATE_RATE and late_end > due:
        span = int((late_end - due).total_seconds())
        return due + timedelta(seconds=1 + int((span - 1) * rng.betavariate(1, 2)))

    span = int((on_time_end - window_start).total_seconds())
    return window_start + timedelta(seconds=int(span * rng.betavariate(4, 1.5)))


# ------------------------------------------------------------------ main generator
def generate_submissions(scale, master, seed=config.SEED):
    rng = random.Random(f"{seed}:transactions-1")      # separate stream from master data
    assignments = {a["assignment_id"]: a for a in master["assignment"]}
    courses = {c["course_id"]: c for c in master["course"]}
    criteria_by_asn = {}
    for c in master["rubric_criterion"]:
        asn = c["rubric_id"][len("RUB-"):-len("-01")]  # rubric id = RUB-<assignment-id>-01
        criteria_by_asn.setdefault(asn, []).append(c)

    pairs = _eligible_pairs(master)
    chosen = rng.sample(pairs, min(scale.n_submissions, len(pairs)))
    chosen.sort(key=lambda p: (p[0]["assignment_id"], p[1]["learner_id"]))

    out = {k: [] for k in ("submission", "submission_artifact", "grade",
                           "grade_criterion_score", "feedback", "grade_event")}
    quality = {}
    event_no = 0

    for a, e in chosen:
        asn, lrn = a["assignment_id"], e["learner_id"]
        sid = ids.submission_id(asn, lrn)
        due = parse_ts(a["due_at_utc"])
        submitted = _pick_submission_time(rng, a, e)

        late_seconds = max(0, int((submitted - due).total_seconds()))
        is_late = submitted > due
        q = min(1.0, max(0.0, rng.betavariate(*config.QUALITY_BETA)))
        quality[sid] = q

        # ---- files ---------------------------------------------------------
        n_files = weighted_choice(rng, config.ARTIFACTS_PER_SUBMISSION)
        no_files = rng.random() < config.MISSING_FILE_RATE
        statuses = []
        for n in range(1, n_files + 1):
            if no_files:
                status = "missing"
            else:
                status = "corrupt" if rng.random() < config.CORRUPT_FILE_RATE else "present"
            statuses.append(status)
            ext = weighted_choice(rng, config.FILE_TYPES)
            name = f"{lrn}_{asn}_{n}.{ext}"
            size = 0 if status == "missing" else (
                rng.randint(1, 1000) if status == "corrupt" else rng.randint(2_000, 5_000_000))
            out["submission_artifact"].append({
                "artifact_id": ids.artifact_id(sid, n),
                "submission_id": sid,
                "resubmission_id": None,
                "file_name": name,
                "file_type": ext,
                "file_size_bytes": size,
                "sha256": None if status == "missing" else hashlib.sha256(f"{name}:{size}".encode()).hexdigest(),
                "file_status": status,
                "uploaded_at_utc": to_ts(submitted),
            })
        has_readable_file = "present" in statuses

        # ---- grading time decides whether a grade exists yet ---------------
        graded_at = submitted + timedelta(days=rng.randint(*config.GRADING_DELAY_DAYS),
                                          seconds=rng.randint(0, 86399))
        graded = graded_at <= config.AS_OF

        out["submission"].append({
            "submission_id": sid,
            "assignment_id": asn,
            "learner_id": lrn,
            "attempt_no": 1,
            "submitted_at_utc": to_ts(submitted),
            "is_late": 1 if is_late else 0,
            "hours_late": round(late_seconds / 3600, 4),
            "status": "graded" if graded else "submitted",
        })
        if not graded:
            continue

        # ---- grade ---------------------------------------------------------
        instructor = courses[a["course_id"]]["instructor_ref"]
        gid = ids.grade_id(sid)
        scores = []
        for crit in criteria_by_asn[asn]:
            if has_readable_file:
                ratio = min(1.0, max(0.0, q + rng.gauss(0, config.GRADER_NOISE_SD)))
                score = round(ratio * crit["max_points"] * 2) / 2
            else:
                score = 0.0
            scores.append((crit, min(score, crit["max_points"])))
            out["grade_criterion_score"].append(
                {"grade_id": gid, "criterion_id": crit["criterion_id"], "score": scores[-1][1]})

        raw_total = sum(s for _, s in scores)                       # derived
        pct, pts = late_penalty(late_seconds, raw_total)            # derived
        final = round(raw_total - pts, 2)                           # derived
        out["grade"].append({
            "grade_id": gid,
            "submission_id": sid,
            "raw_total": raw_total,
            "late_penalty_pct": pct,
            "late_penalty_points": pts,
            "final_score": final,
            "graded_at_utc": to_ts(graded_at),
            "graded_by": instructor,
            "status": "released",
        })

        event_no += 1
        out["grade_event"].append({
            "event_id": ids.event_id(event_no),
            "grade_id": gid,
            "event_type": "initial_grade",
            "old_score": None,
            "new_score": final,
            "event_at_utc": to_ts(graded_at),
            "actor_role": "instructor",
            "actor_ref": instructor,
            "appeal_id": None,
            "resubmission_id": None,
            "reason": "Initial grading",
        })

        # ---- feedback ------------------------------------------------------
        fb_at = graded_at + timedelta(seconds=rng.randint(0, 3600))
        fb_n = 0

        def add_feedback(text, criterion=None):
            nonlocal fb_n
            fb_n += 1
            out["feedback"].append({
                "feedback_id": ids.feedback_id(gid, fb_n),
                "grade_id": gid,
                "criterion_id": criterion,
                "comment_text": text,
                "author_ref": instructor,
                "created_at_utc": to_ts(fb_at),
            })

        if not has_readable_file:
            add_feedback("No readable file was received for this submission; a score of zero was recorded.")
        else:
            percent = final / a["max_score"] * 100
            overall = next(text for floor, text in OVERALL_BANDS if percent >= floor)
            if pct > 0:
                overall += f" A late penalty of {pct:g}% was applied."
            add_feedback(overall)
            for crit, score in scores:
                ratio = score / crit["max_points"]
                if ratio < 0.6:
                    add_feedback(f"{crit['name']}: {rng.choice(WEAKNESS)}", crit["criterion_id"])
                elif ratio >= 0.9:
                    add_feedback(f"{crit['name']}: {rng.choice(STRENGTH)}", crit["criterion_id"])

    ctx = {"quality": quality, "next_event_no": event_no + 1}
    return out, ctx


# ------------------------------------------------------------------ quick self-check
def _self_check(master, tables):
    tol = 0.01
    subs = tables["submission"]
    sub_ids = {s["submission_id"] for s in subs}
    assert len(sub_ids) == len(subs), "duplicate submission IDs"
    assignments = {a["assignment_id"]: a for a in master["assignment"]}
    enrolments = {(e["course_id"], e["learner_id"]): e for e in master["enrollment"]}
    criteria = {c["criterion_id"]: c for c in master["rubric_criterion"]}

    for s in subs:
        a = assignments[s["assignment_id"]]
        e = enrolments.get((a["course_id"], s["learner_id"]))
        assert e is not None, f"unenrolled learner in {s['submission_id']}"
        start, end = _enrolment_window(e)
        t = parse_ts(s["submitted_at_utc"])
        assert start <= t <= end, f"submitted outside enrolment window: {s['submission_id']}"
        assert t >= parse_ts(a["published_at_utc"]), "submitted before publication"
        due = parse_ts(a["due_at_utc"])
        assert s["is_late"] == (1 if t > due else 0), "is_late mismatch"

    grades = {g["grade_id"]: g for g in tables["grade"]}
    assert len(grades) == len(tables["grade"]), "duplicate grade IDs"
    scores_by_grade = {}
    for r in tables["grade_criterion_score"]:
        crit = criteria[r["criterion_id"]]
        assert 0 <= r["score"] <= crit["max_points"], "criterion score out of range"
        scores_by_grade.setdefault(r["grade_id"], []).append(r["score"])
    sub_by_id = {s["submission_id"]: s for s in subs}
    for g in grades.values():
        s = sub_by_id[g["submission_id"]]
        a = assignments[s["assignment_id"]]
        assert abs(sum(scores_by_grade[g["grade_id"]]) - g["raw_total"]) < tol, "raw total mismatch"
        late_secs = max(0, int((parse_ts(s["submitted_at_utc"]) - parse_ts(a["due_at_utc"])).total_seconds()))
        pct, pts = late_penalty(late_secs, g["raw_total"])
        assert g["late_penalty_pct"] == pct and abs(g["late_penalty_points"] - pts) < tol, "penalty mismatch"
        assert abs(g["final_score"] - (g["raw_total"] - g["late_penalty_points"])) < tol, "final mismatch"
        assert 0 <= g["final_score"] <= a["max_score"], "grade outside 0..max"
        assert g["graded_at_utc"] > s["submitted_at_utc"], "graded before submission"
    assert {e["grade_id"] for e in tables["grade_event"]} == set(grades), "every grade needs an event"
    assert all(f["grade_id"] in grades for f in tables["feedback"]), "feedback FK broken"


if __name__ == "__main__":
    # Run: python generator/transactions.py [starter|full]
    scale_name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    scale = config.get_scale(scale_name)
    master = generate_master(scale)
    tables, ctx = generate_submissions(scale, master)
    again, _ = generate_submissions(scale, master)
    assert tables == again, "same seed produced different transactions"
    _self_check(master, tables)

    subs = tables["submission"]
    late = sum(s["is_late"] for s in subs)
    missing = sum(1 for g in tables["feedback"] if g["comment_text"].startswith("No readable"))
    print(f"submissions {len(subs)} (late {late}, ungraded {len(subs) - len(tables['grade'])}, no readable file {missing})")
    for name, rows in tables.items():
        print(f"{name:22} {len(rows):>7} rows")
    print("transactions part 1 OK (checks passed, same seed gives identical data)")