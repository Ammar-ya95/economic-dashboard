"""Refresh data/indicators.json from FRED and the World Bank.

Robustness rules:
- Each series is fetched independently; one failure never kills the run.
- If a series fails, the last good value from the existing JSON is kept.
- Handles both FRED CSV header styles ("DATE" and "observation_date").
- Uses the official FRED API when FRED_API_KEY is set (more reliable
  from GitHub Actions); otherwise falls back to the public CSV endpoint.
"""
import csv
import io
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "indicators.json"
FRED_HOME = "https://fred.stlouisfed.org/"
WB_HOME = "https://data.worldbank.org/"
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()
START = f"{datetime.now(timezone.utc).year - 4}-01-01"


def get_text(url, retries=3, timeout=20):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (economic-dashboard)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except Exception as exc:  # network hiccup, 429, 5xx
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url} failed after {retries} tries: {last}")


def parse_fred_csv(text, series_id):
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError(f"{series_id}: empty CSV")
    cols = list(rows[0].keys())
    # FRED renamed "DATE" -> "observation_date"; accept either (or the first column).
    date_col = next((c for c in cols if c.lower() in ("date", "observation_date")), cols[0])
    value_col = series_id if series_id in cols else cols[-1]
    vals = []
    for row in rows:
        raw = (row.get(value_col) or "").strip()
        if raw in ("", "."):
            continue
        try:
            vals.append({"date": row[date_col], "value": float(raw)})
        except ValueError:
            pass
    return vals


@lru_cache(maxsize=None)
def fred(series_id):
    print(f"Fetching FRED {series_id}...", flush=True)
    if FRED_API_KEY:
        q = urllib.parse.urlencode({"series_id": series_id, "api_key": FRED_API_KEY,
                                    "file_type": "json", "observation_start": START})
        data = json.loads(get_text(f"https://api.stlouisfed.org/fred/series/observations?{q}"))
        vals = [{"date": o["date"], "value": float(o["value"])}
                for o in data.get("observations", []) if o.get("value") not in (None, "", ".")]
    else:
        vals = parse_fred_csv(get_text(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={START}"), series_id)
    if not vals:
        raise ValueError(f"{series_id}: no observations")
    return vals


@lru_cache(maxsize=None)
def world_bank(country, indicator):
    print(f"Fetching World Bank {country} {indicator}...", flush=True)
    payload = json.loads(get_text(f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json&per_page=100"))
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        raise ValueError(f"{country}/{indicator}: no data")
    vals = [{"date": str(r["date"]), "value": float(r["value"])} for r in reversed(payload[1]) if r.get("value") is not None]
    if not vals:
        raise ValueError(f"{country}/{indicator}: all null")
    return vals


def pct_change(series, lag):
    return [{"date": series[i]["date"], "value": (series[i]["value"] / series[i - lag]["value"] - 1) * 100}
            for i in range(lag, len(series)) if series[i - lag]["value"] != 0]


def item(name, series, unit, frequency, source, source_url, scale=1.0):
    hist = [{"date": x["date"], "value": round(x["value"] * scale, 4)} for x in series[-24:]]
    latest, prev = hist[-1], (hist[-2] if len(hist) > 1 else hist[-1])
    return {"name": name, "value": latest["value"], "change": round(latest["value"] - prev["value"], 4),
            "date": latest["date"], "frequency": frequency, "unit": unit, "source": source,
            "source_url": source_url, "history": hist[-14:]}


# Previous good data, used as fallback per series.
try:
    old = json.loads(OUT.read_text(encoding="utf-8"))
    OLD = {x["name"]: x for sec in old.get("sections", {}).values() for x in sec}
except Exception:
    OLD = {}

failures = []


def safe(name, fn):
    try:
        return fn()
    except Exception as exc:
        failures.append(name)
        print(f"  ! {name}: {exc} -> {'keeping last value' if name in OLD else 'skipped'}", flush=True)
        return OLD.get(name)


def F(name, sid, unit, freq, src, scale=1.0, yoy=False):
    return safe(name, lambda: item(name, pct_change(fred(sid), 12) if yoy else fred(sid), unit, freq, src, FRED_HOME, scale))


def WB(name, country, ind, unit="%"):
    return safe(name, lambda: item(name, world_bank(country, ind), unit, "Annual", "World Bank", WB_HOME))


us = [
    F("CPI Inflation (YoY)", "CPIAUCSL", "%", "Monthly", "FRED / BLS", yoy=True),
    F("Core PCE Inflation (YoY)", "PCEPILFE", "%", "Monthly", "FRED / BEA", yoy=True),
    F("Unemployment Rate", "UNRATE", "%", "Monthly", "FRED / BLS"),
    F("Federal Funds Rate", "FEDFUNDS", "%", "Monthly", "FRED / Federal Reserve"),
    F("10-Year Treasury Yield", "DGS10", "%", "Daily", "FRED / U.S. Treasury"),
    F("2-Year Treasury Yield", "DGS2", "%", "Daily", "FRED / U.S. Treasury"),
    F("30-Year Mortgage Rate", "MORTGAGE30US", "%", "Weekly", "FRED / Freddie Mac"),
    F("S&P 500", "SP500", "index", "Daily", "FRED / S&P Dow Jones"),
]
texas = [
    F("Texas Unemployment Rate", "TXUR", "%", "Monthly", "FRED / BLS"),
    F("Texas Nonfarm Employment", "TXNA", "M", "Monthly", "FRED / BLS", scale=0.001),
    F("Texas House Price Index", "TXSTHPI", "index", "Quarterly", "FRED / FHFA"),
    F("Texas Building Permits", "TXBPPRIV", "index", "Monthly", "FRED / Census"),
    F("WTI Crude Oil", "DCOILWTICO", "$", "Daily", "FRED / EIA"),
]
saudi = [
    {"name": "USD / SAR", "value": 3.75, "change": 0.0, "date": datetime.now(timezone.utc).date().isoformat(),
     "frequency": "Fixed peg", "unit": "index", "source": "SAMA peg reference", "source_url": "https://www.sama.gov.sa/",
     "history": []},
    WB("Saudi GDP Growth", "SAU", "NY.GDP.MKTP.KD.ZG"),
    WB("Saudi Inflation", "SAU", "FP.CPI.TOTL.ZG"),
    WB("Saudi Unemployment", "SAU", "SL.UEM.TOTL.ZS"),
    WB("Saudi GDP per capita", "SAU", "NY.GDP.PCAP.CD", unit="$"),
    F("Brent Crude Oil", "DCOILBRENTEU", "$", "Daily", "FRED / EIA"),
]
global_items = [
    WB("World GDP Growth", "WLD", "NY.GDP.MKTP.KD.ZG"),
    WB("Euro Area GDP Growth", "EMU", "NY.GDP.MKTP.KD.ZG"),
    WB("China GDP Growth", "CHN", "NY.GDP.MKTP.KD.ZG"),
    WB("India GDP Growth", "IND", "NY.GDP.MKTP.KD.ZG"),
    WB("Japan GDP Growth", "JPN", "NY.GDP.MKTP.KD.ZG"),
    F("Brent Crude Oil", "DCOILBRENTEU", "$", "Daily", "FRED / EIA"),
]

sections = {k: [x for x in v if x] for k, v in
            {"us": us, "texas": texas, "saudi": saudi, "global": global_items}.items()}
lookup = {x["name"]: x for sec in sections.values() for x in sec}
sections["pulse"] = [lookup[n] for n in ["S&P 500", "10-Year Treasury Yield", "Federal Funds Rate",
                                         "CPI Inflation (YoY)", "Unemployment Rate", "WTI Crude Oil",
                                         "Brent Crude Oil", "USD / SAR"] if n in lookup]

total = sum(len(v) for k, v in sections.items() if k != "pulse")
if total <= 1:  # only the hard-coded peg -> everything failed; don't overwrite good data
    raise SystemExit("All series failed; leaving indicators.json unchanged.")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                           "sections": sections}, indent=2), encoding="utf-8")
print(f"Wrote {total} indicators to {OUT}. Failed/fallback: {len(failures)} {failures if failures else ''}")
