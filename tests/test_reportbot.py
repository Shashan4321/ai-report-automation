from pathlib import Path

import duckdb
import pandas as pd
import pytest

from reportbot import kpis, mailer, narrative, report, warehouse


@pytest.fixture(scope="module")
def pack(tmp_path_factory):
    db = Path(tmp_path_factory.mktemp("wh")) / "w.duckdb"
    warehouse.build(db)
    con = duckdb.connect(str(db), read_only=True)
    return kpis.compute(con, 2025, 12)


def test_kpis_are_consistent(pack):
    assert pack.orders > 0 and pack.revenue > 0
    assert pack.aov == pytest.approx(pack.revenue / pack.orders, abs=0.01)
    assert sum(c["revenue"] for c in pack.by_category) == pytest.approx(pack.revenue, abs=1)
    assert sum(c["share_pct"] for c in pack.channel_mix) == pytest.approx(100, abs=0.1)


def test_template_narrative_only_uses_known_numbers(pack):
    text = narrative.template_narrative(pack)
    assert "### Headline" in text
    assert narrative.check_numbers(text, pack) == []


def test_hallucinated_numbers_are_caught(pack):
    assert narrative.check_numbers("Revenue grew 37.4% to INR 9.99 crore.", pack)


def test_without_api_key_template_is_used(pack, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _, source = narrative.write(pack)
    assert source == "template"


def test_bad_llm_output_falls_back_to_template(pack, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(narrative, "claude_narrative", lambda k: "Revenue jumped 99.9%!")
    _, source = narrative.write(pack)
    assert source == "template"


def test_render_is_self_contained(pack):
    html = report.render(pack, narrative.template_narrative(pack), "template")
    assert "data:image/png;base64," in html and "http" not in html.split("<footer>")[0]


def test_anomaly_detection_flags_spike():
    days = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=30),
            "revenue": [100.0] * 15 + [1000.0] + [101.0, 99.0] * 7,
        }
    )
    flagged = kpis.detect_anomalies(days)
    assert [a["revenue"] for a in flagged] == [1000.0]


def test_mailer_dry_run_without_smtp(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "REPORT_TO"):
        monkeypatch.delenv(k, raising=False)
    assert mailer.send("<p>x</p>", "subject").startswith("dry-run")
