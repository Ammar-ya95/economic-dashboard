import json
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "indicators.json"

if OUT.exists():
    payload = json.loads(OUT.read_text(encoding="utf-8"))
else:
    payload = {
        "generated_at": None,
        "sections": {
            "pulse": [],
            "us": [],
            "texas": [],
            "saudi": [],
            "global": []
        }
    }

payload["generated_at"] = datetime.now(timezone.utc).isoformat()

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

print("Heartbeat refresh succeeded.")
print(f"Updated timestamp in {OUT}")
