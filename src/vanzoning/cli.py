"""Command line: `vanzoning parse <pdf> -o out.json` and `vanzoning show R1-1`."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vanzoning")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse", help="parse a district schedule PDF to JSON (one file per district it covers)")
    p.add_argument("pdf", nargs="+", help="PDF files, or a folder of PDFs")
    p.add_argument("-o", "--out", help="output JSON path, or a folder if the PDFs cover several districts")
    p.add_argument("--csv", help="also write the combined regulations table as CSV")
    s = sub.add_parser("show", help="print the regulations table for a district")
    s.add_argument("district_or_json")
    args = ap.parse_args(argv)

    if args.cmd == "parse":
        from pathlib import Path

        import pandas as pd

        from .parse.schedule import parse_schedule_pdf
        from .store import save

        pdfs = [q for p_ in args.pdf for q in (sorted(Path(p_).glob("*.pdf")) if Path(p_).is_dir() else [Path(p_)])]
        scheds = [s_ for pdf in pdfs for s_ in parse_schedule_pdf(pdf)]
        if args.out and (len(scheds) > 1 or not args.out.endswith(".json")):
            for s_ in scheds:
                path = save(s_, Path(args.out) / f"{s_.district}.json")
                print(f"{s_.district}: {len(s_.regulations)} rules, {len(s_.clauses)} clauses -> {path}", file=sys.stderr)
        elif args.out:
            save(scheds[0], args.out)
            print(f"{scheds[0].district}: {len(scheds[0].regulations)} rules -> {args.out}", file=sys.stderr)
        else:
            print("[" + ",".join(s_.model_dump_json(indent=2) for s_ in scheds) + "]")
        if args.csv:
            pd.concat([s_.regulations_df() for s_ in scheds], ignore_index=True).to_csv(args.csv, index=False)
    elif args.cmd == "show":
        from .store import load, load_file

        x = args.district_or_json
        sched = load_file(x) if x.endswith(".json") else load(x)
        cols = ["group", "use", "metric", "bound", "value", "unit", "min_units", "max_units", "condition", "tenure", "discretionary", "clause"]
        print(sched.regulations_df()[cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
