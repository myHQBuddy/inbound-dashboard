# myHQ Inbound Call Centre Dashboard

A single-file HTML dashboard for monitoring inbound call centre performance — volume, hourly patterns, callbacks, leads, and action intelligence.

---

## Files to Share

| File | Required | Purpose |
|------|----------|---------|
| `inbound-dashboard.html` | Yes | The complete dashboard — all charts and logic |
| `inbound-dashboard-data.js` | Yes | Call records data (snapshot of all calls) |

Both files must be in the **same folder**. Open `inbound-dashboard.html` in any modern browser — no server needed.

> Requires internet access for Chart.js (loaded from CDN). Works offline if Chart.js is cached.

---

## Dashboard Tabs

| Tab | What it shows |
|-----|--------------|
| **Volume** | Daily call volume, answer rate, missed call breakdown, day-of-week patterns |
| **Hourly Pattern** | Heatmap by hour — when calls peak, when answer rates drop |
| **Callbacks** | Missed call callback coverage, reconnect rate, time-to-connect, callback funnel, re-connection frequency |
| **Leads** | Disposed calls by product (AM/VO/OD), new vs existing, daily trend |
| **Action** | Active agents by 7-min slot (step line chart), unreachable contacts, fresh leads, 8 insight cards |

---

## Filters

- **Today / 7D / 14D / 30D / All** — quick date presets (top right)
- **Custom date range** — `dd/mm/yyyy` pickers (top right)
- All charts and KPIs update live on filter change

---

## Data File Format

`inbound-dashboard-data.js` exports four JS constants:

```js
const INBOUND_RECORDS = [...];   // array of call records
const GENERATED_AT = "2026-07-14 08:00";
const DATE_FROM = "2026-06-01";
const DATE_TO   = "2026-07-14";
```

### Record Fields

| Field | Type | Description |
|-------|------|-------------|
| `d` | string | Call date `YYYY-MM-DD` |
| `h` | number | Hour of day (0–23) |
| `ti` | string | Call time `HH:MM:SS` |
| `w` | string | Day of week abbreviated (`Mon`, `Tue` …) |
| `dr` | string | Direction: `inbound` or `callback` |
| `st` | string | Status: `answered` or `missed` |
| `mt` | string | Missed type (e.g. `Queue Missed - Within Hours`) |
| `ah` | number | After-hours flag: `1` = yes, `0` = no |
| `qt` | number | Queue wait time (seconds) |
| `as` | number | Answered duration (seconds) |
| `pr` | string | Product: `AM`, `VO`, `OD`, or blank |
| `ct` | string | Call type: `New`, `Existing`, `Query`, etc. |
| `cl` | string | Caller telecom circle |
| `cn` | string | Client phone number (normalized `+91XXXXXXXXXX`) |
| `ag` | string | Agent name |
| `sc` | string | Source campaign name |

---

## Data Source

Records come from **TATA SmartFlo** (cloud telephony). The Python scripts in `/scripts/` sync and export:

```
scripts/
  tata_sync.py          # Fetches from TATA SmartFlo API → inbound_call_records.csv
  export_inbound_json.py  # Converts CSV → inbound-dashboard-data.js
  sync.py               # Runs both steps in sequence
  config.py             # API credentials (not shareable)
```

To update the data file with fresh records:
```bash
python3 scripts/sync.py
```

Then re-share `inbound-dashboard-data.js`.

---

## Disposition Mapping (Lead Classification)

Calls are classified by the agent's disposition tag in the telephony system:

| Disposition Tag | Product | Call Type |
|----------------|---------|-----------|
| AM New | AM | New |
| AM Existing | AM | Existing |
| VO New | VO | New |
| VO Existing | VO | Existing |
| OD New | OD | New |
| OD Existing | OD | Existing |
| OD Queries | OD | Query |
| VO Queries | VO | Query |
| Others / Undisposed / Missed | — | — |

---

## Action Tab — Contact Cards

The three KPI cards on the Action tab are clickable:

| Card | Shows |
|------|-------|
| **10+ Attempts, Not Connected** | Callers tried 10+ times with no answer — likely unreachable |
| **0 Callbacks Made** | Missed calls where no callback was ever attempted |
| **< 3 Attempts, Not Connected** | Fresh missed leads with fewer than 3 callback attempts — priority queue |

Click any card to see the full phone number list with attempt counts and dates.

---

## Callbacks Tab — Charts Explained

### Callback Funnel — Did they pick up?
Each row = unique callers who received that callback attempt. Shows how many connected on each call vs didn't pick up. Once a caller connects, they exit the funnel (not counted in subsequent rows). Voicemail does not count as connected.

- **1st call / 2nd call / 3rd call / 4th call / 5+ calls**
- Drop-off line: `out of X who didn't pick up → Y got another call · Z not attempted again`

### How Many Times Did a Client Connect?
Shows the distribution of clients by total number of successful connections:
- Connected once, twice, 3 times, 4 times, 5+ times
- Helps identify how often the team reconnects with the same client

### Time to First Callback
Bar chart showing how quickly the team called back after a missed call: <1 hr, 1–4 hr, 4–24 hr, 1–2 days, 2+ days, Never.

---

## Action Tab — Active Agents Chart

- Step line chart, 7-minute slot resolution (9:00 AM to 9:00 PM)
- Shows unique agents who handled at least one inbound call per slot
- Color zones by agent count: gray (0) → pink (1) → orange (2) → red (3+)
- Hover anywhere on chart to see agent names for that slot
- Date picker top-right to view any historical date

---

## Notes

- All data processing happens **client-side** in the browser — no backend required
- Phone numbers are stored as-is from the telephony system (`+91XXXXXXXXXX` format)
- "Leads" counts include both answered inbound calls and answered callbacks to missed calls
- Undisposed % is calculated against inbound answered calls only (not callbacks)
- Voicemail callbacks (`ct = Voice Mail`) are treated as "not connected" across all metrics
