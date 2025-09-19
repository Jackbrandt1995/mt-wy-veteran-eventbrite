#!/usr/bin/env python3
"""
Scrape Eventbrite for veteran events in Montana and Wyoming over the next 60 days.
This script uses the Eventbrite API and writes a JSON file with a list of events or an error message.
"""

import json
import os
import sys
import time
from typing import Dict, List, Tuple

import requests
from datetime import datetime, timedelta

API_BASE = "https://www.eventbriteapi.com/v3"
OUT_FILE = "events.json"

# Default configuration
DEFAULT_STATES = ["Montana", "Wyoming"]
DEFAULT_QUERY = os.environ.get(
    "EVENTBRITE_QUERY",
    "veteran OR veterans OR military OR service member",
)
DEFAULT_WITHIN = os.environ.get("EVENTBRITE_WITHIN", "500mi")
LOOKAHEAD_DAYS = int(os.environ.get("EVENTBRITE_DAYS", "60"))
PAGE_DELAY_SEC = float(os.environ.get("EVENTBRITE_PAGE_DELAY_SEC", "0.5"))


def save_json(payload: Dict, path: str = OUT_FILE) -> None:
    """Save a payload as JSON to the given path."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def get_token() -> str:
    """Retrieve Eventbrite API token from environment and exit if missing."""
    token = os.environ.get("EVENTBRITE_TOKEN")
    if not token:
        save_json({"generated": False, "error": "EVENTBRITE_TOKEN is not set"})
        sys.exit(2)
    return token


def search_region(
    session: requests.Session,
    headers: Dict[str, str],
    query: str,
    location_address: str,
    within: str,
) -> Tuple[List[Dict], List[str]]:
    """Search a single region and return events and warnings."""
    params = {
        "q": query,
        "location.address": location_address,
        "location.within": within,
        "expand": "venue",
        "sort_by": "date",
        "page": 1,
    }
    results: List[Dict] = []
    warnings: List[str] = []
    while True:
        url = f"{API_BASE}/events/search"
        try:
            resp = session.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as exc:
            warnings.append(f"request_error:{location_address}:{exc}")
            break
        if resp.status_code == 404:
            warnings.append(f"404:{location_address}:{resp.text[:256]}")
            break
        if resp.status_code != 200:
            warnings.append(f"http_{resp.status_code}:{location_address}:{resp.text[:256]}")
            break
        data = resp.json()
        results.extend(data.get("events", []) or [])
        if not data.get("pagination", {}).get("has_more_items"):
            break
        params["page"] += 1
        time.sleep(PAGE_DELAY_SEC)
    return results, warnings


def normalize_events(events: List[Dict]) -> List[Dict]:
    """Normalize raw Eventbrite events into a simplified structure."""
    normalized: List[Dict] = []
    for e in events:
        venue = e.get("venue") or {}
        address = venue.get("address") or {}
        normalized.append({
            "id": e.get("id"),
            "name": (e.get("name") or {}).get("text"),
            "url": e.get("url"),
            "start": (e.get("start") or {}).get("local"),
            "end": (e.get("end") or {}).get("local"),
            "is_free": e.get("is_free"),
            "status": e.get("status"),
            "city": address.get("city"),
            "state": address.get("region"),
            "venue_name": venue.get("name"),
            "address": address.get("localized_address_display"),
        })
    return normalized


def filter_upcoming(events: List[Dict], days: int = LOOKAHEAD_DAYS) -> List[Dict]:
    """Filter events to those starting within the next `days` days."""
    now = datetime.utcnow()
    cutoff = now + timedelta(days=days)
    filtered: List[Dict] = []
    for e in events:
        start = e.get("start")
        if not start:
            continue
        try:
            dt = datetime.fromisoformat(start)
        except ValueError:
            continue
        if now <= dt <= cutoff:
            filtered.append(e)
    return filtered


def fetch_events(token: str, query: str = DEFAULT_QUERY, states: List[str] = None, within: str = DEFAULT_WITHIN) -> Dict:
    """Fetch and process events across multiple states."""
    if states is None:
        states = DEFAULT_STATES
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": os.environ.get("VNN_USER_AGENT", "mt-wy-veteran-scraper/1.0"),
    }
    session = requests.Session()
    all_raw: List[Dict] = []
    all_warnings: List[str] = []
    for state in states:
        events, warns = search_region(session, headers, query, state, within)
        all_raw.extend(events)
        all_warnings.extend(warns)
    normalized = normalize_events(all_raw)
    upcoming = filter_upcoming(normalized, LOOKAHEAD_DAYS)
    # Deduplicate by (name, start)
    seen = set()
    unique: List[Dict] = []
    for e in upcoming:
        key = (e.get("name"), e.get("start"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    return {
        "generated": True,
        "source": "eventbrite",
        "query": query,
        "regions": states,
        "within": within,
        "count": len(unique),
        "events": unique,
        "warnings": all_warnings,
    }


def main() -> int:
    token = get_token()
    try:
        payload = fetch_events(token)
        save_json(payload)
        return 0
    except Exception as exc:
        save_json({"generated": False, "error": str(exc)})
        return 1

def main() -> int:
    token = get_token()
    try:
        print("Token acquired, starting fetch_events...")  # Debug
        payload = fetch_events(token)
        print(f"Fetched {payload['count']} events.")  # Debug
        save_json(payload)
        return 0
    except Exception as exc:
        save_json({"generated": False, "error": str(exc)})
        print(f"Error: {exc}")  # Debug
        return 1

if __name__ == "__main__":
    sys.exit(main())
