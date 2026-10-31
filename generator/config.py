"""Central configuration for the data generator.

Every *decision* lives here (seed, volumes, business rules, behaviour rates), so the
other files contain logic only and Design.md can point to one place.
Change a number here and the whole dataset follows. Keep Design.md in sync.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------- reproducibility
SEED = 20261022  # fixed seed required by the task

# ---------------------------------------------------------------- IDs and time
YEAR = 2026  # used in ASN-2026-..., APP-2026-..., CRS-2026-...

# India has no daylight saving, so a fixed +05:30 offset is exact.
# (Avoids the zoneinfo module, which needs an extra package on Windows.)
IST = timezone(timedelta(hours=5, minutes=30))
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"  # every stored timestamp is UTC and ends in Z

DUE_LOCAL_HOUR = 23    # assignments fall due at 23:59 India time
DUE_LOCAL_MINUTE = 59

TERM_START = date(2026, 1, 5)
TERM_END = date(2026, 12, 15)

# The "as of" moment for the data. Never use the real clock (datetime.now):
# that would make two runs with the same seed produce different data.
AS_OF = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- volumes
@dataclass(frozen=True)
class Scale:
    n_courses: int
    n_learners: int
    n_assignments: int
    n_submissions: int      # target; chosen only from (enrolled learner, assignment) pairs
    n_anomalies_each: int   # injected rows per anomaly type


SCALES = {
    # quick to generate and inspect while developing
    "starter": Scale(n_courses=20, n_learners=300, n_assignments=50,
                     n_submissions=800, n_anomalies_each=3),
    # sizes required by the task
    "full": Scale(n_courses=400, n_learners=10_000, n_assignments=1_000,
                  n_submissions=30_000, n_anomalies_each=25),
}

# How many courses each learner enrols in (value -> probability)
ENROLMENTS_PER_LEARNER = {1: 0.50, 2: 0.30, 3: 0.20}

# Rubric shape: number of criteria per rubric, and the assignment maximum score
CRITERIA_PER_RUBRIC = (3, 4, 5)
DEFAULT_MAX_SCORE = 100.0
MAX_SCORE_CHOICES = {100.0: 0.70, 50.0: 0.20, 25.0: 0.10}   # value -> probability

# Master-data behaviour rates
DROP_RATE = 0.05               # share of enrolments where the learner drops the course
INACTIVE_LEARNER_RATE = 0.03   # share of learners with status 'inactive'


# ---------------------------------------------------------------- business rules
# (documented in Design.md section 3)
PENALTY_PCT_PER_DAY = 10     # per started day late
PENALTY_CAP_PCT = 50

RESUBMISSION_THRESHOLD_PCT = 60   # only if original final score is below this % of max
RESUBMISSION_WINDOW_DAYS = 7      # request within this many days of grade release
RESUBMISSION_CAP_PCT = 80         # regraded score is capped at this % of max

APPEAL_WINDOW_DAYS = 7
APPEAL_UPHOLD_MARGIN_PCT = 5      # upheld if review score is this % of max (or more) higher


# ---------------------------------------------------------------- behaviour rates
# These only decide *who* does something. What happens next follows the rules above.
LATE_RATE = 0.15                  # share of submissions made after the deadline
MISSING_FILE_RATE = 0.03          # share of submissions with no readable file
UNGRADED_RATE = 0.05              # share of recent submissions not graded yet
RESUBMIT_RATE_WHEN_ELIGIBLE = 0.50
APPEAL_RATE = 0.06                # share of graded submissions that file an appeal


def get_scale(name: str) -> Scale:
    """Return the Scale for 'starter' or 'full', with a clear error otherwise."""
    try:
        return SCALES[name]
    except KeyError:
        raise ValueError(f"Unknown scale {name!r}. Choose from: {', '.join(SCALES)}") from None


if __name__ == "__main__":
    for scale_name, scale in SCALES.items():
        print(scale_name, scale)