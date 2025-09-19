#!/usr/bin/env python3
import os
import requests
import datetime
import json
import sys
import time

API_URL = "https://www.eventbriteapi.com/v3/events/search"
TOKEN = os.environ.get("EVENTBRITE_TOKEN")
QUERY = os.environ.get("EVENTBRITE_QUERY", "veteran OR veterans")
STATES = ["Montana", "Wyoming"]
WITHIN = os.environ.get("EVENTBRITE_WITHIN", "250mi")
DAYS = int(os.environ.get("EVENTBRITE_DAYS", "60"))
OUTPUT_FILE = "events.json"

def get_date_range(days):
    now = datetime.datetime.utcnow()
    end = now + datetime.timedelta(days=days)
    # Append 'Z' to indicate UTC time
    return now.isoformat() + "Z", end.isoformat() + "Z"

def fetch_events(state):
    start, end = get_date_range(DAYS)
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
    }
    params = {
        "q": QUERY,
        "location.address": state,
        "location.within": WITHIN,
        "start_date.range_start": start,
        "start_date.range_end": end,
        "expand": "venue",
        "page": 1,
    }
    events = []
    while True:
        try:
            resp = requests.get(API_URL, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"Error connecting to Eventbrite API: {e}", file=sys.stderr)
            break
        if resp.status_code == 404:
            print(f"Endpoint not found: {resp.text}", file=sys.stderr)
            break
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code} error: {resp.text}", file=sys.stderr)
            break
        data = resp.json()
        events.extend(data.get("events", []))
        pagination = data.get("pagination", {})
        if not pagination.get("has_more_items"):
            break
        params["page"] = pagination.get("page_number", 1) + 1
        # Respect API rate limits
        time.sleep(0.5)
    return events

def normalize_event(e):
    name = e.get("name", {}).get("text")
    url = e.get("url")
    start = e.get("start", {}).get("local")
    venue = e.get("venue") or {}
    address = venue.get("address") or {}
    location_parts = []
    for key in ("address_1", "city", "region", "postal_code"):
        value = address.get(key)
        if value:
            location_parts.append(value)
    location = ", ".join(location_parts) if location_parts else None
    return {
        "name": name,
        "url": url,
        "start": start,
        "location": location,
        "state": address.get("region"),
        "city": address.get("city"),
    }

def main():
    if not TOKEN:
        print("EVENTBRITE_TOKEN environment variable not set", file=sys.stderr)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        return
    all_events = []
    for state in STATES:
        events = fetch_events(state)
        for e in events:
            all_events.append(normalize_event(e))
    # Deduplicate events by name and start
    unique = []
    seen = set()
    for e in all_events:
        if not e["name"] or not e["start"]:
            continue
        key = (e["name"], e["start"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    unique.sort(key=lambda x: x["start"] or "")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(unique)} events to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
