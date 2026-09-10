"""NOAA NCEI client: real historical weather for the dated scenarios.

Pulls one day of daily GHCND observations (max/min temperature, precipitation,
snowfall) from a representative weather station inside each grid region, so a
scenario like Winter Storm Uri plays out under the temperatures and weather that
actually hit the ground that day:

  * TMAX/TMIN -> a 24-hour ambient temperature curve (hourly_temps_f)
  * SNOW/PRCP/temps -> the weather event kinds the day should favor
    (derive_event_kinds)

Uses NCEI's data-access service, which serves the GHCND daily-summaries
dataset with no API token required (unlike the older CDO v2 API). Same
contract as eia.py: everything is best-effort — any network/parse failure or
station gap returns None and the game falls back to its synthetic seasonal
weather. Successful pulls are cached to disk so replays work offline.

Docs: https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation
"""
import datetime as _dt
import json
import math
import os
import urllib.parse
import urllib.request

from eia import _ssl_context

NOAA_BASE = "https://www.ncei.noaa.gov/access/services/data/v1"
_TIMEOUT = 25
_CACHE_VERSION = 1
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "noaa_cache")

# One representative GHCND station per grid region (big-city airports: long,
# reliable daily records covering every scenario date).
_STATIONS = {
    "ERCO": "USW00003927",   # Dallas/Fort Worth Intl, TX
    "CAL": "USW00023232",    # Sacramento Executive, CA
    "NYIS": "USW00094728",   # NYC Central Park, NY
    "PJM": "USW00013739",    # Philadelphia Intl, PA
    "MISO": "USW00093819",   # Indianapolis Intl, IN
    "ISNE": "USW00014739",   # Boston Logan Intl, MA
    "SWPP": "USW00013967",   # Oklahoma City Will Rogers, OK
}


def _cache_path(region_code, date_str):
    return os.path.join(_CACHE_DIR, f"{region_code}_{date_str}.json")


def _load_cache(region_code, date_str):
    try:
        with open(_cache_path(region_code, date_str)) as f:
            data = json.load(f)
        if data.get("v") != _CACHE_VERSION:
            return None
        return data
    except (OSError, ValueError):
        return None


def _save_cache(payload):
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(payload["region"], payload["date"]), "w") as f:
            json.dump(payload, f)
    except OSError:
        pass


def fetch_weather_day(region_code, date):
    """Fetch (or load from cache) one day of daily weather for a region.

    Returns {"region", "date", "tmax_f", "tmin_f", "prcp_in", "snow_in",
    "source": "noaa" | "cache"} or None on any failure (unknown region,
    network error, station gap).
    """
    station = _STATIONS.get(region_code)
    if station is None:
        return None
    if isinstance(date, _dt.datetime):
        date = date.date()
    date_str = date.isoformat()

    cached = _load_cache(region_code, date_str)
    if cached:
        cached["source"] = "cache"
        return cached

    params = {
        "dataset": "daily-summaries",
        "stations": station,
        "startDate": date_str,
        "endDate": date_str,
        "dataTypes": "TMAX,TMIN,PRCP,SNOW",
        "units": "standard",   # °F and inches
        "format": "json",
    }
    url = f"{NOAA_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "GridManager/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_context()) as resp:
            rows = json.load(resp)
    except Exception:
        return None
    if not rows:
        return None

    row = rows[0]

    def _num(key):
        try:
            return float(row.get(key))
        except (TypeError, ValueError):
            return None

    tmax, tmin = _num("TMAX"), _num("TMIN")
    if tmax is None or tmin is None:
        return None

    payload = {
        "region": region_code,
        "date": date_str,
        "tmax_f": tmax,
        "tmin_f": tmin,
        "prcp_in": _num("PRCP") or 0.0,
        "snow_in": _num("SNOW") or 0.0,
        "source": "noaa",
        "v": _CACHE_VERSION,
    }
    _save_cache(payload)
    return payload


def hourly_temps_f(tmax_f, tmin_f):
    """Expand a daily max/min into a 24-value hourly curve with the standard
    diurnal sinusoid (coldest ~03:00, warmest ~15:00) — the same phase as the
    synthetic model in game_state, so the HUD thermometer behaves identically
    whichever source feeds it."""
    mean = (tmax_f + tmin_f) / 2.0
    amp = (tmax_f - tmin_f) / 2.0
    return [mean + amp * math.sin(2 * math.pi * (h - 9.0) / 24.0) for h in range(24)]


def derive_event_kinds(tmax_f, tmin_f, prcp_in, snow_in):
    """Weather event kinds (game_state GridEvent tags) the real day supports,
    most severe first. Empty list -> nothing notable; the seasonal roller
    carries the day.

    A hard freeze counts even without fresh snowfall on the books — Uri's
    worst day at DFW logged SNOW 0.0 (it fell the day before) but a 14°F high
    absolutely iced turbines and spiked heating load."""
    kinds = []
    deep_freeze = tmax_f <= 25
    if deep_freeze or (snow_in > 0 and tmax_f <= 32):
        kinds += ["ICE_STORM", "SNOW"]
    elif snow_in > 0 or tmax_f <= 32:
        kinds.append("SNOW")
    if tmax_f >= 100 or tmin_f >= 78:
        kinds.append("HEAT_WAVE")
    if prcp_in > 0.3 and snow_in <= 0 and not deep_freeze:
        kinds.append("RAIN")
    return kinds


if __name__ == "__main__":
    import sys
    region = sys.argv[1] if len(sys.argv) > 1 else "ERCO"
    d = _dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else _dt.date(2021, 2, 15)
    data = fetch_weather_day(region, d)
    if not data:
        print("FETCH FAILED (unknown region, network error, or station gap)")
        raise SystemExit(1)
    print(f"{region} {data['date']} via {data['source']}")
    print(f"tmax {data['tmax_f']:.0f}F  tmin {data['tmin_f']:.0f}F  "
          f"prcp {data['prcp_in']:.2f}in  snow {data['snow_in']:.1f}in")
    print("event kinds:", derive_event_kinds(data["tmax_f"], data["tmin_f"],
                                             data["prcp_in"], data["snow_in"]))
    temps = hourly_temps_f(data["tmax_f"], data["tmin_f"])
    print("hourly temps:", " ".join(f"{t:.0f}" for t in temps))
