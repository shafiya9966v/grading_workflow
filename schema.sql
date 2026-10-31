-- schema.sql : assignment / rubric grading workflow (synthetic data)
-- Dialect: SQLite (standard SQL where possible).
-- Timestamps: TEXT, ISO-8601 in UTC, e.g. 2026-03-14T18:29:00Z
-- Scores: REAL rounded to 2 decimals (validator compares with 0.01 tolerance)
--
-- DESIGN NOTE: this file enforces keys, foreign keys and enum values only.
-- Business rules (score <= rubric max, learner must be enrolled, penalty applied
-- once, audit row exists for grade changes) are checked by validator/, NOT by
-- CHECK constraints, because the injected anomaly rows must still be loadable.

PRAGMA foreign_keys = ON;

-- ---------- master data ----------

CREATE TABLE course (
    course_id       TEXT PRIMARY KEY,                 -- CRS-2026-0001
    course_code     TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    instructor_ref  TEXT NOT NULL,                    -- INS-0001 (no instructor table; simplification)
    start_date      TEXT NOT NULL,                    -- YYYY-MM-DD
    end_date        TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('planned','active','completed'))
);

CREATE TABLE learner (
    learner_id      TEXT PRIMARY KEY,                 -- LRN-000001
    full_name       TEXT NOT NULL,                    -- synthetic
    email           TEXT NOT NULL UNIQUE,             -- synthetic, @example.edu
    created_at_utc  TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('active','inactive'))
);

CREATE TABLE enrollment (                             -- bridge: course <-> learner (N:M)
    enrollment_id   TEXT PRIMARY KEY,                 -- ENR-<course_id>-<learner_id>
    course_id       TEXT NOT NULL REFERENCES course(course_id),
    learner_id      TEXT NOT NULL REFERENCES learner(learner_id),
    enrolled_from   TEXT NOT NULL,                    -- YYYY-MM-DD
    enrolled_to     TEXT,                             -- NULL = still enrolled
    status          TEXT NOT NULL CHECK (status IN ('active','dropped','completed')),
    UNIQUE (course_id, learner_id)
);

CREATE TABLE assignment (
    assignment_id         TEXT PRIMARY KEY,           -- ASN-2026-000001
    course_id             TEXT NOT NULL REFERENCES course(course_id),
    title                 TEXT NOT NULL,
    max_score             REAL NOT NULL,              -- points
    published_at_utc      TEXT NOT NULL,
    due_at_utc            TEXT NOT NULL,
    due_timezone          TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    resubmission_allowed  INTEGER NOT NULL CHECK (resubmission_allowed IN (0,1)),
    status                TEXT NOT NULL CHECK (status IN ('draft','published','closed'))
);

CREATE TABLE rubric (
    rubric_id          TEXT PRIMARY KEY,              -- RUB-<assignment_id>-01
    assignment_id      TEXT NOT NULL REFERENCES assignment(assignment_id),
    rubric_no          INTEGER NOT NULL,              -- 1 in baseline data
    total_max_points   REAL NOT NULL,                 -- should equal sum of criteria
    effective_from_utc TEXT NOT NULL,
    UNIQUE (assignment_id, rubric_no)
);

CREATE TABLE rubric_criterion (
    criterion_id    TEXT PRIMARY KEY,                 -- <rubric_id>-C01
    rubric_id       TEXT NOT NULL REFERENCES rubric(rubric_id),
    criterion_no    INTEGER NOT NULL,
    name            TEXT NOT NULL,
    max_points      REAL NOT NULL,
    UNIQUE (rubric_id, criterion_no)
);

-- ---------- transactions ----------

CREATE TABLE submission (
    submission_id   TEXT PRIMARY KEY,                 -- SUB-<assignment_id>-<learner_id>-01
    assignment_id   TEXT NOT NULL REFERENCES assignment(assignment_id),
    learner_id      TEXT NOT NULL REFERENCES learner(learner_id),
    attempt_no      INTEGER NOT NULL DEFAULT 1,
    submitted_at_utc TEXT NOT NULL,
    is_late         INTEGER NOT NULL CHECK (is_late IN (0,1)),   -- derived from due_at_utc
    hours_late      REAL NOT NULL DEFAULT 0,                     -- derived
    status          TEXT NOT NULL CHECK (status IN ('submitted','graded','resubmitted','finalized')),
    UNIQUE (assignment_id, learner_id)
);

CREATE TABLE resubmission (
    resubmission_id   TEXT PRIMARY KEY,               -- RSB-<submission_id>-01
    submission_id     TEXT NOT NULL REFERENCES submission(submission_id),
    requested_at_utc  TEXT NOT NULL,
    submitted_at_utc  TEXT,                           -- NULL until the new file arrives
    status            TEXT NOT NULL CHECK (status IN ('requested','submitted','graded','cancelled'))
);

CREATE TABLE submission_artifact (
    artifact_id       TEXT PRIMARY KEY,               -- ART-<submission_id>-01
    submission_id     TEXT NOT NULL REFERENCES submission(submission_id),
    resubmission_id   TEXT REFERENCES resubmission(resubmission_id),  -- NULL = original upload
    file_name         TEXT NOT NULL,
    file_type         TEXT NOT NULL,
    file_size_bytes   INTEGER NOT NULL,
    sha256            TEXT,
    file_status       TEXT NOT NULL CHECK (file_status IN ('present','missing','corrupt')),
    uploaded_at_utc   TEXT NOT NULL
);

CREATE TABLE grade (
    grade_id              TEXT PRIMARY KEY,           -- GRD-<submission_id>
    submission_id         TEXT NOT NULL UNIQUE REFERENCES submission(submission_id),
    raw_total             REAL NOT NULL,              -- sum of criterion scores
    late_penalty_pct      REAL NOT NULL DEFAULT 0,
    late_penalty_points   REAL NOT NULL DEFAULT 0,
    final_score           REAL NOT NULL,              -- raw_total - late_penalty_points
    graded_at_utc         TEXT NOT NULL,
    graded_by             TEXT NOT NULL,              -- INS-0001
    status                TEXT NOT NULL CHECK (status IN ('released','revised','final'))
);

CREATE TABLE grade_criterion_score (                  -- bridge: grade <-> rubric_criterion
    grade_id        TEXT NOT NULL REFERENCES grade(grade_id),
    criterion_id    TEXT NOT NULL REFERENCES rubric_criterion(criterion_id),
    score           REAL NOT NULL,
    PRIMARY KEY (grade_id, criterion_id)
);

CREATE TABLE feedback (
    feedback_id     TEXT PRIMARY KEY,                 -- FBK-<grade_id>-01
    grade_id        TEXT NOT NULL REFERENCES grade(grade_id),
    criterion_id    TEXT REFERENCES rubric_criterion(criterion_id),  -- NULL = overall comment
    comment_text    TEXT NOT NULL,
    author_ref      TEXT NOT NULL,
    created_at_utc  TEXT NOT NULL
);

CREATE TABLE appeal (
    appeal_id         TEXT PRIMARY KEY,               -- APP-2026-000001
    submission_id     TEXT NOT NULL REFERENCES submission(submission_id),
    grade_id          TEXT NOT NULL REFERENCES grade(grade_id),
    filed_at_utc      TEXT NOT NULL,
    reason_category   TEXT NOT NULL CHECK (reason_category IN ('rubric_misapplied','calculation_error','late_penalty_dispute','other')),
    status            TEXT NOT NULL CHECK (status IN ('filed','under_review','upheld','rejected')),
    decided_at_utc    TEXT,                           -- NULL until decided
    original_score    REAL NOT NULL,
    revised_score     REAL,                           -- NULL unless upheld
    decision_notes    TEXT
);

-- append-only history of every grade change (never updated or deleted)
CREATE TABLE grade_event (
    event_id          TEXT PRIMARY KEY,               -- EVT-2026-000001
    grade_id          TEXT NOT NULL REFERENCES grade(grade_id),
    event_type        TEXT NOT NULL CHECK (event_type IN ('initial_grade','resubmission_regrade','appeal_adjustment')),
    old_score         REAL,                           -- NULL for initial_grade
    new_score         REAL NOT NULL,
    event_at_utc      TEXT NOT NULL,
    actor_role        TEXT NOT NULL CHECK (actor_role IN ('instructor','academic_admin','support_staff','platform_admin')),
    actor_ref         TEXT NOT NULL,
    appeal_id         TEXT REFERENCES appeal(appeal_id),
    resubmission_id   TEXT REFERENCES resubmission(resubmission_id),
    reason            TEXT
);

-- ---------- indexes on foreign keys ----------
CREATE INDEX idx_enrollment_learner   ON enrollment(learner_id);
CREATE INDEX idx_assignment_course    ON assignment(course_id);
CREATE INDEX idx_submission_learner   ON submission(learner_id);
CREATE INDEX idx_artifact_submission  ON submission_artifact(submission_id);
CREATE INDEX idx_event_grade          ON grade_event(grade_id);
CREATE INDEX idx_appeal_submission    ON appeal(submission_id);