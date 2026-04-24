"""
Uso:
  python main.py --owner 86688154
  python main.py --market France
  python main.py --deal-id 12345678
"""
import argparse
import os
from dotenv import load_dotenv

load_dotenv()

from hubspot_client import HubSpotClient
import analyzer
import notifier


def run(filter_type: str, filter_value: str):
    hs = HubSpotClient()

    # Resolve owner name → ID if a non-numeric value was passed
    if filter_type == "owner" and not filter_value.strip().isdigit():
        print(f"[→] Resolving owner name '{filter_value}'...")
        owner = hs.find_owner_by_name(filter_value)
        if not owner:
            print(f"[!] Owner '{filter_value}' not found in HubSpot.")
            return
        filter_value = str(owner["id"])
        full_name = f"{owner.get('firstName','')} {owner.get('lastName','')}".strip()
        print(f"[✓] Resolved: {full_name} → ID {filter_value}")

    print(f"[→] Buscando deals futuros ({filter_type}={filter_value})...")
    deal = hs.get_next_future_deal(filter_type, filter_value)

    if not deal:
        print("[!] No hay deals con first_meeting_at futura para este filtro.")
        return

    _process_deal(hs, deal)


def run_by_id(deal_id: str):
    hs = HubSpotClient()

    print(f"[→] Fetching deal {deal_id}...")
    deal = hs.get_deal_by_id(deal_id)

    if not deal:
        print(f"[!] Deal {deal_id} not found.")
        return

    _process_deal(hs, deal)


def _process_deal(hs: HubSpotClient, deal: dict):
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
    notifier.send_email_and_recap(deal, email, recap)
    print("[✓] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demo prep — HubSpot + Groq + Slack")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--owner",   help="HubSpot owner ID (e.g. 86688154)")
    group.add_argument("--market",  help="Market SAMBA value (e.g. France)")
    group.add_argument("--deal-id", help="Process a specific deal by HubSpot ID")
    args = parser.parse_args()

    if args.deal_id:
        run_by_id(args.deal_id)
    elif args.owner:
        run("owner", args.owner)
    else:
        run("market", args.market)
