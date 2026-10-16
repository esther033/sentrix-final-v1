"""Inventory of extracted RCAEval RE2 data -- facts, not assumptions.

Answers the dataset questions of the project brief (what files a case has,
metric columns, log/trace columns, inject_time format, sampling interval,
time span before/after injection) by reading the files themselves.

A case is any directory containing inject_time.txt. Files are inspected
without loading large CSVs fully: header + streamed line count, and the
first/last value of a time column when one exists.

  python3 rcaeval/inventory_re2.py data/RE2 [--out rcaeval/out]
Writes cases.csv (one row per case), files.csv (one row per file) and
summary.md (per-system aggregates, column lists).
"""
import argparse
import csv
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics

TIME_COLS = ("time", "timestamp", "Time", "Timestamp", "ts", "startTime", "start_time")


def head_and_count(path, max_bytes_count=None):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        header = next(csv.reader([f.readline()]), [])
        first = f.readline()
        n, last = (1 if first else 0), first
        for line in f:
            n += 1
            last = line
    return header, n, first, last


def time_value(header, line):
    if not line:
        return None
    row = next(csv.reader([line]), [])
    for c in TIME_COLS:
        if c in header and header.index(c) < len(row):
            try:
                return float(row[header.index(c)])
            except ValueError:
                return row[header.index(c)]
    return None


def metric_sampling(path, header):
    """Median step of the time column over the first 200 rows."""
    col = next((c for c in TIME_COLS if c in header), None)
    if col is None:
        return None
    idx, vals = header.index(col), []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        r = csv.reader(f); next(r, None)
        for i, row in enumerate(r):
            if i >= 200:
                break
            try:
                vals.append(float(row[idx]))
            except (ValueError, IndexError):
                return None
    steps = [b - a for a, b in zip(vals, vals[1:])]
    return statistics.median(steps) if steps else None


def inspect_case(case, root):
    rel = case.relative_to(root)
    info = {"case": rel.as_posix(), "system": rel.parts[0] if rel.parts else "",
            "inject_time_raw": (case / "inject_time.txt").read_text().strip()}
    try:
        info["inject_time"] = float(info["inject_time_raw"])
    except ValueError:
        info["inject_time"] = None
    files = []
    for p in sorted(case.iterdir()):
        if not p.is_file():
            continue
        entry = {"case": info["case"], "file": p.name, "bytes": p.stat().st_size}
        if p.suffix == ".csv":
            header, n, first, last = head_and_count(p)
            entry.update(columns=len(header), rows=n, header=json.dumps(header[:400]),
                         t_first=time_value(header, first), t_last=time_value(header, last))
            if p.name in ("data.csv", "metrics.csv", "simple_data.csv"):
                entry["median_step"] = metric_sampling(p, header)
        elif p.suffix == ".json" and p.stat().st_size < 512 * 1024 * 1024:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                entry["json_type"] = type(d).__name__
                entry["json_keys"] = json.dumps(list(d)[:50]) if isinstance(d, dict) else None
            except ValueError as exc:
                entry["json_error"] = str(exc)
        files.append(entry)
    info["files"] = ";".join(f["file"] for f in files)
    for f in files:
        if f.get("t_first") is not None and isinstance(f["t_first"], float) and info["inject_time"] is not None:
            info[f"{f['file']}_pre_s"] = info["inject_time"] - f["t_first"]
            if isinstance(f.get("t_last"), float):
                info[f"{f['file']}_post_s"] = f["t_last"] - info["inject_time"]
    return info, files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "out"))
    args = ap.parse_args()
    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = sorted({p.parent for p in root.rglob("inject_time.txt")})
    if not cases:
        raise SystemExit(f"no inject_time.txt under {root}")
    case_rows, file_rows = [], []
    for c in cases:
        info, files = inspect_case(c, root)
        case_rows.append(info); file_rows.extend(files)
    for name, rows in (("cases.csv", case_rows), ("files.csv", file_rows)):
        keys = sorted({k for r in rows for k in r})
        with open(out / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    by_sys = defaultdict(list)
    for r in case_rows:
        by_sys[r["system"]].append(r)
    lines = ["# RE2 inventory", "", f"root: `{root}`  cases: {len(case_rows)}", ""]
    for sysname, rows in sorted(by_sys.items()):
        names = [Path(r["case"]).parts for r in rows]
        lines += [f"## {sysname}", "", f"- cases: {len(rows)}",
                  f"- case path depth examples: {', '.join('/'.join(n) for n in names[:3])}",
                  f"- file sets: {dict(Counter(r['files'] for r in rows))}"]
        sys_files = [f for f in file_rows if f["case"].split("/")[0] == sysname]
        for fname in sorted({f["file"] for f in sys_files}):
            fs = [f for f in sys_files if f["file"] == fname]
            cols = sorted({f.get("columns") for f in fs if f.get("columns") is not None})
            rows_ = [f["rows"] for f in fs if "rows" in f]
            steps = [f["median_step"] for f in fs if f.get("median_step")]
            lines.append(f"- `{fname}`: in {len(fs)} cases; columns {cols[:5]}{'...' if len(cols) > 5 else ''}; "
                         f"rows median {statistics.median(rows_) if rows_ else '-'}; "
                         f"median time step {statistics.median(steps) if steps else '-'}; "
                         f"total {sum(f['bytes'] for f in fs) / 1e9:.2f} GB")
            hdr = next((f["header"] for f in fs if f.get("header")), None)
            if hdr:
                h = json.loads(hdr)
                lines.append(f"  - header ({len(h)} shown): `{', '.join(h[:60])}`{' ...' if len(h) > 60 else ''}")
        pre = [v for r in rows for k, v in r.items() if k.endswith("_pre_s")]
        post = [v for r in rows for k, v in r.items() if k.endswith("_post_s")]
        if pre:
            lines.append(f"- seconds before inject_time (median over files): {statistics.median(pre):.0f}; "
                         f"after: {statistics.median(post) if post else '-'}")
        lines.append("")
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
