# Data Sync — TATA SmartFlo → dashboard

Automatically refreshes `inbound-dashboard-data.js` every 3 hours via GitHub Actions.

## How it works

```
TATA SmartFlo API  →  scripts/sync.py  →  inbound-dashboard-data.js  →  git push  →  GitHub Pages rebuilds
```

- **`scripts/sync.py`** — pages through the SmartFlo Call Detail Records API for the
  last `DAYS_BACK` days (default 44), transforms each record into the dashboard's
  `INBOUND_RECORDS` shape, and writes `inbound-dashboard-data.js`.
- **`.github/workflows/refresh.yml`** — runs the script on a `0 */3 * * *` cron
  (every 3 hours, UTC), copies `inbound-dashboard.html` → `index.html`, and commits
  only if the data actually changed.

## One-time setup: the API token

The workflow reads the SmartFlo JWT from a repo **secret** named `TATA_TOKEN`
(never committed to code).

1. Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. Name: `TATA_TOKEN`
3. Value: the SmartFlo JWT (raw token — the workflow sends it as the `Authorization` header as-is, no `Bearer ` prefix)
4. Save.

To run immediately without waiting for the cron: repo → **Actions** → **Refresh dashboard data** → **Run workflow**.

## Running locally (optional)

Requires Python 3 (no third-party packages — standard library only):

```bash
export TATA_TOKEN="your-token"
export DAYS_BACK=44
python scripts/sync.py
```

## Field mapping (API → dashboard)

| Dashboard | Source | Notes |
|-----------|--------|-------|
| `d`, `ti` | `date`, `time` | direct |
| `h`, `w`, `ah` | derived from date/time | `ah=1` when hour ≥ 20 or < 9 |
| `dr` | `direction` + `dialer_call_details.call_type` | inbound stays; manual outbound → `callback` |
| `st` | `status` | answered / missed |
| `mt` | `dialer_call_details.disposition_code` + hours + `missed_agents` | Agent / Queue (Within/After Hours) / Callback Missed / Answered |
| `qt` | `dialer_call_details.call_wait_time` | queue wait seconds |
| `as` | `answered_seconds` | talk seconds |
| `pr`, `ct` | `dialer_call_details.disposition_name` | see disposition map in `sync.py` |
| `cl` | `circle.circle` | telecom circle |
| `cn` | `client_number` | normalized to `+91XXXXXXXXXX` |
| `ag` | `agent_name` | |
| `sc` | `service` | source campaign |

### Disposition → product/type map

Maintained in `DISPO_MAP` inside `sync.py`:

| disposition_name | product | type |
|------------------|---------|------|
| AM New / AM Existing | AM | New / Existing |
| VO New / VO Existing / VO Queries | VO | New / Existing / Query |
| OD New / OD Existing / OD Queries | OD | New / Existing / Query |
| Others / Undisposed / Queue Missed | — | (kept as `ct` label) |

**If the call-centre adds a new disposition tag in SmartFlo, add it to `DISPO_MAP`**
or it will land in `ct` without a product and won't count as an AM/VO/OD lead.

## Safety

- The script **aborts** rather than writing an empty file if the API returns no
  records, so a bad API response can't wipe the dashboard.
- The workflow commits only when the data changed, keeping history clean.
