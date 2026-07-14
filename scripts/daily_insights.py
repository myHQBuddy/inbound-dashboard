#!/usr/bin/env python3
"""
Daily insights digest. Summarises YESTERDAY's inbound performance plus the
key standing problems (coverage gaps, callback rate) and emails it once a day.

Always sends (unlike alert.py which is silent when healthy).

Env: GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_TO (default rohit.bagga@myhq.in)
"""

import os
import re
import sys
import json
import smtplib
import datetime as dt
from email.mime.text import MIMEText

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "inbound-dashboard-data.js")
RECIPIENT = os.environ.get("ALERT_TO", "rohit.bagga@myhq.in")
WORK_START, WORK_END = 9, 18


def load_records():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r"const INBOUND_RECORDS\s*=\s*(\[.*?\]);", txt, re.S)
    if not m:
        sys.exit("Could not parse INBOUND_RECORDS.")
    return json.loads(m.group(1))


def pct(a, b):
    return round(a / b * 100) if b else 0


def summarise(records):
    yest = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    ib = [r for r in records if r["dr"] == "inbound" and r["d"] == yest]
    cb = [r for r in records if r["dr"] == "callback" and r["d"] == yest]

    lines = [f"Inbound Call Centre — Daily Insights for {yest}", "=" * 48, ""]

    if not ib:
        lines.append("No inbound calls recorded for this date.")
        return yest, "\n".join(lines)

    ans = sum(1 for r in ib if r["st"] == "answered")
    qm = sum(1 for r in ib if r["mt"].startswith("Queue Missed"))
    am = sum(1 for r in ib if r["mt"] == "Agent Missed")
    lines += [
        f"📊 VOLUME",
        f"   Inbound calls : {len(ib)}",
        f"   Answered      : {ans}  ({pct(ans, len(ib))}%)",
        f"   Queue missed  : {qm}  ({pct(qm, len(ib))}%)",
        f"   Agent missed  : {am}",
        "",
    ]

    # Worst hours by queue-missed
    by_hour = {}
    for r in ib:
        d = by_hour.setdefault(r["h"], {"tot": 0, "ans": 0, "qm": 0, "agents": set()})
        d["tot"] += 1
        if r["st"] == "answered":
            d["ans"] += 1
            if r["ag"]:
                d["agents"].add(r["ag"])
        if r["mt"].startswith("Queue Missed"):
            d["qm"] += 1

    worst = sorted(((h, d) for h, d in by_hour.items() if d["tot"] >= 3),
                   key=lambda x: x[1]["qm"], reverse=True)[:3]
    lines.append("🔴 WORST HOURS (most queue-missed)")
    for h, d in worst:
        lines.append(f"   {h:>2}:00  {d['qm']} missed of {d['tot']}  "
                     f"(AR {pct(d['ans'], d['tot'])}%, {len(d['agents'])} agents)")
    lines.append("")

    # Coverage gaps yesterday
    gaps = [f"{h}:00 ({d['tot']} calls)" for h, d in sorted(by_hour.items())
            if WORK_START <= h <= WORK_END and d["tot"] >= 3 and not d["agents"]]
    lines.append("⏰ COVERAGE GAPS (working hour, 0 agents)")
    lines.append("   " + ("; ".join(gaps) if gaps else "None — full coverage 🎉"))
    lines.append("")

    # Callback performance yesterday
    missed_nums = {r["cn"] for r in ib if r["st"] != "answered" and r["cn"]}
    cb_nums = {r["cn"] for r in cb if r["cn"]}
    reached = len(missed_nums & cb_nums)
    lines += [
        "📞 CALLBACK",
        f"   Missed unique callers : {len(missed_nums)}",
        f"   Called back           : {reached}  ({pct(reached, len(missed_nums))}%)",
        f"   Callbacks made        : {len(cb)}",
        "",
    ]

    # Leads
    prods = {}
    for r in ib + cb:
        if r["st"] == "answered" and r["pr"]:
            prods[r["pr"]] = prods.get(r["pr"], 0) + 1
    if prods:
        lines.append("🎯 LEADS DISPOSED")
        for p in ("AM", "VO", "OD"):
            if prods.get(p):
                lines.append(f"   {p}: {prods[p]}")
        lines.append("")

    lines.append("-" * 48)
    lines.append("Dashboard: https://myhqbuddy.github.io/inbound-dashboard/")
    return yest, "\n".join(lines)


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
    print(f"Daily insights sent to {RECIPIENT}.")


def main():
    records = load_records()
    date, body = summarise(records)
    send_email(f"📊 Inbound daily insights — {date}", body)
    print(body)


if __name__ == "__main__":
    main()
