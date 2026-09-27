"""Render the KPI pack + narrative into a self-contained HTML report."""

from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from .kpis import KPIPack  # noqa: E402

TEMPLATES = Path(__file__).parent / "templates"
INK, ACCENT, MUTED = "#1f2937", "#2563eb", "#9ca3af"


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(MUTED)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=8)


def daily_chart(k: KPIPack) -> str:
    df = pd.DataFrame(k.daily)
    df["date"] = pd.to_datetime(df["date"])
    fig, ax = plt.subplots(figsize=(7, 2.4))
    ax.plot(df["date"], df["revenue"] / 1e5, color=ACCENT, lw=1.8)
    for a in k.anomalies:
        d = pd.to_datetime(a["date"])
        ax.scatter([d], [a["revenue"] / 1e5], color="#dc2626", zorder=3, s=24)
    ax.set_ylabel("INR lakh", fontsize=8, color=INK)
    ax.set_title("Daily revenue (red = anomaly)", fontsize=9, loc="left", color=INK)
    _style(ax)
    fig.autofmt_xdate()
    return _png(fig)


def category_chart(k: KPIPack) -> str:
    df = pd.DataFrame(k.by_category).sort_values("revenue")
    fig, ax = plt.subplots(figsize=(7, 2.4))
    ax.barh(df["category"], df["revenue"] / 1e5, color=ACCENT)
    for y, (rev, yoy) in enumerate(zip(df["revenue"], df["yoy_pct"], strict=True)):
        label = "" if yoy is None else f"  {yoy:+.1f}% YoY"
        ax.text(rev / 1e5, y, label, va="center", fontsize=7, color=INK)
    ax.set_xlabel("INR lakh", fontsize=8, color=INK)
    ax.set_title("Revenue by category", fontsize=9, loc="left", color=INK)
    _style(ax)
    return _png(fig)


def render(k: KPIPack, narrative_md: str, source: str) -> str:
    import markdown

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape())
    return env.get_template("report.html.j2").render(
        k=k,
        narrative=markdown.markdown(narrative_md),
        source=source,
        daily_png=daily_chart(k),
        category_png=category_chart(k),
        generated=datetime.now().strftime("%d %b %Y %H:%M"),
    )


def save(html: str, out_dir: Path, period_slug: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"sales_report_{period_slug}.html"
    path.write_text(html, encoding="utf-8")
    return path
