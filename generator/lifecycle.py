"""Transactions, part 2: resubmissions, appeals, grade changes and final statuses.

Rules (documented in Design.md section 3)
- A submission follows ONE route after grading: a resubmission OR an appeal, never both.
- Resubmission: allowed by the assignment, original final score below 60% of max,
  requested within 7 days of grade release, at most one per submission. The regraded
  criterion scores are capped at 80% of each criterion maximum. The original late
  penalty percentage still applies (it is recalculated on the new total, never doubled).
  The grade changes only if the new final score is higher.
- Appeal: at most one per submission, filed within 7 days of grade release. A second
  reviewer scores the work from its underlying quality. If the review raw score is at
  least 5% of max above the current raw score, the appeal is upheld and the grade is
  revised; otherwise it is rejected.
- Every grade change adds a grade_event row (old score, new score, who, why). Rows in
  grade_event are never edited. The grade row holds the CURRENT values.
- A submission becomes 'finalized' (grade 'final') once the request/appeal window has
  closed and nothing is still pending.
"""
import copy
import math
import random
import sys
from collections import Counter
from datetime import timedelta

import config
import ids
from master import generate_master, weighted_choice
from timeutil import parse_ts, to_ts
from transactions import _enrolment_window, generate_submissions, late_penalty

import hashlib

WINDOW = timedelta(days=max(config.RESUBMISSION_WINDOW_DAYS, config.APPEAL_WINDOW_DAYS))


def _half(x: float) -> float:
    return round(x * 2) / 2


def _clip(x: float) -> float:
    return min(1.0, max(0.0, x))


# ------------------------------------------------------------------ main generator
def generate_lifecycle(scale, master, tables, ctx, seed=config.SEED):
    rng = random.Random(f"{seed}:transactions-2")
    t = copy.deepcopy(tables)                      # never modify the caller's data
    quality = ctx["quality"]
    event_no = ctx["next_event_no"]

    assignments = {a["assignment_id"]: a for a in master["assignment"]}
    courses = {c["course_id"]: c for c in master["course"]}
    enrolments = {(e["course_id"], e["learner_id"]): e for e in master["enrollment"]}
    rubric_to_asn = {r["rubric_id"]: r["assignment_id"] for r in master["rubric"]}
    criteria_by_asn = {}
    for c in master["rubric_criterion"]:
        criteria_by_asn.setdefault(rubric_to_asn[c["rubric_id"]], []).append(c)

    grade_by_sub = {g["submission_id"]: g for g in t["grade"]}
    score_rows = {(r["grade_id"], r["criterion_id"]): r for r in t["grade_criterion_score"]}
    n_artifacts = Counter(a["submission_id"] for a in t["submission_artifact"])
    readable = {a["submission_id"] for a in t["submission_artifact"] if a["file_status"] == "present"}
    n_feedback = Counter(f["grade_id"] for f in t["feedback"])

    resubmissions, appeals = [], []
    appeal_no = 0

    def add_feedback(gid, text, author, when):
        n_feedback[gid] += 1
        t["feedback"].append({
            "feedback_id": ids.feedback_id(gid, n_feedback[gid]),
            "grade_id": gid, "criterion_id": None, "comment_text": text,
            "author_ref": author, "created_at_utc": to_ts(when),
        })

    def add_event(gid, etype, old, new, when, role, actor, reason, appeal=None, resub=None):
        nonlocal event_no
        t["grade_event"].append({
            "event_id": ids.event_id(event_no), "grade_id": gid, "event_type": etype,
            "old_score": old, "new_score": new, "event_at_utc": to_ts(when),
            "actor_role": role, "actor_ref": actor, "appeal_id": appeal,
            "resubmission_id": resub, "reason": reason,
        })
        event_no += 1

    def apply_scores(g, new_scores):
        """Update the CURRENT grade from new criterion scores (penalty % is kept)."""
        for crit, sc in new_scores:
            score_rows[(g["grade_id"], crit["criterion_id"])]["score"] = sc
        raw = sum(sc for _, sc in new_scores)
        pts = round(raw * g["late_penalty_pct"] / 100, 2)
        g["raw_total"], g["late_penalty_points"] = raw, pts
        g["final_score"] = round(raw - pts, 2)
        g["status"] = "revised"

    for s in t["submission"]:
        g = grade_by_sub.get(s["submission_id"])
        if g is None:
            continue                                   # not graded yet
        sid, gid = s["submission_id"], g["grade_id"]
        a = assignments[s["assignment_id"]]
        instructor = courses[a["course_id"]]["instructor_ref"]
        _, hard_end = _enrolment_window(enrolments[(a["course_id"], s["learner_id"])])
        graded_at = parse_ts(g["graded_at_utc"])
        max_score = a["max_score"]
        original_final = g["final_score"]
        percent = original_final / max_score * 100
        window_secs = config.RESUBMISSION_WINDOW_DAYS * 86400 - 1

        # ---------------------------------------------------------- route 1: resubmission
        route_resubmission = False
        if a["resubmission_allowed"] == 1 and original_final < config.RESUBMISSION_THRESHOLD_PCT / 100 * max_score:
            requested_at = graded_at + timedelta(seconds=rng.randint(3600, window_secs))
            if requested_at <= hard_end and rng.random() < config.RESUBMIT_RATE_WHEN_ELIGIBLE:
                route_resubmission = True

        if route_resubmission:
            rid = ids.resubmission_id(sid, 1)
            submitted_at, status = None, "cancelled"
            if rng.random() >= config.RESUBMIT_CANCEL_RATE:
                submitted_at = requested_at + timedelta(
                    seconds=rng.randint(3600, config.RESUBMIT_PREP_MAX_DAYS * 86400))
                if submitted_at > hard_end:
                    submitted_at = None
                    status = "requested" if hard_end >= config.AS_OF else "cancelled"
                else:
                    status = "submitted"

            if status == "submitted":
                file_ok = rng.random() >= config.CORRUPT_FILE_RATE
                ext = weighted_choice(rng, config.FILE_TYPES)
                n = n_artifacts[sid] + 1
                name = f"{s['learner_id']}_{s['assignment_id']}_{n}.{ext}"
                size = rng.randint(2_000, 5_000_000) if file_ok else rng.randint(1, 1000)
                t["submission_artifact"].append({
                    "artifact_id": ids.artifact_id(sid, n), "submission_id": sid,
                    "resubmission_id": rid, "file_name": name, "file_type": ext,
                    "file_size_bytes": size,
                    "sha256": hashlib.sha256(f"{name}:{size}".encode()).hexdigest(),
                    "file_status": "present" if file_ok else "corrupt",
                    "uploaded_at_utc": to_ts(submitted_at),
                })
                s["status"] = "resubmitted"

                regraded_at = submitted_at + timedelta(
                    days=rng.randint(*config.RESUBMIT_REGRADE_DAYS), seconds=rng.randint(0, 86399))
                if regraded_at <= config.AS_OF:
                    status = "graded"
                    s["status"] = "graded"
                    q2 = _clip(quality[sid] + rng.uniform(*config.RESUBMIT_IMPROVEMENT))
                    new_scores = []
                    for crit in criteria_by_asn[s["assignment_id"]]:
                        if file_ok:
                            sc = _half(_clip(q2 + rng.gauss(0, config.GRADER_NOISE_SD)) * crit["max_points"])
                            cap = math.floor(config.RESUBMISSION_CAP_PCT / 100 * crit["max_points"] * 2) / 2
                            sc = min(sc, cap)
                        else:
                            sc = 0.0
                        new_scores.append((crit, sc))
                    new_raw = sum(sc for _, sc in new_scores)
                    new_final = round(new_raw - round(new_raw * g["late_penalty_pct"] / 100, 2), 2)
                    improved = new_final > original_final
                    if improved:
                        apply_scores(g, new_scores)
                        reason = "Resubmission graded; higher score recorded"
                        text = f"Resubmission graded: score changed from {original_final:g} to {g['final_score']:g}."
                    else:
                        reason = "Resubmission graded; original score retained"
                        text = f"Resubmission graded: the new score was not higher, so {original_final:g} stands."
                    add_event(gid, "resubmission_regrade", original_final, g["final_score"],
                              regraded_at, "instructor", instructor, reason, resub=rid)
                    add_feedback(gid, text, instructor, regraded_at + timedelta(seconds=rng.randint(0, 3600)))

            resubmissions.append({
                "resubmission_id": rid, "submission_id": sid,
                "requested_at_utc": to_ts(requested_at),
                "submitted_at_utc": to_ts(submitted_at) if submitted_at else None,
                "status": status,
            })
            continue

        # ---------------------------------------------------------- route 2: appeal
        mult = next(m for limit, m in config.APPEAL_RATE_MULTIPLIER if percent < limit)
        if rng.random() >= config.APPEAL_RATE * mult:
            continue
        filed_at = graded_at + timedelta(seconds=rng.randint(3600, config.APPEAL_WINDOW_DAYS * 86400 - 1))
        if filed_at > hard_end:
            continue

        appeal_no += 1
        aid = ids.appeal_id(appeal_no)
        has_penalty = g["late_penalty_pct"] > 0
        reason_category = weighted_choice(rng, {
            "rubric_misapplied": 0.45, "calculation_error": 0.20,
            "late_penalty_dispute": 0.25 if has_penalty else 0.0, "other": 0.10})
        admin = f"ADM-{rng.randint(1, 5):04d}"
        decided_at = filed_at + timedelta(days=rng.randint(*config.APPEAL_DECISION_DAYS),
                                          seconds=rng.randint(0, 86399))
        row = {
            "appeal_id": aid, "submission_id": sid, "grade_id": gid,
            "filed_at_utc": to_ts(filed_at), "reason_category": reason_category,
            "status": None, "decided_at_utc": None, "original_score": original_final,
            "revised_score": None, "decision_notes": None,
        }
        if decided_at > config.AS_OF:
            row["status"] = "under_review" if config.AS_OF >= filed_at + timedelta(days=1) else "filed"
        else:
            margin = config.APPEAL_UPHOLD_MARGIN_PCT / 100 * max_score
            review = []
            for crit in criteria_by_asn[s["assignment_id"]]:
                if sid in readable:
                    sc = _half(_clip(quality[sid] + rng.gauss(0, config.REVIEWER_NOISE_SD)) * crit["max_points"])
                else:
                    sc = 0.0
                review.append((crit, sc))
            review_raw = sum(sc for _, sc in review)
            upheld = review_raw - g["raw_total"] >= margin
            note = (f"Second review raw score {review_raw:g} vs original {g['raw_total']:g} "
                    f"(threshold {margin:g} points). ")
            row["decided_at_utc"] = to_ts(decided_at)
            if upheld:
                apply_scores(g, review)
                row["status"], row["revised_score"] = "upheld", g["final_score"]
                row["decision_notes"] = note + "Upheld; grade revised."
                add_event(gid, "appeal_adjustment", original_final, g["final_score"], decided_at,
                          "academic_admin", admin, f"Appeal {aid} upheld after second review", appeal=aid)
                text = f"Appeal {aid} upheld: grade revised from {original_final:g} to {g['final_score']:g}."
            else:
                row["status"] = "rejected"
                row["decision_notes"] = note + "Original grade stands."
                text = f"Appeal {aid} reviewed: the original grade stands."
            add_feedback(gid, text, admin, decided_at + timedelta(seconds=rng.randint(0, 3600)))
        appeals.append(row)

    # ---------------------------------------------------------- final statuses
    resub_by_sub = {r["submission_id"]: r for r in resubmissions}
    appeal_by_sub = {x["submission_id"]: x for x in appeals}
    for s in t["submission"]:
        g = grade_by_sub.get(s["submission_id"])
        if g is None or s["status"] != "graded":
            continue
        r, x = resub_by_sub.get(s["submission_id"]), appeal_by_sub.get(s["submission_id"])
        pending = (r is not None and r["status"] in ("requested", "submitted")) or \
                  (x is not None and x["status"] in ("filed", "under_review"))
        if not pending and parse_ts(g["graded_at_utc"]) + WINDOW <= config.AS_OF:
            s["status"], g["status"] = "finalized", "final"

    t["resubmission"], t["appeal"] = resubmissions, appeals
    return t


# ------------------------------------------------------------------ self-check
def _self_check(master, t):
    tol = 0.01
    assignments = {a["assignment_id"]: a for a in master["assignment"]}
    criteria = {c["criterion_id"]: c for c in master["rubric_criterion"]}
    enrolments = {(e["course_id"], e["learner_id"]): e for e in master["enrollment"]}
    subs = {s["submission_id"]: s for s in t["submission"]}
    grades = {g["grade_id"]: g for g in t["grade"]}

    # scores reconcile with the rubric and the penalty rule
    scores = {}
    for r in t["grade_criterion_score"]:
        assert 0 <= r["score"] <= criteria[r["criterion_id"]]["max_points"], "criterion score out of range"
        scores.setdefault(r["grade_id"], []).append(r["score"])
    for g in grades.values():
        s = subs[g["submission_id"]]
        a = assignments[s["assignment_id"]]
        late = max(0, int((parse_ts(s["submitted_at_utc"]) - parse_ts(a["due_at_utc"])).total_seconds()))
        pct, _ = late_penalty(late, g["raw_total"])
        assert abs(sum(scores[g["grade_id"]]) - g["raw_total"]) < tol, "raw total mismatch"
        assert g["late_penalty_pct"] == pct, "late penalty percentage changed or doubled"
        assert abs(g["late_penalty_points"] - round(g["raw_total"] * pct / 100, 2)) < tol, "penalty points mismatch"
        assert abs(g["final_score"] - (g["raw_total"] - g["late_penalty_points"])) < tol, "final mismatch"
        assert 0 <= g["final_score"] <= a["max_score"], "grade outside 0..max"

    # event history is complete and chained
    events = {}
    for e in t["grade_event"]:
        events.setdefault(e["grade_id"], []).append(e)
    assert set(events) == set(grades), "every grade needs events"
    for gid, evs in events.items():
        evs.sort(key=lambda e: (e["event_at_utc"], e["event_id"]))
        assert evs[0]["event_type"] == "initial_grade" and evs[0]["old_score"] is None
        for prev, cur in zip(evs, evs[1:]):
            assert cur["old_score"] == prev["new_score"], "event chain broken"
            assert cur["new_score"] >= cur["old_score"], "score went down on a regrade"
        assert abs(evs[-1]["new_score"] - grades[gid]["final_score"]) < tol, "latest event differs from grade"
    event_ids = [e["event_id"] for e in t["grade_event"]]
    assert len(event_ids) == len(set(event_ids)), "duplicate event IDs"

    # resubmissions follow the policy
    seen = set()
    for r in t["resubmission"]:
        sid = r["submission_id"]
        assert sid not in seen, "more than one resubmission"
        seen.add(sid)
        g, s = grades[ids.grade_id(sid)], subs[sid]
        a = assignments[s["assignment_id"]]
        first = events[g["grade_id"]][0]
        assert a["resubmission_allowed"] == 1, "resubmission not allowed for assignment"
        assert first["new_score"] < config.RESUBMISSION_THRESHOLD_PCT / 100 * a["max_score"], "score too high to resubmit"
        gap = parse_ts(r["requested_at_utc"]) - parse_ts(g["graded_at_utc"])
        assert timedelta(0) < gap <= timedelta(days=config.RESUBMISSION_WINDOW_DAYS), "request outside window"
        arts = [x for x in t["submission_artifact"] if x["resubmission_id"] == r["resubmission_id"]]
        assert bool(arts) == (r["submitted_at_utc"] is not None), "artifacts and submitted time disagree"
        regrade = [e for e in events[g["grade_id"]] if e["resubmission_id"] == r["resubmission_id"]]
        assert bool(regrade) == (r["status"] == "graded"), "regrade event and status disagree"
        assert g["raw_total"] <= config.RESUBMISSION_CAP_PCT / 100 * a["max_score"] + tol or not regrade or \
            regrade[0]["new_score"] == regrade[0]["old_score"], "resubmission cap exceeded"

    # appeals follow the policy and are traceable
    seen_a, ap_ids = set(), set()
    for x in t["appeal"]:
        sid = x["submission_id"]
        assert sid not in seen_a and sid not in seen, "more than one route or appeal"
        seen_a.add(sid)
        assert x["appeal_id"] not in ap_ids
        ap_ids.add(x["appeal_id"])
        g = grades[x["grade_id"]]
        assert g["submission_id"] == sid
        first = events[g["grade_id"]][0]
        assert x["original_score"] == first["new_score"], "appeal original score wrong"
        gap = parse_ts(x["filed_at_utc"]) - parse_ts(g["graded_at_utc"])
        assert timedelta(0) < gap <= timedelta(days=config.APPEAL_WINDOW_DAYS), "appeal outside window"
        linked = [e for e in events[g["grade_id"]] if e["appeal_id"] == x["appeal_id"]]
        if x["status"] == "upheld":
            assert len(linked) == 1 and linked[0]["new_score"] == x["revised_score"] > x["original_score"]
            assert linked[0]["old_score"] == x["original_score"], "audit row does not match"
        else:
            assert not linked and x["revised_score"] is None, "unexpected audit row or revised score"
        if x["status"] in ("upheld", "rejected"):
            assert parse_ts(x["decided_at_utc"]) >= parse_ts(x["filed_at_utc"])
        else:
            assert x["decided_at_utc"] is None

    # learners were enrolled for everything they did
    for r in t["resubmission"]:
        s = subs[r["submission_id"]]
        a = assignments[s["assignment_id"]]
        _, end = _enrolment_window(enrolments[(a["course_id"], s["learner_id"])])
        assert parse_ts(r["requested_at_utc"]) <= end, "resubmission after enrolment ended"

    # final statuses are consistent
    for s in t["submission"]:
        g = grades.get(ids.grade_id(s["submission_id"]))
        if s["status"] == "finalized":
            assert g is not None and g["status"] == "final"
        if g is None:
            assert s["status"] == "submitted"
    assert all(g["status"] != "final" or subs[g["submission_id"]]["status"] == "finalized" for g in grades.values())


if __name__ == "__main__":
    # Run: python generator/lifecycle.py [starter|full]
    scale_name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    scale = config.get_scale(scale_name)
    master = generate_master(scale)
    part1, ctx = generate_submissions(scale, master)
    result = generate_lifecycle(scale, master, part1, ctx)
    assert result == generate_lifecycle(scale, master, part1, ctx), "same seed produced different data"
    _self_check(master, result)

    print("resubmissions by status:", dict(Counter(r["status"] for r in result["resubmission"])))
    print("appeals by status:      ", dict(Counter(x["status"] for x in result["appeal"])))
    print("grade events by type:   ", dict(Counter(e["event_type"] for e in result["grade_event"])))
    print("grade status:           ", dict(Counter(g["status"] for g in result["grade"])))
    print("submission status:      ", dict(Counter(s["status"] for s in result["submission"])))
    print("lifecycle OK (checks passed, same seed gives identical data)")