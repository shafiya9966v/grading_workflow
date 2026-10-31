# Validation report: starter_baseline

- Dataset: `outputs\starter_baseline`
- Checks: 39 run, 0 with findings
- Assertions evaluated: 75,508
- Findings: 0

## Checks

| Group | Check | Evaluated | Failed | Status |
|---|---|---:|---:|---|
| keys | pk_unique | 10,302 | 0 | PASS |
| keys | id_format | 7,100 | 0 | PASS |
| keys | id_embeds_parent | 5,832 | 0 | PASS |
| joins | fk_valid | 15,885 | 0 | PASS |
| values | enum_valid | 7,757 | 0 | PASS |
| values | timestamp_format | 6,524 | 0 | PASS |
| values | due_time_timezone | 50 | 0 | PASS |
| dates | course_dates | 20 | 0 | PASS |
| dates | assignment_dates | 50 | 0 | PASS |
| dates | rubric_effective | 50 | 0 | PASS |
| dates | enrollment_dates | 506 | 0 | PASS |
| dates | submission_after_publish | 797 | 0 | PASS |
| dates | is_late_consistent | 797 | 0 | PASS |
| dates | grade_after_submission | 797 | 0 | PASS |
| dates | artifact_time | 1,279 | 0 | PASS |
| dates | feedback_after_grade | 2,117 | 0 | PASS |
| dates | event_times | 797 | 0 | PASS |
| dates | resubmission_dates | 86 | 0 | PASS |
| dates | appeal_dates | 23 | 0 | PASS |
| arithmetic | rubric_total | 50 | 0 | PASS |
| arithmetic | grade_scores_complete | 797 | 0 | PASS |
| arithmetic | criterion_score_nonnegative | 797 | 0 | PASS |
| arithmetic | grade_raw_total | 797 | 0 | PASS |
| arithmetic | late_penalty_pct_rule | 797 | 0 | PASS |
| arithmetic | late_penalty_points_rule | 797 | 0 | PASS |
| arithmetic | grade_final | 797 | 0 | PASS |
| arithmetic | grade_within_rubric_max | 797 | 0 | PASS |
| arithmetic | resubmission_cap | 60 | 0 | PASS |
| lifecycle | submission_learner_enrolled | 797 | 0 | PASS |
| lifecycle | submission_status_vs_grade | 797 | 0 | PASS |
| lifecycle | grade_status_vs_submission | 797 | 0 | PASS |
| lifecycle | event_chain | 797 | 0 | PASS |
| lifecycle | event_links | 875 | 0 | PASS |
| lifecycle | one_route | 797 | 0 | PASS |
| lifecycle | resubmission_policy | 86 | 0 | PASS |
| lifecycle | resubmission_status | 86 | 0 | PASS |
| lifecycle | appeal_status | 46 | 0 | PASS |
| lifecycle | appeal_audit_trail | 23 | 0 | PASS |
| duplicates | no_duplicate_natural_keys | 3,949 | 0 | PASS |
