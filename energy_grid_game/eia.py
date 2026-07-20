"""EIA (U.S. Energy Information Administration) open-data client.

Pulls a single day of real hourly grid data for a region so Free Play / Scenario
modes can be seeded with what actually happened on the ground:

  * hourly DEMAND      -> electricity/rto/region-data/data/      (type = D)
  * hourly GENERATION  -> electricity/rto/fuel-type-data/data/   (by fuel type)

Both are fetched for the 24 hours of the chosen local date, aligned onto a
0..23 hour grid, and returned as plain MW lists. Everything is best-effort: any
network / SSL / parse failure returns None and the caller falls back to the
synthetic curves, so the game never hard-depends on connectivity. Successful
pulls are cached to disk so re-selecting a region/date (or replaying offline)
doesn't hit the API again.

Docs: https://www.eia.gov/opendata/
"""
import datetime as _dt
import json
import os
import ssl
import urllib.parse
import urllib.request

# --- config -----------------------------------------------------------------
# Free, read-only EIA open-data key. Register your own at
# https://www.eia.gov/opendata/register.php
EIA_API_KEY = "QhQUtQRvaTkVhn5I8oFKtUUmhVo9R36aIHJgm9Rt"

EIA_BASE = "https://api.eia.gov/v2"
_TIMEOUT = 25

# EIA fuel-type code -> our in-game source key. NG (natural gas) covers both
# combined-cycle and simple-cycle peakers in EIA's data; we seed the CC plant
# from it and start the small peaker plant at zero (see config.py).
FUEL_TO_SOURCE = {
    "NUC": "nuclear",
    "COL": "coal",
    "NG": "gas",
    "WAT": "hydro",
    "WND": "wind",
    "SUN": "solar",
}

# EIA hourly `period` values are UTC. To line the day's shape up with the
# in-game local clock (so demand peaks in the local afternoon and solar peaks at
# local noon), shift each series by the region's standard UTC offset, +1 during
# US daylight saving. Cache is versioned so old UTC-aligned files are ignored.
_CACHE_VERSION = 2
_TZ_STD_OFFSET = {
    "ERCO": -6, "CAL": -8, "NYIS": -5, "PJM": -5,
    "MISO": -6, "ISNE": -5, "SPP": -6,
}


def _is_us_dst(d):
    """US daylight saving: 2nd Sunday of March through 1st Sunday of November."""
    mar = _dt.date(d.year, 3, 1)
    dst_start = _dt.date(d.year, 3, 1 + (6 - mar.weekday()) % 7 + 7)  # 2nd Sun
    nov = _dt.date(d.year, 11, 1)
    dst_end = _dt.date(d.year, 11, 1 + (6 - nov.weekday()) % 7)       # 1st Sun
    return dst_start <= d < dst_end


def _to_local(arr, respondent, date):
    """Rotate a 24-slot UTC-hour array so it's indexed by local clock hour."""
    if arr is None:
        return None
    shift = _TZ_STD_OFFSET.get(respondent, 0) + (1 if _is_us_dst(date) else 0)
    return [arr[(i - shift) % 24] for i in range(24)]

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eia_cache")


def _ssl_context():
    """Prefer certifi's CA bundle (the stock framework Python on macOS often
    can't verify certs on its own); fall back to an unverified context so a
    missing certifi still lets the public, read-only data through rather than
    hard-failing the whole feature."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


def _get_json(path, params):
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{EIA_BASE}/{path}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "GridManager/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_context()) as resp:
        return json.load(resp)


def _hour_grid(rows, date_str, value_key="value"):
    """Collapse EIA rows (period like 'YYYY-MM-DDTHH') for one date onto a
    24-slot list indexed by hour, then fill any gaps by carry-forward/back so
    the caller always gets a clean 24-length array. Returns None if there's no
    usable data for the date at all."""
    slots = [None] * 24
    for r in rows:
        period = r.get("period", "")
        if not period.startswith(date_str) or "T" not in period:
            continue
        try:
            hour = int(period.split("T", 1)[1][:2])
            val = float(r.get(value_key))
        except (ValueError, TypeError):
            continue
        if 0 <= hour < 24:
            slots[hour] = val if slots[hour] is None else slots[hour] + 0  # keep first
    if all(v is None for v in slots):
        return None
    # forward fill then back fill
    last = None
    for i in range(24):
        if slots[i] is None:
            slots[i] = last
        else:
            last = slots[i]
    nxt = None
    for i in range(23, -1, -1):
        if slots[i] is None:
            slots[i] = nxt
        else:
            nxt = slots[i]
    return [float(v) if v is not None else 0.0 for v in slots]


def _cache_path(respondent, date_str):
    return os.path.join(_CACHE_DIR, f"{respondent}_{date_str}.json")


def _load_cache(respondent, date_str):
    try:
        with open(_cache_path(respondent, date_str)) as f:
            data = json.load(f)
        if data.get("v") != _CACHE_VERSION:  # stale schema (e.g. pre-tz-shift)
            return None
        return data
    except (OSError, ValueError):
        return None


def _save_cache(payload):
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(payload["respondent"], payload["date"]), "w") as f:
            json.dump(payload, f)
    except OSError:
        pass


def fetch_region_day(respondent, date):
    """Fetch (or load from cache) one day of hourly demand + generation-by-fuel
    for an EIA respondent (e.g. 'ERCO').

    `date` is a datetime.date. Returns a dict:
        {
          "respondent": str, "date": "YYYY-MM-DD",
          "demand_hourly": [24 floats, MW],
          "fuel_hourly": {source_key: [24 floats, MW]},   # only fuels present
          "source": "api" | "cache",
        }
    or None on any failure.
    """
    if isinstance(date, _dt.datetime):
        date = date.date()
    date_str = date.isoformat()

    cached = _load_cache(respondent, date_str)
    if cached:
        cached["source"] = "cache"
        return cached

    start = f"{date_str}T00"
    end = f"{(date + _dt.timedelta(days=1)).isoformat()}T00"

    try:
        demand_raw = _get_json(
            "electricity/rto/region-data/data/",
            {
                "api_key": EIA_API_KEY,
                "frequency": "hourly",
                "data[0]": "value",
                "facets[respondent][]": respondent,
                "facets[type][]": "D",
                "start": start,
                "end": end,
                "sort[0][column]": "period",
                "sort[0][direction]": "asc",
                "length": 48,
            },
        )
        fuel_raw = _get_json(
            "electricity/rto/fuel-type-data/data/",
            {
                "api_key": EIA_API_KEY,
                "frequency": "hourly",
                "data[0]": "value",
                "facets[respondent][]": respondent,
                "start": start,
                "end": end,
                "sort[0][column]": "period",
                "sort[0][direction]": "asc",
                "length": 400,
            },
        )
    except Exception:
        return None

    demand_rows = demand_raw.get("response", {}).get("data", [])
    fuel_rows = fuel_raw.get("response", {}).get("data", [])

    demand_hourly = _hour_grid(demand_rows, date_str)
    if not demand_hourly:
        return None
    demand_hourly = _to_local(demand_hourly, respondent, date)

    fuel_hourly = {}
    by_fuel = {}
    for r in fuel_rows:
        by_fuel.setdefault(r.get("fueltype"), []).append(r)
    for fuel_code, src_key in FUEL_TO_SOURCE.items():
        grid = _hour_grid(by_fuel.get(fuel_code, []), date_str)
        if grid is not None:
            fuel_hourly[src_key] = _to_local(grid, respondent, date)

    payload = {
        "respondent": respondent,
        "date": date_str,
        "demand_hourly": demand_hourly,
        "fuel_hourly": fuel_hourly,
        "source": "api",
        "v": _CACHE_VERSION,
    }
    _save_cache(payload)
    return payload


if __name__ == "__main__":
    import sys
    resp = sys.argv[1] if len(sys.argv) > 1 else "ERCO"
    d = _dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else _dt.date(2021, 2, 15)
    data = fetch_region_day(resp, d)
    if not data:
        print("FETCH FAILED")
        raise SystemExit(1)
    print(f"{resp} {data['date']} via {data['source']}")
    dh = data["demand_hourly"]
    print(f"demand: min {min(dh):.0f}  peak {max(dh):.0f} MW  (n={len(dh)})")
    for k, arr in data["fuel_hourly"].items():
        print(f"  {k:8s} peak {max(arr):8.0f}  start(h0) {arr[0]:8.0f} MW")
