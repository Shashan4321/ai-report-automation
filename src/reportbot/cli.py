"""Entry point: ``python -m reportbot.cli --month 2025-12`` (default: last complete month
in the data)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from . import kpis, mailer, narrative, report, warehouse

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> Path:
    p = argparse.ArgumentParser(description="Build and e-mail the monthly sales report")
    p.add_argument("--month", default="2025-12", help="YYYY-MM (data covers 2023-01..2025-12)")
    p.add_argument("--out", default=str(ROOT / "out"))
    p.add_argument("--db", default=str(ROOT / "data" / "warehouse.duckdb"))
    p.add_argument("--no-email", action="store_true")
    a = p.parse_args(argv)

    db = Path(a.db)
    if not db.exists():
        warehouse.build(db)
    year, month = map(int, a.month.split("-"))
    con = duckdb.connect(str(db), read_only=True)
    pack = kpis.compute(con, year, month)
    text, source = narrative.write(pack)
    html = report.render(pack, text, source)
    out = Path(a.out)
    path = report.save(html, out, a.month)
    (out / f"kpis_{a.month}.json").write_text(json.dumps(pack.to_dict(), indent=2, default=str))
    (out / f"narrative_{a.month}.md").write_text(text)
    print(f"report: {path} (narrative: {source})")
    if not a.no_email:
        print(mailer.send(html, f"Sales report - {pack.period}", path))
    return path


if __name__ == "__main__":
    main()
