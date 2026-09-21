import csv
import io
import json
import urllib.request
from datetime import datetime, timezone\nfrom functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "indicators.json"
FRED_HOME = "https://fred.stlouisfed.org/"
WB_HOME = "https://data.worldbank.org/"

def get_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "economic-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8")

def fred(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    rows = list(csv.DictReader(io.StringIO(get_text(url))))
    vals = []
    for row in rows:
        raw = row.get(series_id)
        if raw in (None, "", "."):
            continue
        try:
            vals.append({"date": row["DATE"], "value": float(raw)})
        except Exception:
            pass
    if not vals:
        raise ValueError(series_id)
    return vals

@lru_cache(maxsize=None)\ndef world_bank(country, indicator):\n    print(f"Fetching World Bank {country} {indicator}...", flush=True)
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json&per_page=100"
    payload = json.loads(get_text(url))
    vals = []
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError(indicator)
    for row in reversed(payload[1] or []):
        if row.get("value") is not None:
            vals.append({"date": str(row.get("date")), "value": float(row["value"])})
    if not vals:
        raise ValueError(indicator)
    return vals

def percent_change(series, lag=1):
    out = []
    for i in range(lag, len(series)):
        prev = series[i-lag]["value"]
        cur = series[i]["value"]
        if prev != 0:
            out.append({"date": series[i]["date"], "value": (cur / prev - 1) * 100})
    return out

def as_item(name, series, unit, frequency, source, source_url, scale=1.0):
    hist = [{"date": x["date"], "value": x["value"] * scale} for x in series[-24:]]
    if not hist:
        raise ValueError(name)
    latest = hist[-1]
    prev = hist[-2] if len(hist) > 1 else latest
    return {
        "name": name,
        "value": latest["value"],
        "change": latest["value"] - prev["value"],
        "date": latest["date"],
        "frequency": frequency,
        "unit": unit,
        "source": source,
        "source_url": source_url,
        "history": hist[-14:]
    }

def safe(fn):
    try:
        return fn()
    except Exception as exc:
        print("Skipping series:", exc)
        return None

us = [
    safe(lambda: as_item("CPI Inflation (YoY)", percent_change(fred("CPIAUCSL"), 12), "%", "Monthly", "FRED / BLS", FRED_HOME)),
    safe(lambda: as_item("Core PCE Inflation (YoY)", percent_change(fred("PCEPILFE"), 12), "%", "Monthly", "FRED / BEA", FRED_HOME)),
    safe(lambda: as_item("Unemployment Rate", fred("UNRATE"), "%", "Monthly", "FRED / BLS", FRED_HOME)),
    safe(lambda: as_item("Federal Funds Rate", fred("FEDFUNDS"), "%", "Monthly", "FRED / Federal Reserve", FRED_HOME)),
    safe(lambda: as_item("10-Year Treasury Yield", fred("DGS10"), "%", "Daily", "FRED / U.S. Treasury", FRED_HOME)),
    safe(lambda: as_item("2-Year Treasury Yield", fred("DGS2"), "%", "Daily", "FRED / U.S. Treasury", FRED_HOME)),
    safe(lambda: as_item("30-Year Mortgage Rate", fred("MORTGAGE30US"), "%", "Weekly", "FRED / Freddie Mac", FRED_HOME)),
    safe(lambda: as_item("WTI Crude Oil", fred("DCOILWTICO"), "$", "Daily", "FRED / EIA", FRED_HOME)),
    safe(lambda: as_item("S&P 500", fred("SP500"), "index", "Daily", "FRED / S&P Dow Jones", FRED_HOME))
]
us = [x for x in us if x]

texas = [
    safe(lambda: as_item("Texas Unemployment Rate", fred("TXUR"), "%", "Monthly", "FRED / BLS", FRED_HOME)),
    safe(lambda: as_item("Texas Nonfarm Employment", fred("TXNA"), "M", "Monthly", "FRED / BLS", FRED_HOME, scale=0.001)),
    safe(lambda: as_item("Texas House Price Index", fred("TXSTHPI"), "index", "Quarterly", "FRED / FHFA", FRED_HOME)),
    safe(lambda: as_item("Texas Building Permits", fred("TXBPPRIV"), "index", "Monthly", "FRED / Census", FRED_HOME)),
    safe(lambda: as_item("WTI Crude Oil", fred("DCOILWTICO"), "$", "Daily", "FRED / EIA", FRED_HOME))
]
texas = [x for x in texas if x]

saudi = [
    safe(lambda: as_item("Saudi GDP Growth", world_bank("SAU", "NY.GDP.MKTP.KD.ZG"), "%", "Annual", "World Bank", WB_HOME)),
    safe(lambda: as_item("Saudi Inflation", world_bank("SAU", "FP.CPI.TOTL.ZG"), "%", "Annual", "World Bank", WB_HOME)),
    safe(lambda: as_item("Saudi Unemployment", world_bank("SAU", "SL.UEM.TOTL.ZS"), "%", "Annual", "World Bank", WB_HOME)),
    safe(lambda: as_item("Saudi GDP per capita", world_bank("SAU", "NY.GDP.PCAP.CD"), "$", "Annual", "World Bank", WB_HOME)),
    safe(lambda: as_item("Brent Crude Oil", fred("DCOILBRENTEU"), "$", "Daily", "FRED / EIA", FRED_HOME))
]
saudi = [x for x in saudi if x]
saudi.insert(0, {
    "name": "USD / SAR",
    "value": 3.75,
    "change": 0.0,
    "date": datetime.now(timezone.utc).date().isoformat(),
    "frequency": "Daily reference",
    "unit": "index",
    "source": "Saudi riyal official peg reference",
    "source_url": "https://www.sama.gov.sa/",
    "history": [{"date": "peg", "value": 3.75}, {"date": "today", "value": 3.75}]
})

global_items = [
    safe(lambda: as_item("World GDP Growth", world_bank("WLD", "NY.GDP.MKTP.KD.ZG"), "%", "Annual", "World Bank", WB_HOME)),
    safe(lambda: as_item("Euro Area GDP Growth", world_bank("EMU", "NY.GDP.MKTP.KD.ZG"), "%", "Annual", "World Bank", WB_HOME)),
    safe(lambda: as_item("China GDP Growth", world_bank("CHN", "NY.GDP.MKTP.KD.ZG"), "%", "Annual", "World Bank", WB_HOME)),
    safe(lambda: as_item("India GDP Growth", world_bank("IND", "NY.GDP.MKTP.KD.ZG"), "%", "Annual", "World Bank", WB_HOME)),
    safe(lambda: as_item("Japan GDP Growth", world_bank("JPN", "NY.GDP.MKTP.KD.ZG"), "%", "Annual", "World Bank", WB_HOME)),
    safe(lambda: as_item("Brent Crude Oil", fred("DCOILBRENTEU"), "$", "Daily", "FRED / EIA", FRED_HOME)),
    safe(lambda: as_item("Gold Price", fred("GOLDAMGBD228NLBM"), "$", "Daily", "FRED / LBMA", FRED_HOME))
]
global_items = [x for x in global_items if x]

lookup = {}
for row in us + texas + saudi + global_items:
    lookup[row["name"]] = row

pulse = []
for name in [
    "S&P 500",
    "10-Year Treasury Yield",
    "Federal Funds Rate",
    "CPI Inflation (YoY)",
    "Unemployment Rate",
    "WTI Crude Oil",
    "USD / SAR",
    "Brent Crude Oil"
]:
    if name in lookup:
        pulse.append(lookup[name])

payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "sections": {
        "pulse": pulse,
        "us": us,
        "texas": texas,
        "saudi": saudi,
        "global": global_items
    }
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print("Wrote", OUT)
