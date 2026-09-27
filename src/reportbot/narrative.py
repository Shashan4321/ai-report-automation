"""Turn the KPI pack into an executive narrative.

* With ``ANTHROPIC_API_KEY`` set, Claude writes the narrative from the KPI JSON.
* Without it (CI, local demo), a deterministic template writes it instead.

Either way, :func:`check_numbers` verifies that every number in the text can be
traced back to the KPI pack, so a hallucinated figure never reaches an executive.
"""

from __future__ import annotations

import json
import os
import re

from .kpis import KPIPack

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

PROMPT = """You are the head of analytics writing the monthly sales note for the \
leadership team of a retail company.

Write 4 short sections in Markdown:
### Headline  (one sentence: the single most important takeaway)
### What happened  (3-4 bullets: revenue, orders, AOV, margin, MoM and YoY)
### Where  (2-3 bullets: categories and cities driving or dragging performance)
### Watch-outs & actions  (2-3 bullets: anomalies, returns, a concrete next step each)

Rules:
- Use ONLY numbers that appear in the JSON below. Do not compute new numbers.
- Money is INR. Write large amounts in lakh or crore with 2 decimals (1 crore = 100 lakh =
  10,000,000), e.g. "INR 4.12 crore". Percentages with 1 decimal.
- Plain business English, no jargon, under 220 words.

KPI JSON:
{kpis}
"""


def _inr(x: float) -> str:
    return f"INR {x / 1e7:.2f} crore" if abs(x) >= 1e7 else f"INR {x / 1e5:.2f} lakh"


def _signed(p: float | None) -> str:
    return "n/a" if p is None else f"{p:+.1f}%"


def template_narrative(k: KPIPack) -> str:
    """Deterministic narrative used when no API key is configured."""
    best = max(k.by_category, key=lambda c: c["yoy_pct"] if c["yoy_pct"] is not None else -1e9)
    worst = min(k.by_category, key=lambda c: c["yoy_pct"] if c["yoy_pct"] is not None else 1e9)
    trend = "up" if (k.revenue_yoy_pct or 0) >= 0 else "down"
    lines = [
        "### Headline",
        f"{k.period} revenue was {_inr(k.revenue)}, {trend} "
        f"{abs(k.revenue_yoy_pct or 0):.1f}% year on year.",
        "",
        "### What happened",
        f"- Revenue {_inr(k.revenue)}: {_signed(k.revenue_mom_pct)} vs last month, "
        f"{_signed(k.revenue_yoy_pct)} vs last year.",
        f"- Orders {k.orders:,} ({_signed(k.orders_yoy_pct)} YoY); "
        f"average order value INR {k.aov:,.2f}.",
        f"- Gross margin {k.margin_pct:.1f}%; return rate {k.return_rate_pct:.2f}%.",
        "",
        "### Where",
        f"- Fastest-growing category: {best['category']} ({_signed(best['yoy_pct'])} YoY); "
        f"weakest: {worst['category']} ({_signed(worst['yoy_pct'])}).",
        f"- Top city: {k.top_cities[0]['city']} ({_inr(k.top_cities[0]['revenue'])}); "
        f"lowest: {k.bottom_cities[0]['city']} ({_inr(k.bottom_cities[0]['revenue'])}).",
        "",
        "### Watch-outs & actions",
    ]
    if k.anomalies:
        a = k.anomalies[0]
        lines.append(
            f"- Unusual day: {a['date']} at {_inr(a['revenue'])} "
            f"(z-score {a['z_score']:+.1f}). Check promotions or data feeds."
        )
    lines.append(f"- Review pricing and stock in {worst['category']} with the category team.")
    return "\n".join(lines)


def claude_narrative(k: KPIPack) -> str:
    import anthropic

    msg = anthropic.Anthropic().messages.create(
        model=MODEL,
        max_tokens=800,
        temperature=0.2,
        messages=[
            {
                "role": "user",
                "content": PROMPT.format(
                    kpis=json.dumps(
                        {kk: v for kk, v in k.to_dict().items() if kk != "daily"}, default=str
                    )
                ),
            }
        ],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()


NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def _allowed_numbers(k: KPIPack) -> set[float]:
    """Every number in the pack, plus the display conversions the prompt allows."""
    allowed: set[float] = set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            for f in (v, v / 1e5, v / 1e7):
                allowed.update({round(f, 2), round(f, 1), round(f, 0)})
        elif isinstance(v, str):
            for n in NUM_RE.findall(v):
                allowed.add(round(float(n.replace(",", "")), 2))

    walk(k.to_dict())
    return allowed


def check_numbers(text: str, k: KPIPack) -> list[str]:
    """Return numbers in ``text`` that cannot be traced to the KPI pack."""
    allowed = _allowed_numbers(k)
    bad = []
    for raw in NUM_RE.findall(text):
        n = round(abs(float(raw.replace(",", "").rstrip("."))), 2)
        if n in {0, 1, 2, 3, 4, 5, 10, 100}:  # list markers, "top 3" etc.
            continue
        if not any(abs(n - a) <= 0.006 for a in allowed) and not any(
            abs(n + a) <= 0.006 for a in allowed
        ):
            bad.append(raw)
    return bad


def write(k: KPIPack) -> tuple[str, str]:
    """Return (narrative, source) where source is 'claude' or 'template'."""
    if os.getenv("ANTHROPIC_API_KEY"):
        text = claude_narrative(k)
        if not check_numbers(text, k):
            return text, "claude"
        # fall back rather than publish an unverifiable number
    return template_narrative(k), "template"
