"""Command-line entry point: generate the dataset and write all output files.

Usage (from the project folder):
    python generator/generate.py --seed 20261022 --scale starter --out outputs/starter
    python generator/generate.py --seed 20261022 --scale full    --out outputs/full --zip

Writes, inside --out:
    csv/<table>.csv      one file per table (empty cell = NULL)
    json/<table>.json    one file per table (null = NULL)
    sql/seed.sql         INSERT statements, parents first (load schema.sql first)
    ground_truth.csv/.json   the labelled anomalies (separate from the input tables)
    manifest.json        seed, scale, row counts and a SHA-256 checksum of every file
    <out>.zip            (only with --zip) the same files, compressed, byte-for-byte reproducible

Optional --baseline-out writes the CLEAN dataset (before anomalies were injected) in the same
format, so the validator can be shown passing on clean data and flagging the injected data.

Every run also loads the data into an in-memory SQLite database built from schema.sql
with foreign keys enforced, so a broken join or a column mismatch fails immediately.
"""
import argparse
import csv
import hashlib
import json
import sqlite3
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import config
from inject import GROUND_TRUTH_COLUMNS, ISSUE_TYPES, inject_anomalies
from lifecycle import generate_lifecycle
from master import generate_master
from transactions import generate_submissions

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"

# Parents before children, so foreign keys are always satisfied when loading.
TABLE_ORDER = [
    "course", "learner", "enrollment", "assignment", "rubric", "rubric_criterion",
    "submission", "resubmission", "submission_artifact", "grade", "grade_criterion_score",
    "feedback", "appeal", "grade_event",
]
SQL_BATCH_ROWS = 100


# ------------------------------------------------------------------ build
TABLE_KEYS = {   # primary key columns, used to give every table a stable, sorted row order
    "course": ("course_id",), "learner": ("learner_id",), "enrollment": ("enrollment_id",),
    "assignment": ("assignment_id",), "rubric": ("rubric_id",), "rubric_criterion": ("criterion_id",),
    "submission": ("submission_id",), "resubmission": ("resubmission_id",),
    "submission_artifact": ("artifact_id",), "grade": ("grade_id",),
    "grade_criterion_score": ("grade_id", "criterion_id"), "feedback": ("feedback_id",),
    "appeal": ("appeal_id",), "grade_event": ("event_id",),
}


def sort_tables(tables):
    """Sort every table by primary key, so injected rows cannot be spotted by their position."""
    for name, keys in TABLE_KEYS.items():
        tables[name].sort(key=lambda r: tuple(r[k] for k in keys))


def build_tables(scale, seed):
    """Run every generation step in order.

    Returns (baseline, injected, ground_truth). The baseline holds n_anomalies_each fewer
    submissions than the target, because exactly that many unenrolled submissions are added
    back during injection, so the final dataset has exactly the requested submission count.
    """
    base_scale = replace(scale, n_submissions=scale.n_submissions - scale.n_anomalies_each)
    master = generate_master(base_scale, seed)
    part1, ctx = generate_submissions(base_scale, master, seed)
    transactions = generate_lifecycle(base_scale, master, part1, ctx, seed)
    baseline = {**master, **transactions}
    injected, truth = inject_anomalies(scale, baseline, seed)
    sort_tables(baseline)
    sort_tables(injected)
    return baseline, injected, truth


# ------------------------------------------------------------------ schema
def schema_columns():
    """Load schema.sql into memory and return (connection, {table: [columns in order]})."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    columns = {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in TABLE_ORDER}
    return conn, columns


def check_columns(tables, columns):
    """The generated rows must have exactly the columns the schema defines."""
    for name in TABLE_ORDER:
        expected = set(columns[name])
        for row in tables[name][:1] + tables[name][-1:]:
            if set(row) != expected:
                raise SystemExit(f"Column mismatch in {name}: generator has {sorted(set(row) ^ expected)} "
                                 f"that differ from schema.sql")


def load_check(conn, columns, tables):
    """Insert everything into SQLite (foreign keys ON). Raises if any join is broken."""
    for name in TABLE_ORDER:
        cols = columns[name]
        sql = f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
        conn.executemany(sql, tables[name])
    conn.commit()
    for name in TABLE_ORDER:
        (count,) = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
        if count != len(tables[name]):
            raise SystemExit(f"Row count mismatch after load in {name}")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SystemExit(f"Foreign key violations found: {violations[:3]}")


# ------------------------------------------------------------------ writers
def write_csv(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(cols)
        for r in rows:
            writer.writerow([r[c] for c in cols])


def write_json(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump([{c: r[c] for c in cols} for r in rows], f, separators=(",", ":"))


def sql_literal(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(path, columns, tables, seed, scale_name):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"-- Seed data: scale={scale_name}, seed={seed}\n")
        f.write("-- Load schema.sql first, then this file. Parents are inserted before children.\n")
        f.write("PRAGMA foreign_keys = ON;\nBEGIN TRANSACTION;\n")
        for name in TABLE_ORDER:
            cols, rows = columns[name], tables[name]
            head = f"INSERT INTO {name} ({', '.join(cols)}) VALUES\n"
            for i in range(0, len(rows), SQL_BATCH_ROWS):
                batch = rows[i:i + SQL_BATCH_ROWS]
                values = ",\n".join("(" + ", ".join(sql_literal(r[c]) for c in cols) + ")" for r in batch)
                f.write(head + values + ";\n")
        f.write("COMMIT;\n")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_dataset(out_dir, tables, columns, seed, scale_name, variant, ground_truth=None):
    """Write CSV, JSON, SQL, optional ground truth and the manifest. Returns the manifest dict."""
    out = Path(out_dir)
    (out / "csv").mkdir(parents=True, exist_ok=True)
    (out / "json").mkdir(parents=True, exist_ok=True)
    (out / "sql").mkdir(parents=True, exist_ok=True)

    for name in TABLE_ORDER:
        write_csv(out / "csv" / f"{name}.csv", columns[name], tables[name])
        write_json(out / "json" / f"{name}.json", columns[name], tables[name])
    write_sql(out / "sql" / "seed.sql", columns, tables, seed, scale_name)
    if ground_truth is not None:   # kept OUTSIDE csv/ and json/ so it is never mistaken for input data
        write_csv(out / "ground_truth.csv", GROUND_TRUTH_COLUMNS, ground_truth)
        write_json(out / "ground_truth.json", GROUND_TRUTH_COLUMNS, ground_truth)

    files = {}
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files[path.relative_to(out).as_posix()] = {"bytes": path.stat().st_size, "sha256": sha256_of(path)}

    manifest = {
        "seed": seed,
        "scale": scale_name,
        "variant": variant,
        "generator_command": f"python generator/generate.py --seed {seed} --scale {scale_name}",
        "as_of_utc": config.AS_OF.strftime(config.TIMESTAMP_FORMAT),
        "external_data": "none (fully synthetic)",
        "row_counts": {name: len(tables[name]) for name in TABLE_ORDER},
        "anomalies_injected": ({i: sum(1 for r in ground_truth if r["issue_type"] == i) for i in ISSUE_TYPES}
                               if ground_truth is not None else {}),
        "files": files,
    }
    with open(out / "manifest.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return manifest


def make_archive(out_dir):
    """Zip the output folder. Fixed timestamps make the zip itself reproducible."""
    out = Path(out_dir)
    archive = Path(str(out) + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(out).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                z.writestr(info, path.read_bytes())
    return archive


# ------------------------------------------------------------------ command line
def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the synthetic grading-workflow dataset.")
    parser.add_argument("--seed", type=int, default=config.SEED, help=f"random seed (default {config.SEED})")
    parser.add_argument("--scale", choices=list(config.SCALES), default="starter", help="dataset size")
    parser.add_argument("--out", help="output folder for the injected dataset (default: outputs/<scale>)")
    parser.add_argument("--baseline-out", help="optional folder for the clean baseline (before injection)")
    parser.add_argument("--skip-load-check", action="store_true", help="skip the SQLite load check")
    parser.add_argument("--zip", action="store_true", help="also write <out>.zip (useful for the full dataset)")
    args = parser.parse_args(argv)

    out_dir = args.out or f"outputs/{args.scale}"
    scale = config.get_scale(args.scale)
    started = time.time()

    print(f"Generating scale={args.scale} seed={args.seed} ...")
    baseline, tables, truth = build_tables(scale, args.seed)
    conn, columns = schema_columns()
    check_columns(tables, columns)

    if not args.skip_load_check:
        load_check(conn, columns, tables)
        print("SQLite load check: OK (schema.sql, foreign keys enforced)")

    manifest = write_dataset(out_dir, tables, columns, args.seed, args.scale, "injected", truth)
    if args.baseline_out:
        write_dataset(args.baseline_out, baseline, columns, args.seed, args.scale, "baseline")
        print(f"Wrote clean baseline to {args.baseline_out}")

    for name in TABLE_ORDER:
        print(f"  {name:22} {manifest['row_counts'][name]:>8} rows")
    print("Injected anomalies (see ground_truth.csv):", manifest["anomalies_injected"])
    total_mb = sum(f["bytes"] for f in manifest["files"].values()) / 1_000_000
    if args.zip:
        archive = make_archive(out_dir)
        print(f"Wrote {archive} ({archive.stat().st_size / 1_000_000:.1f} MB)")
    print(f"Wrote {len(manifest['files'])} files ({total_mb:.1f} MB) to {out_dir} in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())