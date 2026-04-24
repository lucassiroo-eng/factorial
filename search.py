"""
Search HubSpot for all future deals and write results to docs/results.json
via GitHub Contents API.

Usage:
  python search.py --filter-type owner --filter-value "Fanny Haurot"
  python search.py --filter-type market --filter-value France
"""
import argparse
import base64
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

from hubspot_client import HubSpotClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter-type",  required=True)
    parser.add_argument("--filter-value", required=True)
    args = parser.parse_args()

    hs           = HubSpotClient()
    filter_type  = args.filter_type
    filter_value = args.filter_value

    # Resolve owner name → ID (also loads all owners into a dict we reuse below)
    all_owners: dict = {}
    if filter_type == "owner" and not filter_value.strip().isdigit():
        print(f"[→] Resolving owner '{filter_value}'...")
        all_owners = hs.get_all_owners()
        matched_id = next(
            (oid for oid, name in all_owners.items() if filter_value.lower() in name.lower()),
            None,
        )
        if not matched_id:
            _save({"deals": [], "error": f"Owner '{filter_value}' not found in HubSpot.", "ts": int(time.time())})
            print("[!] Owner not found.")
            return
        filter_value = matched_id
        print(f"[✓] {all_owners[matched_id]} → ID {filter_value}")

    # Fetch all owners in one call (skip if already loaded above)
    if not all_owners:
        print("[→] Fetching owners...")
        all_owners = hs.get_all_owners()
        print(f"[✓] {len(all_owners)} owner(s) loaded.")

    print(f"[→] Searching deals ({filter_type}={filter_value})...")
    raw_deals = hs.get_all_future_deals(filter_type, filter_value)
    print(f"[✓] {len(raw_deals)} deal(s) found.")

    results = []
    for d in raw_deals:
        props    = d.get("properties", {})
        owner_id = props.get("hubspot_owner_id", "") or ""
        results.append({
            "id":       d["id"],
            "name":     props.get("dealname", ""),
            "date":     props.get("first_meeting_at", ""),
            "owner":    all_owners.get(owner_id, ""),
            "market":   props.get("country_qobra_samba", ""),
            "amount":   props.get("amount", ""),
            "industry": props.get("industry", ""),
        })

    _save({
        "deals":  results,
        "filter": {"type": filter_type, "value": args.filter_value},
        "ts":     int(time.time()),
    })
    print(f"[✓] Saved {len(results)} deals to docs/results.json.")


def _save(payload: dict):
    token = os.environ.get("GITHUB_TOKEN", "")
    repo  = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("[!] GITHUB_TOKEN / GITHUB_REPOSITORY not set.")
        print(json.dumps(payload, indent=2))
        return

    content = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    url     = f"https://api.github.com/repos/{repo}/contents/docs/results.json"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    r   = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.ok else None

    body: dict = {"message": "chore: update search results", "content": content, "branch": "main"}
    if sha:
        body["sha"] = sha

    r2 = requests.put(url, headers=headers, json=body)
    if not r2.ok:
        print(f"[!] Failed to save: {r2.status_code} {r2.text}")
    else:
        print("[✓] docs/results.json updated.")


if __name__ == "__main__":
    main()
