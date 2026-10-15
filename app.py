"""WattWitness - local review app.  Run:  python app.py   (opens http://127.0.0.1:8501)

Serves ui/index.html plus a small JSON API built from the detector outputs in outputs/.
The app never re-implements a detector rule or threshold: it only reads what
scripts/detect_evaluate.py wrote and re-uses its physics_pairs() for the charts.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from datetime import datetime
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
UI = ROOT / "ui" / "index.html"
REVIEWS = OUT / "operator_review_decisions.csv"
sys.path.insert(0, str(ROOT / "scripts"))
from add_measurement_noise import DROPOUT_GROUPS  # noqa: E402
from detect_evaluate import FEATURES, RESIDUALS, physics_pairs  # noqa: E402
from review_log import append_decision, read_decisions  # noqa: E402

VIEWS = {"fault": ("Fault replay", "perturbed_test.csv", "alert_log.csv"),
         "clean": ("Clean window", "clean_test.csv", "baseline_alert_log.csv")}
DECISIONS = ["Confirm data issue", "Likely genuine operating event", "Escalate for further review", "Dismiss alert"]
KIND = {"Likely telemetry / data inconsistency": "bad", "Telemetry gap": "gap",
        "Possible data-quality issue": "rule", "Potential operating event - verify context": "event"}
CHECK = {  # key: (short name, headline, reported label, implied label)
    "power_balance_kw": ("Energy balance", "Energy does not add up",
                         "Sources (PV + wind + grid)", "Uses (load + battery + curtailment)"),
    "grid_kw": ("Grid: power vs V × I", "Grid meter disagrees with grid voltage × current",
                "Grid meter", "Grid voltage × current"),
    "pv_source_vs_inverter_kw": ("PV meter vs inverter", "PV meter disagrees with the PV inverter",
                                 "PV meter", "PV inverter output"),
    "pv_ac_kw": ("PV AC: power vs V × I", "PV AC power disagrees with AC voltage × current",
                 "PV AC power", "AC voltage × current"),
    "pv_dc_kw": ("PV DC: power vs V × I", "PV DC power disagrees with DC voltage × current",
                 "PV DC power", "DC voltage × current"),
    "battery_current_a": ("Battery: current vs power", "Battery current does not match battery power",
                          "Battery current", "Current implied by battery power"),
}
DEVICE = {c: d for d, chans in DROPOUT_GROUPS.items() if d != "whole data logger" for c in chans}


def unit(channel: str) -> str:
    return "V" if "Voltage" in channel else "A" if "Current" in channel else "kWh" if channel == "Battery SOC" else "kW"


def series(values) -> list:
    s = pd.Series(values, dtype=float).round(3)
    return [None if np.isnan(v) else float(v) for v in s.to_numpy()]


def read(name: str) -> pd.DataFrame:
    df = pd.read_csv(OUT / name)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    return df


@lru_cache(maxsize=None)
def meta() -> dict:
    summary = json.loads((OUT / "evaluation_summary.json").read_text())
    tables = {}
    for n in ["evaluation_metrics", "event_level_results", "fault_type_recall", "noise_robustness", "untouched_test_alarm_rates"]:
        df = pd.read_csv(OUT / f"{n}.csv")
        tables[n] = df.astype(object).where(df.notna(), None).to_dict(orient="records")
    return {"summary": summary, **tables, "decisions": DECISIONS,
            "checks": {k: {"name": v[0], "unit": RESIDUALS[k][1]} for k, v in CHECK.items()},
            "pairLabels": {k: [v[2], v[3]] for k, v in CHECK.items()},
            "channels": {k: RESIDUALS[k][2] for k in CHECK}}


def describe(row: pd.Series, res: dict, limits: dict) -> dict:
    """Plain-language headline, one-sentence explanation and the chart to show for one alert."""
    checks = []
    for k in CHECK:
        a, b = res[k]
        gap = None if pd.isna(a) or pd.isna(b) else float(a - b)
        checks.append({"key": k, "gap": gap, "limit": limits[k], "ratio": None if gap is None else abs(gap) / limits[k],
                       "fired": f"{k}" in str(row["checks_fired"]).split(";")})
    fired = [c for c in checks if c["fired"]]
    missing = [c for c in FEATURES if pd.isna(row[c])]
    rules = [c.split(":", 1) for c in str(row["checks_fired"]).split(";") if ":" in c]
    if missing:
        devices = sorted({DEVICE.get(c, c) for c in missing})
        whole = len(missing) == len(FEATURES)
        head = "The whole data logger went silent" if whole else (
            f"{missing[0]} is missing" if len(missing) == 1 else f"No reading from the {' and '.join(devices)}")
        text = (f"{', '.join(missing) if len(missing) <= 4 else str(len(missing)) + ' channels'} "
                f"{'has' if len(missing) == 1 else 'have'} no value this hour, so nothing can be cross-checked until the data are recovered.")
        chart = {"kind": "channels", "channels": missing[:3]}
    elif fired:
        top = max(fired, key=lambda c: c["ratio"] or 0)
        name, head, la, lb = CHECK[top["key"]]
        u = RESIDUALS[top["key"]][1]
        a, b = res[top["key"]]
        times = f"{top['ratio']:.1f}×" if top["ratio"] < 10 else f"{top['ratio']:.0f}×"
        text = (f"{la} reads {a:,.1f} {u}, but {lb[0].lower() + lb[1:]} gives {b:,.1f} {u}: a {abs(a - b):,.1f} {u} gap, "
                f"{times} the normal meter-error limit of {top['limit']:.1f} {u}.")
        chart = {"kind": "pair", "key": top["key"]}
    elif rules:
        rule, ch = rules[0]
        if rule == "spike":
            head = f"{ch} spiked for one hour"
            text = (f"{ch} jumped by {row['_jump']:+,.0f} {unit(ch)} and came straight back the next hour: "
                    "the shape of a glitch rather than a real change. Related meters stayed consistent.")
        else:
            head = f"{ch} looks stuck"
            text = f"{ch} repeated exactly {row[ch]:,.1f} {unit(ch)} for four hours or more. A working meter always moves a little."
        chart = {"kind": "channels", "channels": [ch]}
    else:
        head, text, chart = "Flagged reading", str(row["explanation"]), {"kind": "channels", "channels": ["Grid Power"]}
    return {"headline": head, "sentence": text, "chart": chart, "checks": checks}


@lru_cache(maxsize=None)
def view(name: str) -> dict:
    label, telemetry_file, log_file = VIEWS[name]
    tel = read(telemetry_file)
    log = read(log_file)
    limits = json.loads((OUT / "evaluation_summary.json").read_text())["physics_thresholds"]
    pairs = physics_pairs(tel)
    alerts = []
    for i in np.flatnonzero(log["alert_rules_physics"].to_numpy() == 1):
        row = pd.concat([tel.iloc[i], log.iloc[i].drop("Timestamp")])
        row["_jump"] = 0.0
        for rule in str(row["checks_fired"]).split(";"):
            if rule.startswith("spike:"):
                ch = rule.split(":", 1)[1]
                row["_jump"] = float(tel[ch].diff().iloc[i])
        info = describe(row, {k: (a.iloc[i], b.iloc[i]) for k, (a, b) in pairs.items()}, limits)
        alerts.append({"i": int(i), "t": tel["Timestamp"].iloc[i].strftime("%Y-%m-%dT%H:%M"),
                       "kind": KIND.get(row["interpretation"], "rule"), "interpretation": row["interpretation"],
                       "evidence": row["evidence_label"], "score": float(row["evidence_score"]),
                       "action": row["recommended_action"], "detail": row["explanation"], **info})
    return {"name": name, "label": label,
            "t": tel["Timestamp"].dt.strftime("%Y-%m-%dT%H:%M").tolist(),
            "signals": {c: series(tel[c]) for c in FEATURES},
            "pairs": {k: {"a": series(a), "b": series(b)} for k, (a, b) in pairs.items()},
            "alerts": alerts}


@lru_cache(maxsize=None)
def truth() -> dict:
    ev = read("evaluation_predictions.csv")
    manifest = pd.read_csv(OUT / "fault_manifest.csv")
    return {"fault_type": ev["fault_type"].fillna("none").tolist(), "event_id": ev["fault_event_id"].fillna("").tolist(),
            "events": manifest[["event_id", "fault_type", "affected_signal", "start_index", "end_index", "severity"]].to_dict(orient="records")}


def decisions() -> list[dict]:
    return read_decisions(REVIEWS).to_dict(orient="records")


def record_decision(body: dict) -> list[dict]:
    """Validate a decision from the UI and append it to the review log."""
    name = body.get("view")
    if name not in VIEWS:
        raise ValueError("unknown view")
    if body.get("decision") not in DECISIONS:
        raise ValueError("unknown decision")
    alert = next((a for a in view(name)["alerts"] if a["i"] == body.get("i")), None)
    if alert is None:
        raise ValueError("unknown alert")
    append_decision(REVIEWS, {
        "decision_timestamp": datetime.now().isoformat(timespec="seconds"), "scenario": VIEWS[name][0],
        "event_timestamp": alert["t"].replace("T", " ") + ":00", "reviewer": str(body.get("reviewer") or "Demo operator")[:80],
        "decision": body["decision"], "notes": str(body.get("notes") or "")[:2000], "interpretation": alert["interpretation"],
        "evidence_score": f"{alert['score']:.2f}", "explanation": alert["detail"], "suggested_check": alert["action"]})
    return decisions()


class Handler(BaseHTTPRequestHandler):
    def send(self, status: int, payload, content_type: str = "application/json") -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        try:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self.send(200, UI.read_bytes(), "text/html; charset=utf-8")
            routes = {"/api/meta": meta, "/api/view/fault": lambda: view("fault"), "/api/view/clean": lambda: view("clean"),
                      "/api/truth": truth, "/api/decisions": decisions}
            if path in routes:
                return self.send(200, routes[path]())
            self.send(404, {"error": "not found"})
        except FileNotFoundError as exc:
            self.send(503, {"error": f"Missing output file ({Path(str(exc.filename)).name}). Run: python scripts/run_phase1_pipeline.py"})
        except Exception as exc:  # report, never crash the server
            self.send(500, {"error": str(exc)})

    def do_POST(self):  # noqa: N802
        if self.path != "/api/decisions":
            return self.send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 10_000)) or b"{}")
            self.send(200, record_decision(body))
        except (ValueError, json.JSONDecodeError) as exc:
            self.send(400, {"error": str(exc)})
        except Exception as exc:
            self.send(500, {"error": str(exc)})

    def log_message(self, *args):  # keep the terminal quiet
        pass


def main():
    ap = argparse.ArgumentParser(description="WattWitness local review app")
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)  # local only
    url = f"http://127.0.0.1:{a.port}/"
    print(f"WattWitness review app running at {url}  (Ctrl+C to stop)", flush=True)
    if not a.no_browser:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
