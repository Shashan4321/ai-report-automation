"""Compute the month's KPI pack from the warehouse with plain SQL.

The output is a small JSON-serialisable dict. It is the *only* thing the LLM sees,
which keeps the narrative grounded in numbers we computed ourselves.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

import duckdb
import pandas as pd

BASE = """
FROM fact_sales f
JOIN dim_date d USING (date_key)
JOIN dim_product p USING (product_key)
JOIN dim_store s USING (store_key)
"""


@dataclass
class KPIPack:
    period: str
    revenue: float
    orders: int
    aov: float
    margin_pct: float
    return_rate_pct: float
    revenue_mom_pct: float | None
    revenue_yoy_pct: float | None
    orders_yoy_pct: float | None
    by_category: list[dict] = field(default_factory=list)
    top_cities: list[dict] = field(default_factory=list)
    bottom_cities: list[dict] = field(default_factory=list)
    channel_mix: list[dict] = field(default_factory=list)
    anomalies: list[dict] = field(default_factory=list)
    daily: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _pct(new: float, old: float | None) -> float | None:
    if not old:
        return None
    return round((new / old - 1) * 100, 1)


def _month_totals(con: duckdb.DuckDBPyConnection, y: int, m: int) -> tuple[float, int]:
    r = con.execute(
        f"SELECT COALESCE(SUM(net_revenue), 0), COUNT(DISTINCT order_id) {BASE} "
        "WHERE d.year = ? AND d.month = ? AND NOT f.is_returned",
        [y, m],
    ).fetchone()
    return float(r[0]), int(r[1])


def compute(con: duckdb.DuckDBPyConnection, year: int, month: int) -> KPIPack:
    """KPIs for ``year``-``month`` with MoM and YoY comparisons."""
    rev, orders = _month_totals(con, year, month)
    if orders == 0:
        raise ValueError(f"No sales found for {year}-{month:02d}")
    py, pm = (year, month - 1) if month > 1 else (year - 1, 12)
    rev_prev, _ = _month_totals(con, py, pm)
    rev_ly, orders_ly = _month_totals(con, year - 1, month)

    where = "WHERE d.year = ? AND d.month = ?"
    margin, returns = con.execute(
        f"""SELECT (SUM(net_revenue) FILTER (WHERE NOT is_returned)
                    - SUM(cost) FILTER (WHERE NOT is_returned))
                   / SUM(net_revenue) FILTER (WHERE NOT is_returned) * 100,
                   AVG(CASE WHEN is_returned THEN 1 ELSE 0 END) * 100
            {BASE} {where}""",
        [year, month],
    ).fetchone()

    def q(sql: str) -> list[dict]:
        df = con.execute(sql, [year, month]).df()
        return df.round(2).to_dict(orient="records")

    ok = f"{where} AND NOT f.is_returned"
    by_cat = q(f"""SELECT p.category, SUM(net_revenue) AS revenue,
                          (SUM(net_revenue) - SUM(cost)) / SUM(net_revenue) * 100 AS margin_pct
                   {BASE} {ok} GROUP BY 1 ORDER BY revenue DESC""")
    # add YoY per category
    ly = dict(
        con.execute(
            f"SELECT p.category, SUM(net_revenue) {BASE} {ok} GROUP BY 1", [year - 1, month]
        ).fetchall()
    )
    for row in by_cat:
        row["yoy_pct"] = _pct(row["revenue"], ly.get(row["category"]))

    city_sql = f"SELECT s.city, SUM(net_revenue) AS revenue {BASE} {ok} GROUP BY 1 ORDER BY 2"
    cities = q(city_sql)
    channel = q(f"""SELECT f.channel, SUM(net_revenue) * 100
                          / SUM(SUM(net_revenue)) OVER () AS share_pct
                    {BASE} {ok} GROUP BY 1 ORDER BY 2 DESC""")
    daily_df = con.execute(
        f"SELECT d.date, SUM(net_revenue) AS revenue {BASE} {ok} GROUP BY 1 ORDER BY 1",
        [year, month],
    ).df()

    return KPIPack(
        period=date(year, month, 1).strftime("%B %Y"),
        revenue=round(rev, 2),
        orders=orders,
        aov=round(rev / orders, 2),
        margin_pct=round(float(margin), 1),
        return_rate_pct=round(float(returns), 2),
        revenue_mom_pct=_pct(rev, rev_prev),
        revenue_yoy_pct=_pct(rev, rev_ly),
        orders_yoy_pct=_pct(orders, orders_ly),
        by_category=by_cat,
        top_cities=list(reversed(cities[-3:])),
        bottom_cities=cities[:3],
        channel_mix=channel,
        anomalies=detect_anomalies(daily_df),
        daily=[
            {"date": str(pd.Timestamp(r.date).date()), "revenue": round(r.revenue, 2)}
            for r in daily_df.itertuples()
        ],
    )


def detect_anomalies(daily: pd.DataFrame, z: float = 3.5) -> list[dict]:
    """Flag days whose revenue is more than ``z`` robust standard deviations from the median."""
    if len(daily) < 7:
        return []
    s = daily["revenue"]
    med = s.median()
    mad = (s - med).abs().median() * 1.4826 or s.std()
    score = (s - med) / mad
    out = daily.loc[score.abs() > z].assign(z_score=score.round(1))
    return [
        {
            "date": str(pd.Timestamp(r.date).date()),
            "revenue": round(r.revenue, 2),
            "z_score": float(r.z_score),
        }
        for r in out.itertuples()
    ]
