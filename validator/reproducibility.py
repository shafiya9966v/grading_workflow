"""Reproducibility check (task step 10).

Runs the generator twice with the SAME seed and compares row counts and SHA-256
checksums of every output file. It also runs once with a DIFFERENT seed as a control:
if the control produced identical files, the comparison would prove nothing, so the
check fails in that case.

Usage (from the project folder):
    python validator/reproducibility.py --scale starter
    python validator/reproducibility.py --scale full

Writes reports/reproducibility_<scale>.json and .md
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATE = ROOT / "generator" / "generate.py"
DEFAULT_SEED = 20261022


def run_generator(seed, scale, out_dir):
    """Run generate.py as a separate process and return its manifest and manifest checksum."""
    cmd = [sys.executable, str(GENERATE), "--seed", str(seed), "--scale", scale,
           "--out", str(out_dir), "--skip-load-check"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"Generator failed:\n{result.stderr or result.stdout}")
    manifest_path = Path(out_dir) / "manifest.json"
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    return json.loads(manifest_path.read_text(encoding="utf-8")), manifest_sha


def fingerprint(manifest):
    """One checksum summarising every file in a run."""
    lines = "\n".join(f"{path}:{info['sha256']}" for path, info in sorted(manifest["files"].items()))
    return hashlib.sha256(lines.encode()).hexdigest()


def compare(a, b):
    """Compare two manifests: returns (identical_files, different_files, row_count_mismatches)."""
    same, different = [], []
    for path in sorted(set(a["files"]) | set(b["files"])):
        fa, fb = a["files"].get(path), b["files"].get(path)
        (same if fa and fb and fa["sha256"] == fb["sha256"] else different).append(path)
    counts = {t: (a["row_counts"].get(t), b["row_counts"].get(t))
              for t in sorted(set(a["row_counts"]) | set(b["row_counts"]))}
    return same, different, counts


def main(argv=None):
    p = argparse.ArgumentParser(description="Check that the same seed gives identical output.")
    p.add_argument("--scale", choices=["starter", "full"], default="starter")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--report-dir", default="reports")
    args = p.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print(f"Run 1 (seed {args.seed}, scale {args.scale}) ...")
        m1, sha1 = run_generator(args.seed, args.scale, tmp / "run1")
        print("Run 2 (same seed) ...")
        m2, sha2 = run_generator(args.seed, args.scale, tmp / "run2")
        print(f"Control run (seed {args.seed + 1}) ...")
        m3, _ = run_generator(args.seed + 1, args.scale, tmp / "control")

    same, different, counts = compare(m1, m2)
    control_same, control_diff, _ = compare(m1, m3)
    rows_match = all(a == b for a, b in counts.values())
    fp1, fp2 = fingerprint(m1), fingerprint(m2)

    checks = {
        "row counts identical across runs": rows_match,
        "every file checksum identical across runs": not different,
        "manifest.json identical across runs": sha1 == sha2,
        "dataset fingerprint identical": fp1 == fp2,
        "control run with another seed differs (so the comparison is meaningful)": len(control_diff) > 0,
    }
    passed = all(checks.values())

    report = {
        "scale": args.scale, "seed": args.seed, "result": "PASS" if passed else "FAIL",
        "checks": checks, "files_compared": len(same) + len(different), "files_identical": len(same),
        "dataset_fingerprint_run1": fp1, "dataset_fingerprint_run2": fp2,
        "row_counts": {t: {"run1": a, "run2": b, "match": a == b} for t, (a, b) in counts.items()},
        "control_seed": args.seed + 1, "control_files_different": len(control_diff),
        "files": {path: {"run1": m1["files"].get(path, {}).get("sha256"),
                         "run2": m2["files"].get(path, {}).get("sha256"),
                         "match": path in same} for path in sorted(set(m1["files"]) | set(m2["files"]))},
    }

    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"reproducibility_{args.scale}.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    lines = [f"# Reproducibility report: {args.scale}", "",
             f"- Seed: `{args.seed}`  |  Result: **{report['result']}**",
             f"- Command: `python generator/generate.py --seed {args.seed} --scale {args.scale}` (run twice)",
             f"- Files compared: {report['files_compared']}, identical: {report['files_identical']}",
             f"- Dataset fingerprint run 1: `{fp1}`",
             f"- Dataset fingerprint run 2: `{fp2}`",
             f"- Control (seed {args.seed + 1}): {len(control_diff)} of {report['files_compared']} files differ", "",
             "## Checks", "", "| Check | Result |", "|---|---|"]
    lines += [f"| {name} | {'PASS' if ok else 'FAIL'} |" for name, ok in checks.items()]
    lines += ["", "## Row counts", "", "| Table | Run 1 | Run 2 | Match |", "|---|---:|---:|---|"]
    lines += [f"| {t} | {a:,} | {b:,} | {'yes' if a == b else 'NO'} |" for t, (a, b) in counts.items()]
    lines += ["", "## File checksums (SHA-256, first 16 characters)", "", "| File | Run 1 | Run 2 | Match |", "|---|---|---|---|"]
    for path, info in report["files"].items():
        lines.append(f"| {path} | `{(info['run1'] or '-')[:16]}` | `{(info['run2'] or '-')[:16]}` | {'yes' if info['match'] else 'NO'} |")
    with open(out / f"reproducibility_{args.scale}.md", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"{report['files_identical']} of {report['files_compared']} files identical across the two runs")
    print(f"Control run: {len(control_diff)} files differ with a different seed")
    print("RESULT:", report["result"], f"(report written to {out}/reproducibility_{args.scale}.md)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())