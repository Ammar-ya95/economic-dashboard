import csv
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "indicators.json"
FRED_HOME = "https://fred.stlouisfed.org/"

def fred(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "economic-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        text = response.read().decode("utf-8")

    rows = csv.DictReader(io.StringIO(text))
    values = []
    for row in rows:
        raw = row.get(series_id)
        if raw and raw != ".":
            values.append({"date": row["DATE"], "value": float(raw)})

    if not values:
        raise RuntimeError(f"No data returned for {series_id}")
    return values

def latest_item(name, series_id, unit, frequency, source):
    series = fred(series_id)
    latest = series[-1]
    previous = series[-2] if len(series) > 1 else latest
    return {
        "name": name,
        "value": latest["value"],
        "change": latest["value"] - previous["value"],
        "date": latest["date"],
        "frequency": frequency,
        "unit": unit,
        "source": source,
        "source_url": FRED_HOME,
        "history": series[-12:]
    }

def yoy_cpi():
    series = fred("CPIAUCSL")
    yoy = []
    for i in range(12, len(series)):
        prev = series[i - 12]["value"]
        cur = series[i]["value"]
        if prev != 0:
            yoy.append({
                "date": series[i]["date"],
                "value": (cur / prev - 1) * 100
            })
    latest = yoy[-1]
    previous = yoy[-2]
    return {
        "name": "CPI Inflation (YoY)",
        "value": latest["value"],
        "change": latest["value"] - previous["value"],
        "date": latest["date"],
        "frequency": "Monthly",
        "unit": "%",
        "source": "FRED / BLS",
        "source_url": FRED_HOME,
        "history": yoy[-12:]
    }

us = [
    yoy_cpi(),
    latest_item("Unemployment Rate", "UNRATE", "%", "Monthly", "FRED / BLS"),
    latest_item("10-Year Treasury Yield", "DGS10", "%", "Daily", "FRED / U.S. Treasury"),
    latest_item("S&P 500", "SP500", "index", "Daily", "FRED / S&P Dow Jones"),
]

texas = [
    latest_item("Texas Unemployment Rate", "TXUR", "%", "Monthly", "FRED / BLS"),
]

saudi = [{
    "name": "USD / SAR Reference Rate",
    "value": 3.75,
    "change": 0.0,
    "date": datetime.now(timezone.utc).date().isoformat(),
    "frequency": "Reference",
    "unit": "index",
    "source": "Saudi riyal peg reference",
    "source_url": "https://www.sama.gov.sa/",
    "history": [
        {"date": "previous", "value": 3.75},
        {"date": "current", "value": 3.75}
    ]
}]

global_items = [
    latest_item("WTI Crude Oil", "DCOILWTICO", "$", "Daily", "FRED / EIA"),
]

pulse = [
    us[3],
    us[2],
    us[0],
    us[1],
    texas[0],
    global_items[0],
    saudi[0],
]

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

OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"Updated {OUT}")
