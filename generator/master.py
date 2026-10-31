"""Master data: courses, learners, enrollments, assignments, rubrics, rubric criteria.

Parents are always generated before children, so every foreign key points to a row
that already exists. Each row is a dict whose keys match the columns in schema.sql.

Reproducibility: one random.Random(seed) drives everything, rows are produced in a
fixed order, and nothing uses the real clock or set/dict-hash ordering.
"""
import random
import sys
from datetime import date, datetime, timedelta, timezone

import config
import ids
from timeutil import ist_to_utc, to_ts

DEPARTMENTS = ["CS", "DS", "AI", "EE", "MA", "PH", "CE", "BA"]
TOPICS = [
    "Programming Fundamentals", "Data Structures", "Algorithms", "Database Systems",
    "Operating Systems", "Computer Networks", "Machine Learning", "Statistics",
    "Linear Algebra", "Software Engineering", "Web Development", "Cloud Computing",
    "Cybersecurity", "Digital Electronics", "Signal Processing", "Discrete Mathematics",
    "Human-Computer Interaction", "Data Visualisation",
]
LEVELS = ["Introduction to", "Applied", "Advanced", "Principles of"]
ASSIGNMENT_KINDS = ["Lab", "Project", "Problem Set", "Case Study", "Report"]
CRITERION_POOL = [
    "Correctness", "Code quality", "Documentation", "Testing",
    "Efficiency", "Design", "Presentation", "Originality",
]
# Synthetic names only. A combination may match a real person by pure chance.
FIRST_NAMES = [
    "Aarav", "Anaya", "Rohan", "Meera", "Karthik", "Sneha", "Vikram", "Divya", "Arjun", "Pooja",
    "Nikhil", "Isha", "Rahul", "Kavya", "Sanjay", "Lakshmi", "Varun", "Priya", "Manoj", "Tanvi",
    "Harsha", "Nandini", "Ravi", "Swathi", "Deepak", "Anjali", "Suresh", "Bhavana", "Imran", "Zoya",
]
LAST_NAMES = [
    "Reddy", "Sharma", "Rao", "Iyer", "Patel", "Naidu", "Khan", "Gupta", "Kumar", "Nair",
    "Das", "Verma", "Menon", "Singh", "Chowdary", "Joshi", "Mehta", "Bose", "Pillai", "Shaik",
    "Varma", "Yadav", "Prasad", "Murthy", "Ahmed", "Fernandes", "Thomas", "Banerjee", "Kapoor", "Sethi",
]

LEARNER_CREATED_FROM = datetime(2025, 6, 1, tzinfo=timezone.utc)
LEARNER_CREATED_TO = datetime(2026, 1, 4, tzinfo=timezone.utc)


def weighted_choice(rng: random.Random, mapping: dict):
    """Pick a key of mapping using its values as probabilities (stable order)."""
    keys = list(mapping)
    weights = [mapping[k] for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def split_points(rng: random.Random, total: float, k: int) -> list:
    """Split `total` points into k positive criteria in steps of 0.5.

    The last criterion takes the remainder, so the parts add up to `total` exactly.
    (Steps of 0.5 are exact in binary floating point, so no rounding drift.)
    """
    weights = [rng.randint(1, 4) for _ in range(k)]
    s = sum(weights)
    parts = [round(total * w / s * 2) / 2 for w in weights[:-1]]
    last = total - sum(parts)
    assert last > 0, "criterion split produced a non-positive remainder"
    return parts + [last]


# ------------------------------------------------------------------ courses
def generate_courses(rng, scale):
    n_instructors = max(5, scale.n_courses // 4)
    span = (config.TERM_END - config.TERM_START).days
    as_of = config.AS_OF.date()
    rows = []
    for n in range(1, scale.n_courses + 1):
        dept = rng.choice(DEPARTMENTS)
        weeks = rng.randint(12, 16)
        start = config.TERM_START + timedelta(days=rng.randint(0, span - weeks * 7))
        end = start + timedelta(days=weeks * 7)
        if start > as_of:
            status = "planned"
        elif end < as_of:
            status = "completed"
        else:
            status = "active"
        rows.append({
            "course_id": ids.course_id(n),
            "course_code": f"{dept}{100 + n}",          # number is unique, so code is unique
            "title": f"{rng.choice(LEVELS)} {rng.choice(TOPICS)}",
            "instructor_ref": f"INS-{rng.randint(1, n_instructors):04d}",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "status": status,
        })
    return rows


# ------------------------------------------------------------------ learners
def generate_learners(rng, scale):
    window = int((LEARNER_CREATED_TO - LEARNER_CREATED_FROM).total_seconds())
    rows = []
    for n in range(1, scale.n_learners + 1):
        created = LEARNER_CREATED_FROM + timedelta(seconds=rng.randint(0, window))
        inactive = rng.random() < config.INACTIVE_LEARNER_RATE
        rows.append({
            "learner_id": ids.learner_id(n),
            "full_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "email": f"learner{n:06d}@example.edu",       # counter makes it unique
            "created_at_utc": to_ts(created),
            "status": "inactive" if inactive else "active",
        })
    return rows


# ------------------------------------------------------------------ enrollments
def generate_enrollments(rng, scale, courses, learners):
    as_of = config.AS_OF.date()
    rows = []
    for learner in learners:
        k = min(weighted_choice(rng, config.ENROLMENTS_PER_LEARNER), len(courses))
        for idx in sorted(rng.sample(range(len(courses)), k)):
            course = courses[idx]
            c_start = date.fromisoformat(course["start_date"])
            enrolled_from = c_start + timedelta(days=rng.randint(0, 14))

            dropped = rng.random() < config.DROP_RATE
            drop_date = enrolled_from + timedelta(days=rng.randint(14, 60))
            if drop_date > as_of:        # a drop cannot happen after the as-of date
                dropped = False

            if dropped:
                status, enrolled_to = "dropped", drop_date.isoformat()
            elif course["status"] == "completed":
                status, enrolled_to = "completed", course["end_date"]
            else:
                status, enrolled_to = "active", None

            rows.append({
                "enrollment_id": ids.enrollment_id(course["course_id"], learner["learner_id"]),
                "course_id": course["course_id"],
                "learner_id": learner["learner_id"],
                "enrolled_from": enrolled_from.isoformat(),
                "enrolled_to": enrolled_to,
                "status": status,
            })
    return rows


# ------------------------------------------------------------------ assignments, rubrics, criteria
def generate_assignments(rng, scale, courses):
    as_of = config.AS_OF
    per_course = {c["course_id"]: 0 for c in courses}
    assignments, rubrics, criteria = [], [], []

    for n in range(1, scale.n_assignments + 1):
        # first pass gives every course at least one assignment; the rest are random
        course = courses[n - 1] if n <= len(courses) else rng.choice(courses)
        cid = course["course_id"]
        per_course[cid] += 1

        c_start = date.fromisoformat(course["start_date"])
        c_end = date.fromisoformat(course["end_date"])
        duration = (c_end - c_start).days
        pub_date = c_start + timedelta(days=rng.randint(0, duration - 22))
        due_date = pub_date + timedelta(days=rng.randint(7, 21))      # always <= course end
        published = ist_to_utc(pub_date, 9, 0)                          # 09:00 IST
        due = ist_to_utc(due_date, config.DUE_LOCAL_HOUR, config.DUE_LOCAL_MINUTE)

        if published > as_of:
            status = "draft"
        elif due < as_of:
            status = "closed"
        else:
            status = "published"

        max_score = weighted_choice(rng, config.MAX_SCORE_CHOICES)
        asn = ids.assignment_id(n)
        assignments.append({
            "assignment_id": asn,
            "course_id": cid,
            "title": f"{course['course_code']} {rng.choice(ASSIGNMENT_KINDS)} {per_course[cid]}",
            "max_score": max_score,
            "published_at_utc": to_ts(published),
            "due_at_utc": to_ts(due),
            "due_timezone": "Asia/Kolkata",
            "resubmission_allowed": 1 if rng.random() < 0.6 else 0,
            "status": status,
        })

        rub = ids.rubric_id(asn, 1)
        k = rng.choice(config.CRITERIA_PER_RUBRIC)
        names = rng.sample(CRITERION_POOL, k)
        points = split_points(rng, max_score, k)
        rubrics.append({
            "rubric_id": rub,
            "assignment_id": asn,
            "rubric_no": 1,
            "total_max_points": sum(points),          # derived from the criteria
            "effective_from_utc": to_ts(published - timedelta(days=1)),
        })
        for i, (name, pts) in enumerate(zip(names, points), start=1):
            criteria.append({
                "criterion_id": ids.criterion_id(rub, i),
                "rubric_id": rub,
                "criterion_no": i,
                "name": name,
                "max_points": pts,
            })
    return assignments, rubrics, criteria


# ------------------------------------------------------------------ entry point
def generate_master(scale, seed=config.SEED):
    """Generate all master tables. Returns {table_name: [row dicts]}."""
    rng = random.Random(seed)
    courses = generate_courses(rng, scale)
    learners = generate_learners(rng, scale)
    enrollments = generate_enrollments(rng, scale, courses, learners)
    assignments, rubrics, criteria = generate_assignments(rng, scale, courses)
    return {
        "course": courses,
        "learner": learners,
        "enrollment": enrollments,
        "assignment": assignments,
        "rubric": rubrics,
        "rubric_criterion": criteria,
    }


# ------------------------------------------------------------------ quick self-check
def _self_check(tables):
    def pks(name, col):
        values = [r[col] for r in tables[name]]
        assert len(values) == len(set(values)), f"duplicate primary key in {name}"
        return set(values)

    course_ids = pks("course", "course_id")
    learner_ids = pks("learner", "learner_id")
    pks("enrollment", "enrollment_id")
    asn_ids = pks("assignment", "assignment_id")
    rub_ids = pks("rubric", "rubric_id")
    pks("rubric_criterion", "criterion_id")

    assert all(e["course_id"] in course_ids and e["learner_id"] in learner_ids
               for e in tables["enrollment"]), "enrollment FK broken"
    assert all(a["course_id"] in course_ids for a in tables["assignment"]), "assignment FK broken"
    assert all(r["assignment_id"] in asn_ids for r in tables["rubric"]), "rubric FK broken"
    assert all(c["rubric_id"] in rub_ids for c in tables["rubric_criterion"]), "criterion FK broken"

    # rubric totals reconcile to the criteria and to the assignment maximum
    max_by_asn = {a["assignment_id"]: a["max_score"] for a in tables["assignment"]}
    sums = {}
    for c in tables["rubric_criterion"]:
        sums[c["rubric_id"]] = sums.get(c["rubric_id"], 0) + c["max_points"]
    for r in tables["rubric"]:
        assert sums[r["rubric_id"]] == r["total_max_points"] == max_by_asn[r["assignment_id"]], \
            f"rubric total mismatch for {r['rubric_id']}"
    for a in tables["assignment"]:
        assert a["published_at_utc"] < a["due_at_utc"], "due date before publish date"


if __name__ == "__main__":
    # Run: python generator/master.py [starter|full]
    scale_name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    scale = config.get_scale(scale_name)
    first = generate_master(scale)
    second = generate_master(scale)
    assert first == second, "same seed produced different data"
    _self_check(first)
    for name, rows in first.items():
        print(f"{name:18} {len(rows):>7} rows")
    print("master OK (checks passed, same seed gives identical data)")