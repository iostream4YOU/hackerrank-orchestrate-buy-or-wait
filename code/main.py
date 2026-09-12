"""Buy or Wait? — generate output.csv for dataset/requests.csv.

Usage (from the repository root):
    python3 code/main.py                      # full run -> ./output.csv
    python3 code/main.py --input dataset/sample_requests.csv --output /tmp/samples_out.csv
    python3 code/main.py --no-llm             # rule-based evidence only (no API calls)
"""
import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from buyorwait import data  # noqa: E402
from buyorwait.pipeline import OUTPUT_COLUMNS, solve_request  # noqa: E402


def run(input_csv, output_csv, dataset_dir, use_llm=True, refresh=False, quiet=False, report=None):
    ds = data.load(dataset_dir)
    requests = data.read_csv(input_csv)
    from buyorwait.evidence import Evidence
    evidence = Evidence(ds, use_llm=use_llm, refresh=refresh, verbose=not quiet,
                        users={r["user_id"] for r in requests})
    rows, failures = [], 0
    for req in requests:
        if req["user_id"] not in ds.profiles:
            raise SystemExit(f"{req['request_id']}: unknown user {req['user_id']}")
        row, errs = solve_request(ds, req, evidence)
        if errs:
            failures += 1
            if not quiet:
                print(f"[verify] {req['request_id']}: {errs}", file=sys.stderr)
        rows.append(row)
    assert list(OUTPUT_COLUMNS) == ds.output_columns, "output schema drifted from dataset/output.csv"
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    assert len(rows) == len(requests) and len({r["request_id"] for r in rows}) == len(rows)
    evidence.save()
    if report:
        from buyorwait.report import write_usage_report
        write_usage_report(report, evidence, len(requests), os.path.relpath(input_csv, REPO),
                           os.path.relpath(output_csv, REPO))
    if not quiet:
        print(f"wrote {len(rows)} rows -> {output_csv} ({failures} rows with verifier warnings)")
    return rows, evidence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=os.path.join(REPO, "dataset"))
    ap.add_argument("--input", default=None, help="requests CSV (default: dataset/requests.csv)")
    ap.add_argument("--output", default=os.path.join(REPO, "output.csv"))
    ap.add_argument("--no-llm", action="store_true", help="skip model calls; use cached/rule-based evidence")
    ap.add_argument("--refresh", action="store_true", help="ignore the evidence cache and re-query models")
    ap.add_argument("--report", default=None, help="usage report path (default for the full run: "
                    "code/evaluation/usage_report.md)")
    args = ap.parse_args()
    input_csv = args.input or os.path.join(args.dataset, "requests.csv")
    default_run = os.path.abspath(input_csv) == os.path.abspath(os.path.join(args.dataset, "requests.csv"))
    report = args.report or (os.path.join(HERE, "evaluation", "usage_report.md") if default_run else None)
    run(input_csv, args.output, args.dataset, use_llm=not args.no_llm, refresh=args.refresh, report=report)


if __name__ == "__main__":
    main()
