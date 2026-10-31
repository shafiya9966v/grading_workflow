# Design

This document explains what the project builds, the assumptions and rules behind it, the key decisions and trade-offs, how it was tested, and what it does not do.

## 1. What this project is

A **synthetic data generator** for an assignment and rubric-grading workflow (courses, learners, assignments, rubrics, submissions, grades, feedback, resubmissions and appeals). It is not a grading application. One command produces related tables, a separate answer key for deliberately injected errors, and manifests with checksums. A separate validator checks the data, and a reproducibility script proves the same seed gives the same files.

Everything is synthetic. No external data is used and no real personal data appears (names are combinations from short fixed lists and may match real people by chance; e-mail addresses use `example.edu`).

## 2. Pipeline

```
config.py (seed, scale, rules, rates)
   |
master.py        courses, learners, enrollments, assignments, rubrics, criteria
   |
transactions.py  submissions, files, grades, criterion scores, feedback, initial events
   |
lifecycle.py     resubmissions, appeals, grade changes, history events, final statuses
   |
BASELINE  (fully valid; written with --baseline-out)
   |
inject.py        adds 4 labelled anomaly types  ->  ground_truth
   |
generate.py      sorts every table by primary key, loads it into SQLite (foreign keys on),
                 writes CSV / JSON / SQL / ground truth / manifest
```

The validator (`validator/validate.py`) is independent: it reads only the CSV tables and shares no code with the generator. Its policy constants are repeated in that file and must be kept equal to section 5.

## 3. Data model

14 tables: the 11 required entities plus three added for correctness.

| Added table | Why |
|---|---|
| `enrollment` | Bridge table for the many-to-many link between course and learner, with effective dates and status |
| `grade_criterion_score` | One score per rubric criterion per grade, so totals can be reconciled to the rubric |
| `grade_event` | Append-only history of every grade change (old score, new score, actor, reason, linked appeal or resubmission) |

Relationships (full field-level detail is in `docs/data_dictionary.md`, SQL in `schema.sql`):

```
course 1--N enrollment N--1 learner          (N:M via enrollment)
course 1--N assignment 1--N rubric 1--N rubric_criterion
assignment 1--N submission N--1 learner
submission 1--N submission_artifact
submission 1--1 grade (optional until graded) 1--N grade_criterion_score N--1 rubric_criterion
grade 1--N feedback        grade 1--N grade_event
submission 1--N resubmission (policy allows 1)   submission 1--N appeal (policy allows 1)
```

ID formats: `CRS-2026-0001`, `LRN-000001` (these two are my own choice, the task does not specify them), `ASN-2026-000001`, `RUB-<assignment-id>-01`, `<rubric-id>-C01`, `SUB-<assignment-id>-<learner-id>-01`, `GRD-<submission-id>`, `APP-2026-000001`, `ART-`/`FBK-`/`RSB-<parent-id>-NN`, `EVT-2026-000001`. Counters are zero-padded, IDs never change, and child IDs embed their parent ID so joins can be checked from the string alone. The `-01` in a submission ID is the attempt number of the original submission; resubmissions are separate rows in `resubmission`, so a submission ID never changes.

## 4. Assumptions

- One submission per learner per assignment. There is no instructor or staff table; instructors and administrators appear only as reference IDs (`INS-0001`, `ADM-0001`).
- A fixed "as of" moment (2026-10-15 00:00 UTC) stands in for "now". The real clock is never used, because it would make runs differ.
- All timestamps are UTC; due dates are authored in India time (IST, fixed +05:30, no daylight saving).
- Course and learner counts are my own sizing (400 courses, 10,000 learners, about 1.7 enrollments per learner) chosen so that 30,000 submissions is a realistic share (about 75%: 30,000 of 40,084 possible learner/assignment pairs) of the work that could have been submitted.

## 5. Business rules (outcomes follow rules, not independent random draws)

| Area | Rule |
|---|---|
| Time zones | Publish at 09:00 IST, due at 23:59 IST, both stored as UTC. A submission is late only if `submitted_at > due_at`; exactly at the deadline is on time. |
| Who can submit | Only a learner enrolled at the moment of submission. A learner who dropped cannot submit after the drop date. |
| Grading | Each submission has a hidden underlying quality (0 to 1). A criterion score is quality plus grader noise (SD 0.08) times the criterion maximum, rounded to 0.5 and capped at the maximum. Quality is never written to any table. |
| Missing files | 3% of submissions have no files; 1% of files are corrupt. With no readable file every criterion scores 0 and the feedback says so. |
| Late penalty | `pct = min(50, 10 x started days late)`; `points = round(raw_total x pct / 100, 2)`; `final = raw_total - points`. Calculated from the exact timestamps and applied once. |
| Grade release | 1 to 10 days after submission. If that moment is after the as-of date the submission is still ungraded (this is derived, not drawn). |
| Resubmission | Only if the assignment allows it, the original final score is below 60% of the maximum, requested within 7 days of grade release, at most one per submission. The new work is regraded with every criterion capped at 80% of its maximum. The late-penalty percentage stays and is recalculated on the new total (never doubled). The grade changes only if the new score is higher; the regrade is logged either way. |
| Appeal | At most one per submission, filed within 7 days of grade release. Low scores are more likely to be appealed. A second reviewer scores the work from the same hidden quality with less noise (SD 0.04). If the review raw score is at least 5% of the maximum above the current raw score the appeal is upheld and the grade revised; otherwise rejected. |
| One route | A submission follows a resubmission or an appeal, never both (a simplification that avoids two overlapping score changes). |
| History | Every grade change adds a `grade_event` row. Events are never edited. The `grade` row holds the current values. |
| Finalisation | When 7 days have passed since release and nothing is pending, the submission becomes `finalized` and the grade `final`. |

Lifecycle states: assignment `draft -> published -> closed`; submission `submitted -> graded -> (resubmitted -> graded) -> finalized`; grade `released -> revised -> final`; resubmission `requested -> submitted -> graded` or `cancelled`; appeal `filed -> under_review -> upheld | rejected`.

## 6. Derived values

Totals, hours late, penalties, final scores, statuses, rubric totals and `is_late` are calculated from source records. The generator computes them once; the validator recomputes them independently from the stored timestamps and scores (not from the stored `hours_late`, which is rounded to 4 decimals).

## 7. The four injected anomalies

The baseline is built first and is valid. Anomalies are then added so that only the labelled records change; a diff against the baseline proves this.

| Issue type | How it is injected | Count (full / starter) |
|---|---|---|
| `unenrolled_submission` | A new, otherwise valid submission (file, grade, scores, feedback, event) for a learner with no enrollment in the course | 25 / 3 |
| `grade_exceeds_max` | One criterion score is raised so the final score passes the assignment maximum; totals and the grade event are kept consistent | 25 / 3 |
| `double_late_penalty` | Penalty points are deducted twice; the percentage is unchanged | 25 / 3 |
| `appeal_without_audit` | The `appeal_adjustment` event of an upheld appeal is removed | 25 / 1 |

The baseline holds 25 (starter: 3) fewer submissions, and exactly that many unenrolled submissions are added back, so the delivered dataset has exactly 30,000 (starter: 800) submissions. Labels live only in `ground_truth.csv/json`, outside the `csv/` and `json/` table folders. No table has a label column, and every table is sorted by primary key so injected rows cannot be found by position.

## 7a. Key decisions and trade-offs

- **SQLite with few CHECK constraints.** `schema.sql` enforces keys, foreign keys and enum values. Business rules (score within maximum, learner enrolled, penalty applied once, audit row present) are checked by the validator, because the injected rows must still load.
- **Standard library only.** No install problems for a reviewer; the cost is a little more code than pandas would need.
- **`grade` holds current values, `grade_event` holds history.** Simpler queries than versioned grade rows, at the cost of not keeping criterion-level history (see limitations).
- **Appeals and resubmissions are exclusive routes.** Keeps every grade change explainable by exactly one cause.
- **Hidden quality drives both grading and appeals.** Outcomes are consistent with each other without being independently random.
- **Compressed full dataset in the repository.** The unzipped full dataset is about 180 MB (the SQL file alone is 54 MB), too large for comfortable use on GitHub. The compressed `outputs/full.zip` is about 21 MB and the starter dataset (about 5 MB) is committed unzipped.

## 8. Testing and validation

`validator/validate.py` runs 39 checks in eight groups (keys, joins, values, dates, arithmetic, lifecycle, duplicates and the four anomaly detectors). Detection never reads the ground truth; it is read afterwards only to score the validator.

| Dataset | Assertions | Findings | Result |
|---|---:|---:|---|
| starter baseline | 75,508 | 0 | clean |
| starter (injected) | 75,698 | 11 | all 10 labelled anomalies found, 0 unexpected |
| full baseline | 2,700,002 | 0 | clean |
| full (injected) | 2,701,455 | 125 | all 100 labelled anomalies found, 0 unexpected |

Precision and recall are 1.0 for each anomaly type. This is partly in-sample, because the injection and the detectors were written together. To test beyond that, the clean data was also broken six unrelated ways (missing parent row, duplicate key, invalid status, wrong total, wrong due time, submission before publication) and the validator flagged all of them. That test was run by hand and is not part of the repository.

Other checks run on every generation: the data is loaded into SQLite from `schema.sql` with foreign keys enforced; the generator modules each contain a self-check that runs the generation twice and asserts identical output.

**Reproducibility (`validator/reproducibility.py`).** The generator runs twice with the seed and once with a different seed. All 31 output files have identical SHA-256 checksums across the two same-seed runs and all 31 differ in the control run, at both scales. The starter dataset was also generated on the author's Windows laptop and in a separate Linux environment with identical checksums for all files.

## 9. Resulting distributions (full dataset, as generated)

- Submissions: 30,000; 14.6% late; 1,277 still ungraded (grade date after the as-of date); 28,075 finalized.
- Final scores: mean 67.5%, median 71.0%, 28.2% below 60%; 775 zero scores (no readable file).
- Late penalties: 24,440 grades with none, then 1,285 / 966 / 749 / 559 / 724 at 10 / 20 / 30 / 40 / 50%.
- Files: 45,617 present, 1,460 missing, 480 corrupt.
- Resubmissions: 2,523 (2,302 graded, 166 cancelled, 55 pending). Appeals: 1,152 (201 upheld, 931 rejected, 20 pending).
- Boundary cases: about 1% of submissions are placed exactly at the deadline or one second after it.

## 10. Limitations

- Distributions are assumptions chosen by me, not measured from real institutions.
- Only the current criterion scores are stored. The grade history stores total scores, so a criterion-level before/after view is not available.
- A single global late-penalty and resubmission policy; no per-course policy variation.
- Appeals can only raise a grade; a reviewer never lowers one.
- `support_staff` and `platform_admin` are allowed values but never appear as actors, and the `planned` course status does not occur at the chosen as-of date.
- The event IDs of the injected unenrolled submissions are the highest numbers, so an event ID could hint at an injected row. IDs must not be used as features.
- The starter dataset has only one `appeal_without_audit` example because it has only two upheld appeals (half are kept clean).
- Precision and recall on the injected anomalies is partly in-sample, as explained in section 8.

## 11. Possible next steps

- Add a criterion-level history table for grade changes.
- Support per-course policies and more actor roles (support staff, platform administrator).
- Add a small automated test suite (including the unrelated-corruption test) and run it in CI.
- Calibrate score, lateness and appeal rates against a public education dataset, with its licence and provenance recorded in the source manifest.