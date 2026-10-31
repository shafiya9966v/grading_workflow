# Validation report: starter

- Dataset: `outputs\starter`
- Checks: 39 run, 5 with findings
- Assertions evaluated: 75,698
- Findings: 11

## Checks

| Group | Check | Evaluated | Failed | Status |
|---|---|---:|---:|---|
| keys | pk_unique | 10,328 | 0 | PASS |
| keys | id_format | 7,114 | 0 | PASS |
| keys | id_embeds_parent | 5,844 | 0 | PASS |
| joins | fk_valid | 15,925 | 0 | PASS |
| values | enum_valid | 7,776 | 0 | PASS |
| values | timestamp_format | 6,538 | 0 | PASS |
| values | due_time_timezone | 50 | 0 | PASS |
| dates | course_dates | 20 | 0 | PASS |
| dates | assignment_dates | 50 | 0 | PASS |
| dates | rubric_effective | 50 | 0 | PASS |
| dates | enrollment_dates | 506 | 0 | PASS |
| dates | submission_after_publish | 800 | 0 | PASS |
| dates | is_late_consistent | 800 | 0 | PASS |
| dates | grade_after_submission | 800 | 0 | PASS |
| dates | artifact_time | 1,282 | 0 | PASS |
| dates | feedback_after_grade | 2,120 | 0 | PASS |
| dates | event_times | 800 | 0 | PASS |
| dates | resubmission_dates | 86 | 0 | PASS |
| dates | appeal_dates | 23 | 0 | PASS |
| arithmetic | rubric_total | 50 | 0 | PASS |
| arithmetic | grade_scores_complete | 800 | 0 | PASS |
| arithmetic | criterion_score_nonnegative | 800 | 0 | PASS |
| arithmetic | grade_raw_total | 800 | 0 | PASS |
| arithmetic | late_penalty_pct_rule | 800 | 0 | PASS |
| arithmetic | late_penalty_points_rule | 800 | 3 | FAIL |
| arithmetic | grade_final | 800 | 0 | PASS |
| arithmetic | grade_within_rubric_max | 800 | 3 | FAIL |
| arithmetic | resubmission_cap | 60 | 0 | PASS |
| lifecycle | submission_learner_enrolled | 800 | 3 | FAIL |
| lifecycle | submission_status_vs_grade | 800 | 0 | PASS |
| lifecycle | grade_status_vs_submission | 800 | 0 | PASS |
| lifecycle | event_chain | 800 | 1 | FAIL |
| lifecycle | event_links | 877 | 0 | PASS |
| lifecycle | one_route | 800 | 0 | PASS |
| lifecycle | resubmission_policy | 86 | 0 | PASS |
| lifecycle | resubmission_status | 86 | 0 | PASS |
| lifecycle | appeal_status | 46 | 0 | PASS |
| lifecycle | appeal_audit_trail | 23 | 1 | FAIL |
| duplicates | no_duplicate_natural_keys | 3,958 | 0 | PASS |

## Detection scored against ground truth

| Anomaly | Expected | Flagged | Correct | False positives | Missed | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| appeal_without_audit | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| double_late_penalty | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| grade_exceeds_max | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| unenrolled_submission | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |

Unexpected findings (not on a labelled record): **0**
