#!/usr/bin/env python3
"""
Incremental TATA SmartFlo sync.

Mirrors the original tata_sync.py design:
  - inbound_call_records.csv is the committed baseline (full history).
  - sync_state.json stores last_sync (IST 'YYYY-MM-DD HH:MM:SS').
  - Each run fetches only from (last_sync - OVERLAP) to now, dedups by call_id,
    appends genuinely-new rows to the CSV, and bumps last_sync.
  - Then regenerates inbound-dashboard-data.js from the FULL CSV.

Fetch structure & classification match tata_sync.py exactly (three sources:
inbound-type + callbacks from the outbound feed, plus the inbound feed).

Env: TATA_TOKEN (raw JWT as Authorization header, no 'Bearer').
"""

import os
import re
import csv
import sys
import json
import time
import datetime as dt
import urllib.request
import urllib.parse
import urllib.error

API_URL = "https://api-smartflo.tatateleservices.com/v1/call/records"
PAGE_LIMIT = 500
OVERLAP_MINUTES = 5        # re-fetch this many minutes before last_sync (catch late records)
OFFICE_START, OFFICE_END = 9, 20
REQUEST_PAUSE = 0.3
MAX_RETRIES = 4

# IST (UTC+5:30) — TATA timestamps are IST.
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "inbound_call_records.csv")
STATE_PATH = os.path.join(BASE_DIR, "sync_state.json")
JS_PATH = os.path.join(BASE_DIR, "inbound-dashboard-data.js")

COLUMNS = [
    "call_id", "call_date", "call_time", "day_of_week", "hour_of_day",
    "client_number", "agent_name", "status", "call_direction",
    "missed_type", "is_after_hours",
    "call_duration", "answered_seconds", "queue_time", "queue_name",
    "service", "call_type", "product", "disposition_name",
    "department_name", "did_number",
    "caller_operator", "caller_circle", "hangup_cause", "recording_url",
    "campaign_name",
]

DISPOSITION_MAP = {
    "AM New": ("AM", "New"), "AM Existing": ("AM", "Existing"),
    "VO New": ("VO", "New"), "VO Existing": ("VO", "Existing"),
    "OD New": ("OD", "New"), "OD Existing": ("OD", "Existing"),
    "OD Queries": ("OD", "Query"), "VO Queries": ("VO", "Query"),
    "Others": ("", "Other"), "Voice Mail": ("", "Voice Mail"),
    "Did Not Respond": ("", "Did Not Respond"), "Invalid Num": ("", "Invalid"),
    "Queue Missed": ("", ""), "Missed By Agent": ("", "Missed By Agent"),
    "Receiver is Busy": ("", "Busy"), "Receiver is busy": ("", "Busy"),
    "System Failure": ("", "System Failure"), "Call Rejected": ("", "Call Rejected"),
    "Undisposed": ("", "Undisposed"), "Unallocated Number": ("", "Unallocated"),
    "Network Issue": ("", "Network Issue"), "Channel Issue": ("", "Channel Issue"),
    "Not Reachable": ("", "Not Reachable"), "No Answer": ("", "No Answer"),
}

DOW_SHORT = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu",
             "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun"}


# ── HTTP ──────────────────────────────────────────────────────────────────────
def token():
    t = os.environ.get("TATA_TOKEN", "").strip()
    if not t:
        sys.exit("ERROR: TATA_TOKEN not set.")
    return t


def http_get(params, auth):
    url = API_URL + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers={"Authorization": auth, "accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 * attempt); continue
            raise SystemExit(f"ERROR fetching {url}\n{last_err}")
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = str(e); time.sleep(2 * attempt)
    raise SystemExit(f"ERROR: retries exhausted.\n{last_err}")


def _paginate(auth, from_dt, to_dt, direction):
    rows, page = [], 1
    while True:
        data = http_get({"from_date": from_dt, "to_date": to_dt,
                         "direction": direction, "limit": PAGE_LIMIT, "page": page}, auth)
        batch = data.get("results", []) or []
        rows.extend(batch)
        count = int(data.get("count", 0) or 0)
        got = (page - 1) * PAGE_LIMIT + len(batch)
        print(f"  [{direction}] page {page}: +{len(batch)} ({got}/{count})", flush=True)
        if not batch or got >= count:
            break
        page += 1
        time.sleep(REQUEST_PAUSE)
    return rows


def fetch_all(auth, from_dt, to_dt):
    """Three sources, exactly like tata_sync.py; deduped by call_id in main()."""
    outbound = _paginate(auth, from_dt, to_dt, "outbound")
    inbound_calls = [r for r in outbound
                     if (r.get("dialer_call_details") or {}).get("call_type", "").lower() == "inbound"]
    callbacks = [r for r in outbound
                 if (r.get("dialer_call_details") or {}).get("call_type", "").lower() != "inbound"]
    raw_inbound = _paginate(auth, from_dt, to_dt, "inbound")
    return inbound_calls + callbacks + raw_inbound


# ── Transform (matches tata_sync.py) ─────────────────────────────────────────
def normalize_number(num):
    n = (num or "").strip()
    if not n or n.startswith("+"):
        return n
    if n.startswith("91") and len(n) == 12:
        return "+" + n
    if len(n) == 10:
        return "+91" + n
    return n


def parse_disposition(dcd):
    name = (dcd.get("disposition_name") or "").strip()
    if name in DISPOSITION_MAP:
        return DISPOSITION_MAP[name]
    return ("", name) if name else ("", "")


def transform(rec):
    dcd = rec.get("dialer_call_details") or {}
    service = rec.get("service") or ""
    description = rec.get("description") or ""
    call_time = rec.get("time") or "00:00:00"
    try:
        hour = int(call_time.split(":")[0])
    except Exception:
        hour = 0

    is_ah = ("After office" in service or "After office" in description
             or not (OFFICE_START <= hour < OFFICE_END))

    if not dcd:
        direction = "inbound"
    elif (dcd.get("call_type") or "").lower() == "inbound":
        direction = "inbound"
    else:
        direction = "callback"

    status = rec.get("status") or ""
    if status == "answered":
        mt = "Answered"
    elif direction == "callback":
        mt = "Callback Missed"
    elif is_ah:
        mt = "Queue Missed - After Hours"
    elif (dcd.get("disposition_name") or "").strip() == "Missed By Agent":
        mt = "Agent Missed"
    else:
        mt = "Queue Missed - Within Hours"

    product, ctype = parse_disposition(dcd)
    try:
        queue_time = int(dcd.get("call_wait_time") or 0)
    except Exception:
        queue_time = 0

    call_date = rec.get("date") or ""
    try:
        dow = dt.datetime.strptime(f"{call_date} {call_time}", "%Y-%m-%d %H:%M:%S").strftime("%A")
    except Exception:
        dow = ""
    circle = rec.get("circle") or {}

    return {
        "call_id": rec.get("call_id") or rec.get("uuid") or "",
        "call_date": call_date, "call_time": call_time, "day_of_week": dow,
        "hour_of_day": hour, "client_number": normalize_number(rec.get("client_number") or ""),
        "agent_name": rec.get("agent_name") or "", "status": status,
        "call_direction": direction, "missed_type": mt,
        "is_after_hours": "Yes" if is_ah else "No",
        "call_duration": rec.get("call_duration") or 0,
        "answered_seconds": rec.get("answered_seconds") or 0,
        "queue_time": queue_time, "queue_name": dcd.get("inbound_queue") or "",
        "service": service, "call_type": ctype, "product": product,
        "disposition_name": (dcd.get("disposition_name") or "").strip(),
        "department_name": rec.get("department_name") or "",
        "did_number": rec.get("did_number") or "",
        "caller_operator": circle.get("operator") or "", "caller_circle": circle.get("circle") or "",
        "hangup_cause": rec.get("hangup_cause") or "", "recording_url": rec.get("recording_url") or "",
        "campaign_name": dcd.get("campaign_name") or "",
    }


# ── CSV / state ──────────────────────────────────────────────────────────────
def load_existing():
    if not os.path.exists(CSV_PATH):
        return [], set()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = {r["call_id"] for r in rows if r.get("call_id")}
    return rows, ids


def write_csv(rows):
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def load_last_sync():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f).get("last_sync", "")
    return (dt.datetime.now(IST) - dt.timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")


def save_last_sync(ts):
    with open(STATE_PATH, "w") as f:
        json.dump({"last_sync": ts}, f)


# ── CSV -> dashboard JS ──────────────────────────────────────────────────────
def _i(v):
    try:
        return int(v)
    except Exception:
        return 0


def regenerate_js(rows):
    records = []
    for r in rows:
        records.append({
            "d": r["call_date"], "h": _i(r["hour_of_day"]), "ti": r["call_time"],
            "w": DOW_SHORT.get(r["day_of_week"], (r["day_of_week"] or "")[:3]),
            "dr": r["call_direction"], "st": r["status"], "mt": r["missed_type"],
            "ah": 1 if r["is_after_hours"] == "Yes" else 0,
            "qt": _i(r["queue_time"]), "as": _i(r["answered_seconds"]),
            "pr": r["product"], "ct": r["call_type"], "cl": r["caller_circle"],
            "cn": r["client_number"], "ag": r["agent_name"], "sc": r["service"],
        })
    records.sort(key=lambda x: (x["d"], x["ti"]))
    dates = [r["d"] for r in records if r["d"]]
    gen = dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    body = (
        "const INBOUND_RECORDS = " + json.dumps(records, separators=(",", ":"), ensure_ascii=False) + ";\n"
        + f'const GENERATED_AT = "{gen}";\n'
        + f'const DATE_FROM = "{min(dates) if dates else ""}";\n'
        + f'const DATE_TO   = "{max(dates) if dates else ""}";\n'
    )
    with open(JS_PATH, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"Regenerated JS: {len(records)} records, {min(dates)}..{max(dates)}", flush=True)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    auth = token()
    existing_rows, existing_ids = load_existing()
    print(f"Baseline CSV: {len(existing_rows)} rows.", flush=True)

    last_sync = load_last_sync()
    try:
        base = dt.datetime.strptime(last_sync, "%Y-%m-%d %H:%M:%S")
    except Exception:
        base = dt.datetime.now(IST).replace(tzinfo=None) - dt.timedelta(days=1)
    from_dt = (base - dt.timedelta(minutes=OVERLAP_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    now_ist = dt.datetime.now(IST)
    to_dt = now_ist.strftime("%Y-%m-%d %H:%M:%S")
    print(f"Incremental fetch: {from_dt} -> {to_dt} (overlap {OVERLAP_MINUTES}m)", flush=True)

    raw = fetch_all(auth, from_dt, to_dt)
    transformed = [transform(r) for r in raw]
    new_rows = [r for r in transformed if r["call_id"] and r["call_id"] not in existing_ids]
    # dedup within this batch too
    seen = set()
    deduped = []
    for r in new_rows:
        if r["call_id"] in seen:
            continue
        seen.add(r["call_id"])
        deduped.append(r)
    print(f"Fetched {len(raw)} raw, {len(deduped)} genuinely new.", flush=True)

    all_rows = existing_rows + deduped
    if deduped:
        write_csv(all_rows)
    save_last_sync(to_dt)
    regenerate_js(all_rows)


if __name__ == "__main__":
    main()
