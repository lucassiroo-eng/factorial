"""
Uso:
  python main.py --owner 86688154
  python main.py --market France
  python main.py --market France --all                   # todos los deals futuros
  python main.py --market France --all --next-business-day  # demos del próximo día laborable
  python main.py --deal-id 12345678
"""
from __future__ import annotations
import argparse
import json
import os
import time
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

from hubspot_client import HubSpotClient
import analyzer
import notifier


def _resolve_owner_id(hs: HubSpotClient, filter_type: str, filter_value: str) -> str:
    if filter_type == "owner" and not filter_value.strip().isdigit():
        print(f"[→] Resolving owner name '{filter_value}'...")
        owner = hs.find_owner_by_name(filter_value)
        if not owner:
            raise SystemExit(f"[!] Owner '{filter_value}' not found in HubSpot.")
        filter_value = str(owner["id"])
        full_name = f"{owner.get('firstName','')} {owner.get('lastName','')}".strip()
        print(f"[✓] Resolved: {full_name} → ID {filter_value}")
    return filter_value


def run(filter_type: str, filter_value: str, send_to_me: bool = False, recipient_email: str | None = None):
    hs = HubSpotClient()
    filter_value = _resolve_owner_id(hs, filter_type, filter_value)

    print(f"[→] Buscando próximo deal ({filter_type}={filter_value})...")
    deal = hs.get_next_future_deal(filter_type, filter_value)
    if not deal:
        print("[!] No hay deals con first_meeting_at futura para este filtro.")
        return
    _process_deal(hs, deal, send_to_me=send_to_me, recipient_email=recipient_email)


def _next_business_day() -> date:
    today = date.today()
    return today + timedelta(days=3 if today.weekday() == 4 else 1)  # viernes → lunes


def run_all(filter_type: str, filter_value: str, send_to_me: bool = False, target_date: date | None = None):
    hs = HubSpotClient()
    filter_value = _resolve_owner_id(hs, filter_type, filter_value)

    label = target_date.isoformat() if target_date else "futuro"
    print(f"[→] Buscando deals para {label} ({filter_type}={filter_value})...")
    all_deals = hs.get_all_future_deals(filter_type, filter_value, target_date=target_date)
    if not all_deals:
        print(f"[!] No hay deals para {label}.")
        return
    print(f"[✓] {len(all_deals)} deal(s) encontrado(s). Procesando...")
    for deal in all_deals:
        _process_deal(hs, deal, send_to_me=send_to_me)


def run_by_id(deal_id: str, send_to_me: bool = False, recipient_email: str | None = None):
    hs = HubSpotClient()
    print(f"[→] Fetching deal {deal_id}...")
    deal = hs.get_deal_by_id(deal_id)
    if not deal:
        print(f"[!] Deal {deal_id} not found.")
        return
    _process_deal(hs, deal, send_to_me=send_to_me, recipient_email=recipient_email)


def _log_api_usage(hs: HubSpotClient):
    from hubspot_client import _DAILY_CALL_LIMIT
    print(f"[→] HubSpot API calls this run: {hs._call_count}/{_DAILY_CALL_LIMIT}")


def _process_deal(hs: HubSpotClient, deal: dict, send_to_me: bool = False, recipient_email: str | None = None):
    props   = deal.get("properties", {})
    name    = props.get("dealname", deal["id"])
    meeting = props.get("first_meeting_at", "?")
    print(f"[✓] Deal: {name} | Demo: {meeting}")

    print("[→] Fetching full context (contacts, company, notes)...")
    context = hs.get_full_context(deal)
    print(f"    {len(context['notes'])} note(s) found.")

    print("[→] Generating email & recap...")
    email, recap = analyzer.analyze_and_generate(context)

    if not email:
        print("[!] Insufficient info for personalized email.")
        notifier.send_no_bant(deal, context)
        return

    print("[→] Sending to Slack...")
    if recipient_email:
        effective_email = recipient_email
    elif send_to_me:
        effective_email = None  # falls back to SLACK_USER_ID
    else:
        effective_email = context.get("owner", {}).get("email")
    notifier.send_email_and_recap(deal, email, recap, owner_email=effective_email)
    print("[✓] Done.")
    _log_api_usage(hs)


KNOWN_MARKETS = ["France", "Spain", "Portugal", "Germany", "Italy", "Belgium"]


OWNERS_FILE = os.path.join(os.path.dirname(__file__), "docs", "owners.json")


def discover_owners():
    hs = HubSpotClient()

    # Load existing owners so we only add, never remove
    existing: dict[str, dict] = {}
    if os.path.exists(OWNERS_FILE):
        with open(OWNERS_FILE) as f:
            for o in json.load(f).get("owners", []):
                existing[o["email"] or o["id"]] = o
        print(f"[→] {len(existing)} owner(s) already in owners.json")

    print(f"\nScanning last 50 deals per market in 'partners distribution' pipeline...\n")
    owners_map = hs._load_owners_map()
    print(f"[✓] {len(owners_map)} owners loaded from HubSpot\n")

    merged = {k: dict(v) for k, v in existing.items()}
    for market in KNOWN_MARKETS:
        time.sleep(1)
        owners = hs.get_owners_by_market(market, owners_map, limit=50)
        new_in_market = 0
        for o in owners:
            key = o["email"] or o["id"]
            if key not in merged:
                merged[key] = {**o, "markets": []}
                new_in_market += 1
            if market not in merged[key]["markets"]:
                merged[key]["markets"].append(market)
        label = f"+{new_in_market} new" if new_in_market else "no new"
        print(f"  {market}: {len(owners)} owner(s) found ({label})")

    sorted_owners = sorted(merged.values(), key=lambda x: x["name"])
    with open(OWNERS_FILE, "w") as f:
        json.dump({"owners": sorted_owners}, f, indent=2, ensure_ascii=False)

    js_file = OWNERS_FILE.replace(".json", ".js")
    with open(js_file, "w") as f:
        f.write("// Auto-generated by: python main.py --discover-owners\n")
        f.write("window.FACTORIAL_OWNERS = ")
        json.dump(sorted_owners, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    print(f"\n{'─'*60}")
    print(f"{'NAME':<25} {'EMAIL':<35} MARKETS")
    print(f"{'─'*60}")
    for o in sorted_owners:
        print(f"{o['name']:<25} {o['email']:<35} {', '.join(o['markets'])}")
    print(f"{'─'*60}")
    print(f"Total: {len(merged)} unique owner(s) → saved to owners.json")
    _log_api_usage(hs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demo prep — HubSpot + Groq + Slack")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--owner",          help="HubSpot owner ID or name")
    group.add_argument("--market",         help="Market value (e.g. France)")
    group.add_argument("--deal-id",        help="Process a specific deal by HubSpot ID")
    group.add_argument("--discover-owners", action="store_true", help="List all owners per market (last 50 deals)")
    parser.add_argument("--all",               action="store_true", help="Process all future deals (not just the next one)")
    parser.add_argument("--next-business-day", action="store_true", help="Filter for the next business day (Fri→Mon)")
    parser.add_argument("--send-to-me",        action="store_true", help="Force sending to SLACK_USER_ID (auto flows)")
    parser.add_argument("--recipient-email",   default=None,        help="Override Slack recipient by email (manual/web flows)")
    args = parser.parse_args()

    target = _next_business_day() if args.next_business_day else None
    rec    = args.recipient_email or None

    if args.discover_owners:
        discover_owners()
    elif args.deal_id:
        run_by_id(args.deal_id, send_to_me=args.send_to_me, recipient_email=rec)
    elif args.all:
        run_all("owner" if args.owner else "market", args.owner or args.market, send_to_me=args.send_to_me, target_date=target)
    elif args.owner:
        run("owner", args.owner, send_to_me=args.send_to_me, recipient_email=rec)
    else:
        run("market", args.market, send_to_me=args.send_to_me, recipient_email=rec)
