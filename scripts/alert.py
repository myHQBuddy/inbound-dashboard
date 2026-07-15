#!/usr/bin/env python3
"""
Business-health alert. Reads the freshly-synced inbound-dashboard-data.js,
checks TODAY's operation against data-derived thresholds, and emails
rohit.bagga@myhq.in ONLY when something is wrong.

Checks:
  1. Coverage short  — a core hour (10-17) with real demand (>=5 calls) but
                       fewer than 2 active agents answering
  2. Answer-rate      — today's answer rate < 65%  (norm ~68%)
  3. Callback breakdown — missed callers today with 0 callback attempts
  4. Sync freshness   — data file didn't update (GENERATED_AT not today)

Silent when everything is healthy (no email). Env:
  GMAIL_USER, GMAIL_APP_PASSWORD  — Gmail SMTP creds (from repo secrets)
  ALERT_TO                        — recipient (defaults to rohit.bagga@myhq.in)
"""

import os
import re
import sys
import json
import smtplib
import datetime as dt
from email.mime.text import MIMEText

AR_THRESHOLD = 65             # answer-rate alert below this %
# Coverage rule: every CORE working hour should have >=2 agents answering.
# "Active agents" = distinct agents who answered an inbound call that hour
# (same definition as the dashboard's Active Agents chart).
CORE_START, CORE_END = 10, 17     # check hours 10:00..17:00 (10am-6pm core)
MIN_AGENTS = 2                    # want at least this many active agents/hour
MIN_CALLS_FOR_COVERAGE = 5        # only judge coverage when demand was real
                                  # (quiet hours naturally show few agents)
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "inbound-dashboard-data.js")
RECIPIENT = os.environ.get("ALERT_TO", "rohit.bagga@myhq.in")


def load_records():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r"const INBOUND_RECORDS\s*=\s*(\[.*?\]);", txt, re.S)
    if not m:
        sys.exit("Could not parse INBOUND_RECORDS from data file.")
    records = json.loads(m.group(1))
    gen = re.search(r'GENERATED_AT\s*=\s*"([^"]*)"', txt)
    generated_at = gen.group(1) if gen else ""
    return records, generated_at


def check(records, generated_at):
    """Return a list of alert strings (empty = healthy)."""
    today = dt.date.today().isoformat()
    alerts = []

    today_ib = [r for r in records if r["dr"] == "inbound" and r["d"] == today]
    today_cb = [r for r in records if r["dr"] == "callback" and r["d"] == today]

    # --- 4. sync freshness ---
    if not generated_at.startswith(today):
        alerts.append(f"⚠️ DATA STALE: file last generated {generated_at or 'unknown'} — sync may be failing.")

    # If no inbound today yet (early morning), skip volume-based checks quietly.
    if not today_ib:
        return alerts

    # --- 2. answer rate ---
    ans = sum(1 for r in today_ib if r["st"] == "answered")
    ar = round(ans / len(today_ib) * 100)
    if ar < AR_THRESHOLD:
        alerts.append(f"📉 ANSWER RATE {ar}% today ({ans}/{len(today_ib)}) — below {AR_THRESHOLD}% target.")

    # --- 1. coverage: every core hour should have >=2 active agents ---
    by_hour = {}
    for r in today_ib:
        h = r["h"]
        d = by_hour.setdefault(h, {"tot": 0, "agents": set()})
        d["tot"] += 1
        if r["st"] == "answered" and r["ag"]:
            d["agents"].add(r["ag"])
    now_hour = dt.datetime.now().hour
    gap_hours = []
    for h in range(CORE_START, CORE_END + 1):
        if h >= now_hour:        # don't judge an hour that hasn't finished
            continue
        d = by_hour.get(h)
        if not d:
            continue
        # Only flag when there was real demand (avoids false alarms on quiet hours).
        if d["tot"] >= MIN_CALLS_FOR_COVERAGE and len(d["agents"]) < MIN_AGENTS:
            gap_hours.append(f"{h}:00 ({len(d['agents'])} agent(s), {d['tot']} calls)")
    if gap_hours:
        alerts.append(
            f"🚨 COVERAGE SHORT — fewer than {MIN_AGENTS} agents during: "
            + "; ".join(gap_hours)
        )

    # --- 3. callback breakdown ---
    missed_today = [r for r in today_ib if r["st"] != "answered"]
    if missed_today and not today_cb:
        alerts.append(f"📞 CALLBACK GAP — {len(missed_today)} missed calls today, 0 callbacks attempted.")

    return alerts


def send_email(subject, body):
    user = os.environ.get("GMAIL_USER", "").strip()
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    if not user or not pw:
        sys.exit("ERROR: GMAIL_USER / GMAIL_APP_PASSWORD not set.")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = RECIPIENT
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [RECIPIENT], msg.as_string())
    print(f"Alert email sent to {RECIPIENT}.")


def main():
    records, generated_at = load_records()
    alerts = check(records, generated_at)
    if not alerts:
        print("Healthy — no alert.")
        return
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    body = (f"Inbound Call Centre — health alert ({now})\n"
            + "=" * 48 + "\n\n"
            + "\n\n".join(alerts)
            + "\n\n" + "-" * 48
            + "\nDashboard: https://myhqbuddy.github.io/inbound-dashboard/\n")
    send_email(f"🔴 Inbound alert — {len(alerts)} issue(s) [{now}]", body)
    print(body)


if __name__ == "__main__":
    main()
