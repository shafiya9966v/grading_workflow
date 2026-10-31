# Data dictionary

Conventions used everywhere:

- All timestamps are `TEXT`, ISO-8601, **UTC**, ending in `Z` (example `2026-03-14T18:29:00Z`).
- All dates are `YYYY-MM-DD`.
- Scores are `REAL`, in **points**, rounded to 2 decimals. Reconciliation uses a 0.01 tolerance.
- "Req" = required (NOT NULL). "Unique" = unique across the table.
- IDs are immutable and zero-padded. A foreign key must match its parent ID exactly.
- All people and content are synthetic. No real personal data is used.

## Relationship summary

| Parent | Child | Cardinality | Optional? |
|---|---|---|---|
| course | enrollment | 1:N | no |
| learner | enrollment | 1:N | no |
| course <-> learner | via enrollment | N:M | |
| course | assignment | 1:N | no |
| assignment | rubric | 1:N (1:1 in baseline data) | no |
| rubric | rubric_criterion | 1:N | no |
| assignment | submission | 1:N | no |
| learner | submission | 1:N | no |
| submission | submission_artifact | 1:N | an artifact may be missing (`file_status`) |
| submission | grade | 1:1 | yes, until graded |
| grade <-> rubric_criterion | via grade_criterion_score | N:M | |
| grade | feedback | 1:N | yes |
| submission | resubmission | 1:N (policy allows max 1) | yes |
| submission | appeal | 1:N (policy allows max 1) | yes |
| grade | grade_event | 1:N | no (at least `initial_grade`) |

## course

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| course_id | TEXT (PK) | yes | `CRS-2026-NNNN` | yes | matches pattern, zero-padded |
| course_code | TEXT | yes | e.g. `CS101` | yes | non-empty |
| title | TEXT | yes | free text | no | non-empty |
| instructor_ref | TEXT | yes | `INS-NNNN` | no | no instructor table (simplification) |
| start_date | TEXT | yes | date | no | <= end_date |
| end_date | TEXT | yes | date | no | >= start_date |
| status | TEXT | yes | planned, active, completed | no | enum |

## learner

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| learner_id | TEXT (PK) | yes | `LRN-NNNNNN` | yes | matches pattern |
| full_name | TEXT | yes | synthetic name | no | non-empty |
| email | TEXT | yes | `...@example.edu` | yes | synthetic domain only |
| created_at_utc | TEXT | yes | UTC timestamp | no | valid timestamp |
| status | TEXT | yes | active, inactive | no | enum |

## enrollment (bridge: course <-> learner)

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| enrollment_id | TEXT (PK) | yes | `ENR-<course_id>-<learner_id>` | yes | equals its parts |
| course_id | TEXT (FK) | yes | existing course | no | FK valid |
| learner_id | TEXT (FK) | yes | existing learner | no | FK valid |
| enrolled_from | TEXT | yes | date | no | within course dates |
| enrolled_to | TEXT | no | date or NULL | no | >= enrolled_from; NULL = still enrolled |
| status | TEXT | yes | active, dropped, completed | no | enum; dropped/completed need enrolled_to |

Unique pair: (course_id, learner_id).

## assignment

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| assignment_id | TEXT (PK) | yes | `ASN-2026-NNNNNN` | yes | matches pattern |
| course_id | TEXT (FK) | yes | existing course | no | FK valid |
| title | TEXT | yes | free text | no | non-empty |
| max_score | REAL | yes | points, > 0 (baseline 100) | no | equals rubric total |
| published_at_utc | TEXT | yes | UTC timestamp | no | < due_at_utc |
| due_at_utc | TEXT | yes | UTC timestamp | no | > published_at_utc |
| due_timezone | TEXT | yes | `Asia/Kolkata` | no | display zone only |
| resubmission_allowed | INTEGER | yes | 0 or 1 | no | enum |
| status | TEXT | yes | draft, published, closed | no | enum |

## rubric

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| rubric_id | TEXT (PK) | yes | `RUB-<assignment_id>-NN` | yes | equals its parts |
| assignment_id | TEXT (FK) | yes | existing assignment | no | FK valid |
| rubric_no | INTEGER | yes | >= 1 | no | matches `NN` in ID |
| total_max_points | REAL | yes | points | no | = sum of criterion max_points |
| effective_from_utc | TEXT | yes | UTC timestamp | no | <= assignment published_at_utc |

Unique pair: (assignment_id, rubric_no).

## rubric_criterion

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| criterion_id | TEXT (PK) | yes | `<rubric_id>-CNN` | yes | equals its parts |
| rubric_id | TEXT (FK) | yes | existing rubric | no | FK valid |
| criterion_no | INTEGER | yes | >= 1 | no | unique within rubric |
| name | TEXT | yes | e.g. Correctness | no | non-empty |
| max_points | REAL | yes | points, > 0 | no | sum over rubric = total |

## submission

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| submission_id | TEXT (PK) | yes | `SUB-<assignment_id>-<learner_id>-01` | yes | equals its parts |
| assignment_id | TEXT (FK) | yes | existing assignment | no | FK valid |
| learner_id | TEXT (FK) | yes | existing learner | no | FK valid; learner must be enrolled in the assignment's course |
| attempt_no | INTEGER | yes | 1 | no | original attempt is always 1 |
| submitted_at_utc | TEXT | yes | UTC timestamp | no | >= assignment published_at_utc |
| is_late | INTEGER | yes | 0 or 1 | no | = (submitted_at_utc > due_at_utc) |
| hours_late | REAL | yes | hours, >= 0 | no | 0 if not late |
| status | TEXT | yes | submitted, graded, resubmitted, finalized | no | enum; legal transitions in Design.md |

Unique pair: (assignment_id, learner_id).

## resubmission

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| resubmission_id | TEXT (PK) | yes | `RSB-<submission_id>-NN` | yes | equals its parts |
| submission_id | TEXT (FK) | yes | existing submission | no | FK valid; policy limits to 1 per submission |
| requested_at_utc | TEXT | yes | UTC timestamp | no | after the grade was released, within 7 days |
| submitted_at_utc | TEXT | no | UTC timestamp or NULL | no | >= requested_at_utc |
| status | TEXT | yes | requested, submitted, graded, cancelled | no | enum |

## submission_artifact

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| artifact_id | TEXT (PK) | yes | `ART-<submission_id>-NN` | yes | equals its parts |
| submission_id | TEXT (FK) | yes | existing submission | no | FK valid |
| resubmission_id | TEXT (FK) | no | existing resubmission or NULL | no | NULL = original upload |
| file_name | TEXT | yes | free text | no | non-empty |
| file_type | TEXT | yes | pdf, zip, py, ipynb, txt | no | enum |
| file_size_bytes | INTEGER | yes | bytes, >= 0 | no | 0 allowed only if file_status is missing/corrupt |
| sha256 | TEXT | no | 64 hex chars | no | NULL if missing |
| file_status | TEXT | yes | present, missing, corrupt | no | enum |
| uploaded_at_utc | TEXT | yes | UTC timestamp | no | equals the submission/resubmission time |

## grade

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| grade_id | TEXT (PK) | yes | `GRD-<submission_id>` | yes | equals its parts |
| submission_id | TEXT (FK) | yes | existing submission | yes | FK valid; 1:1 |
| raw_total | REAL | yes | points | no | = sum of grade_criterion_score |
| late_penalty_pct | REAL | yes | 0 to 50 | no | = min(50, 10 x ceil(hours_late / 24)) |
| late_penalty_points | REAL | yes | points | no | = round(raw_total x pct / 100, 2); applied once |
| final_score | REAL | yes | points, 0 to max_score | no | = raw_total - late_penalty_points |
| graded_at_utc | TEXT | yes | UTC timestamp | no | > submission time |
| graded_by | TEXT | yes | `INS-NNNN` | no | non-empty |
| status | TEXT | yes | released, revised, final | no | enum |

## grade_criterion_score (bridge: grade <-> rubric_criterion)

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| grade_id | TEXT (FK, PK part) | yes | existing grade | pair | FK valid |
| criterion_id | TEXT (FK, PK part) | yes | existing criterion | pair | must belong to this assignment's rubric |
| score | REAL | yes | points | no | 0 <= score <= criterion max_points |

Primary key: (grade_id, criterion_id).

## feedback

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| feedback_id | TEXT (PK) | yes | `FBK-<grade_id>-NN` | yes | equals its parts |
| grade_id | TEXT (FK) | yes | existing grade | no | FK valid |
| criterion_id | TEXT (FK) | no | existing criterion or NULL | no | NULL = overall comment |
| comment_text | TEXT | yes | free text | no | non-empty |
| author_ref | TEXT | yes | `INS-NNNN` | no | non-empty |
| created_at_utc | TEXT | yes | UTC timestamp | no | >= graded_at_utc |

## appeal

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| appeal_id | TEXT (PK) | yes | `APP-2026-NNNNNN` | yes | matches pattern |
| submission_id | TEXT (FK) | yes | existing submission | no | FK valid; policy limits to 1 per submission |
| grade_id | TEXT (FK) | yes | existing grade | no | must belong to the same submission |
| filed_at_utc | TEXT | yes | UTC timestamp | no | within 7 days of the grade release |
| reason_category | TEXT | yes | rubric_misapplied, calculation_error, late_penalty_dispute, other | no | enum |
| status | TEXT | yes | filed, under_review, upheld, rejected | no | legal transitions in Design.md |
| decided_at_utc | TEXT | no | UTC timestamp or NULL | no | required when upheld/rejected; >= filed_at_utc |
| original_score | REAL | yes | points | no | = grade final_score at filing time |
| revised_score | REAL | no | points or NULL | no | required when upheld; NULL otherwise |
| decision_notes | TEXT | no | free text | no | |

## grade_event (append-only history)

| Field | Type | Req | Allowed values / units | Unique | Validation rule |
|---|---|---|---|---|---|
| event_id | TEXT (PK) | yes | `EVT-2026-NNNNNN` | yes | matches pattern |
| grade_id | TEXT (FK) | yes | existing grade | no | FK valid |
| event_type | TEXT | yes | initial_grade, resubmission_regrade, appeal_adjustment | no | enum |
| old_score | REAL | no | points or NULL | no | NULL only for initial_grade |
| new_score | REAL | yes | points | no | |
| event_at_utc | TEXT | yes | UTC timestamp | no | events ordered in time per grade |
| actor_role | TEXT | yes | instructor, academic_admin, support_staff, platform_admin | no | enum |
| actor_ref | TEXT | yes | free text ID | no | non-empty |
| appeal_id | TEXT (FK) | no | existing appeal or NULL | no | required when appeal_adjustment |
| resubmission_id | TEXT (FK) | no | existing resubmission or NULL | no | required when resubmission_regrade |
| reason | TEXT | no | free text | no | |

Rule: the latest `new_score` for a grade must equal `grade.final_score`.

## ground_truth (separate file, not part of the schema above)

Stored as `ground_truth.csv`, never loaded as an input table.

| Field | Type | Req | Allowed values | Notes |
|---|---|---|---|---|
| record_table | TEXT | yes | table name | which table holds the bad row |
| record_id | TEXT | yes | the affected ID | |
| issue_type | TEXT | yes | unenrolled_submission, grade_exceeds_max, double_late_penalty, appeal_without_audit | the four required anomalies |
| expected_detection | TEXT | yes | short description | what a correct validator should report |