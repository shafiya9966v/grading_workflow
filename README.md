# Assignment Grading Workflow: Synthetic Data Generator

A reproducible generator for synthetic data about an assignment and rubric-grading workflow: courses, learners, enrollments, assignments, rubrics, submissions, files, grades, feedback, resubmissions and appeals. It injects labelled anomalies, validates the data, and proves reproducibility with a fixed seed.

All data is synthetic. No external datasets and no real personal data are used.

- **Design, rules and trade-offs:** [Design.md](Design.md)
- **Every table and field:** [docs/data_dictionary.md](docs/data_dictionary.md)
- **How AI tools were used:** [AI_usage.md](AI_usage.md), prompts in [docs/prompts/](docs/prompts/)

## Requirements

- Python 3.10 or newer (check with `python --version`)
- No third-party packages (standard library only)

## Quick start

Run everything from the project folder.

```bash
# 1. clone and enter the repository
git clone <repo-url>
cd <repo-folder>

# 2. small dataset (about 1 second), plus the clean baseline it was built from
python generator/generate.py --seed 20261022 --scale starter --out outputs/starter --baseline-out outputs/starter_baseline

# 3. validate both
python validator/validate.py --dataset outputs/starter_baseline     # expect: clean, no findings
python validator/validate.py --dataset outputs/starter              # expect: all injected anomalies found

# 4. prove reproducibility (runs the generator twice with the same seed and once with another)
python validator/reproducibility.py --scale starter
```

Full required volume (1,000 assignments, 10,000 learners, 30,000 submissions; about 30 seconds):

```bash
python generator/generate.py --seed 20261022 --scale full --out outputs/full --baseline-out outputs/full_baseline --zip
python validator/validate.py --dataset outputs/full_baseline
python validator/validate.py --dataset outputs/full
python validator/reproducibility.py --scale full
```

Reports are written to `reports/` (`.md` for reading, `.json` for tools).

### Command options (`generator/generate.py`)

| Option | Meaning |
|---|---|
| `--seed` | Random seed (default `20261022`) |
| `--scale starter\|full` | Dataset size. Both use the same generator code. |
| `--out` | Output folder for the injected dataset (default `outputs/<scale>`) |
| `--baseline-out` | Also write the clean dataset (before anomalies were injected) |
| `--zip` | Also write `<out>.zip` (byte-for-byte reproducible) |
| `--skip-load-check` | Skip the SQLite load check |

Every run loads the data into an in-memory SQLite database built from `schema.sql` with foreign keys enforced, so a broken join or a column mismatch stops the run.

### Load the seed data into SQLite yourself (optional)

```bash
python -c "import sqlite3; c=sqlite3.connect('demo.db'); c.executescript(open('schema.sql', encoding='utf-8').read()); c.executescript(open('outputs/starter/sql/seed.sql', encoding='utf-8').read()); print('loaded')"
```

`demo.db` is ignored by git.

## What each run produces

```
outputs/<name>/
  csv/<table>.csv         14 tables (an empty cell means NULL)
  json/<table>.json       the same 14 tables (null means NULL)
  sql/seed.sql            INSERT statements, parents before children (load schema.sql first)
  ground_truth.csv/.json  the labelled anomalies, kept OUTSIDE the table folders
  manifest.json           seed, scale, row counts and a SHA-256 checksum of every file
```

The baseline folder has the same layout without `ground_truth`.

## Volumes

| | starter | full |
|---|---:|---:|
| Courses / learners | 20 / 300 | 400 / 10,000 |
| Assignments (= rubrics) | 50 | 1,000 |
| Submissions (including injected) | 800 | 30,000 |
| Rubric criteria | 200 | 3,994 |
| Enrollments | 506 | 17,087 |
| Grades / criterion scores | 800 / 3,214 | 28,723 / 114,733 |
| Resubmissions / appeals | 86 / 23 | 2,523 / 1,152 |
| Grade events | 877 | 31,201 |
| Files on disk | 5.1 MB | 182 MB (21 MB zipped) |

Ungraded submissions are those whose grade date falls after the fixed as-of date (2026-10-15).

## Injected anomalies and ground truth

| Issue type | Meaning | Full / starter |
|---|---|---:|
| `unenrolled_submission` | Submission by a learner not enrolled in the course | 25 / 3 |
| `grade_exceeds_max` | A score exceeds its criterion or the assignment maximum | 25 / 3 |
| `double_late_penalty` | Late penalty deducted twice | 25 / 3 |
| `appeal_without_audit` | Appeal upheld and grade changed, but no history event | 25 / 1 |

Each row of `ground_truth.csv` gives the anomaly ID, issue type, table, record ID, what a validator should report, and what was changed. The tables contain no label column, so the answer key cannot leak into input features.

## Results

| Dataset | Assertions | Findings | Result |
|---|---:|---:|---|
| starter baseline | 75,508 | 0 | clean |
| starter | 75,698 | 11 | all 10 labelled anomalies found, 0 unexpected |
| full baseline | 2,700,002 | 0 | clean |
| full | 2,701,455 | 125 | all 100 labelled anomalies found, 0 unexpected |

Reproducibility: two runs with the same seed give identical SHA-256 checksums for all 31 output files at both scales, and a run with a different seed differs in all 31. Dataset fingerprints (a SHA-256 over every file's checksum):

- starter: `2806a4c142016a8ecd51bb1d01fc267bad9c4f8a52d2b7d28a493be5ffdba623`
- full: `c10130716b4d55349e9eeae43a976cc5da12c97a7490aa872641567796604884`

The starter dataset was also generated on the author's Windows laptop and in a separate Linux environment, with identical checksums.

## Committed outputs

- `outputs/starter/` and `outputs/starter_baseline/` (about 5 MB each, unzipped)
- `outputs/full.zip` (about 21 MB). The unzipped full dataset (about 180 MB) is git-ignored: regenerate it with the command above, or unzip `full.zip`.
- `reports/`: validation and reproducibility reports for both scales

## Repository layout

```
README.md  Design.md  AI_usage.md  requirements.txt  schema.sql
docs/data_dictionary.md          every table and field
docs/prompts/                    full prompt history
generator/
  config.py                      seed, scales, business rules, behaviour rates
  ids.py  timeutil.py            ID formats, UTC and India-time helpers
  master.py                      courses, learners, enrollments, assignments, rubrics, criteria
  transactions.py                submissions, files, grades, feedback, initial events
  lifecycle.py                   resubmissions, appeals, grade changes, final statuses
  inject.py                      the four labelled anomalies
  generate.py                    command-line entry point and file writers
validator/
  validate.py                    39 checks, anomaly detection, scoring against the ground truth
  reproducibility.py             same-seed comparison with a different-seed control
outputs/  reports/
```

Each generator module can also be run on its own (for example `python generator/master.py starter`); it runs a short self-check and prints row counts.

## Source manifest

No external data is used. Everything is generated by the code in this repository. If external reference data were added, its URL, version, retrieval date, licence, transformations and discarded fields would be listed here.

## Known limitations

See section 10 of [Design.md](Design.md). The main ones: distributions are assumptions rather than measurements, only current criterion scores are stored (history keeps totals), a submission has one route (resubmission or appeal), and detection scores on the injected anomalies are partly in-sample.