# Design

> Draft. Every rule below is a decision I made and must be able to explain. Edit anything that no longer matches the code.

## 1. Problem understanding

The goal is a **synthetic data generator** (not an application) for an assignment and rubric-grading workflow: courses, learners, enrollments, assignments, rubrics, submissions, grades, feedback, resubmissions and appeals. The output is a set of related tables, a separate answer key for deliberately injected errors, a validation report, and proof that the same seed reproduces the same data.

## 2. Assumptions

- Only the required entities are modelled as tables, plus: `enrollment` (bridge), `grade_criterion_score` (bridge between grade and rubric criteria) and `grade_event` (append-only history).
- There is no instructor or staff table. Instructors and staff appear as reference IDs (`INS-0001`).
- One submission per learner per assignment. The `-01` in `SUB-...-01` is the attempt number of the original submission. Resubmissions are separate rows in `resubmission`, so the submission ID never changes.
- All data is synthetic. No external datasets are used.

## 3. Business rules (documented so outcomes are derived, not random)

| Area | Rule |
|---|---|
| Timezone | All timestamps are stored in UTC. Due dates are authored as 23:59 India time (Asia/Kolkata) and converted to UTC. A submission is late only if `submitted_at_utc > due_at_utc`; exactly at the deadline is on time. |
| Late penalty | `penalty_pct = min(50, 10 x ceil(hours_late / 24))`. `penalty_points = round(raw_total x penalty_pct / 100, 2)`. `final_score = raw_total - penalty_points`. Applied exactly once. |
| Grading | Each criterion score is between 0 and the criterion maximum. `raw_total` is the sum of criterion scores. |
| Missing file | If a submission has no artifact with `file_status = present`, all criterion scores are 0 and the feedback says no readable file was received. |
| Resubmission | Allowed only if the assignment permits it, the original `final_score` is below 60% of `max_score`, it is requested within 7 days of grade release, and there is at most one per submission. The regraded score is capped at 80% of `max_score` and carries no extra late penalty. The grade only changes if the new score is higher. |
| Appeal | At most one per submission, filed within 7 days of the grade release. A second review score is derived from the submission's underlying quality (the same value used to produce the original grade). If the review raw score exceeds the current raw score by 5% of `max_score` or more, the appeal is **upheld** and the grade is revised; otherwise it is **rejected**. A revision always creates a `grade_event` row. |
| History | Grade changes are never silent. Each change adds a `grade_event` row with old score, new score, actor, and the appeal or resubmission that caused it. |

## 4. Lifecycle states and legal transitions

- Assignment: draft -> published -> closed
- Submission: submitted -> graded -> (resubmitted -> graded) -> finalized
- Grade: released -> revised -> final
- Resubmission: requested -> submitted -> graded (or cancelled)
- Appeal: filed -> under_review -> upheld | rejected

The validator flags any record that jumps to a state it cannot legally reach.

## 5. ID conventions

| Entity | Format |
|---|---|
| Course | `CRS-2026-NNNN` (my choice) |
| Learner | `LRN-NNNNNN` (my choice) |
| Assignment | `ASN-2026-NNNNNN` |
| Rubric | `RUB-<assignment_id>-NN` |
| Criterion | `<rubric_id>-CNN` |
| Submission | `SUB-<assignment_id>-<learner_id>-NN` |
| Grade | `GRD-<submission_id>` |
| Appeal | `APP-2026-NNNNNN` |

Counters are zero-padded, IDs are immutable, and child IDs embed their parent ID so joins can be checked from the string alone.

## 6. Generation approach

1. Generate master data (courses, learners, enrollments, assignments, rubrics, criteria) from a fixed seed.
2. Generate submissions only for enrolled learners, then artifacts, grades, feedback, resubmissions, appeals and grade events, computing every derived value from source records.
3. Copy the clean dataset, then inject the four required anomalies and record each one in `ground_truth.csv`.
4. Run the validator on both the clean and the injected data.

Scale is a parameter (`starter` and `full` use the same generator code).

## 6a. Trade-offs

- **SQLite with few CHECK constraints.** The schema enforces keys, foreign keys and enums. Business rules are checked by the validator so that injected anomalies still load.
- **Standard library only.** Fewer installation problems for reviewers, at the cost of slightly more code than pandas would need.
- **Grade row holds the current value, `grade_event` holds history.** Simpler queries than versioned grade rows.

## 7. Testing and validation

TODO (fill in once the validator exists): primary-key uniqueness, foreign-key integrity, enums, date ordering, score reconciliation, lifecycle transitions, duplicates, detection of each injected anomaly, and the two-run reproducibility comparison.

## 8. Limitations

TODO (be honest, for example: simplified instructor model, a single global late-penalty policy, synthetic names, distributions chosen by me rather than measured from real data).

## 9. Next steps

TODO.