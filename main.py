import os
import schedule
import time
import yaml
from dotenv import load_dotenv

from hubspot_client import HubSpotClient
import analyzer
import notifier

load_dotenv()


def load_config() -> dict:
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)


def run_check():
    print("[Check] Buscando deals con demo mañana...")
    config = load_config()
    hs = HubSpotClient()

    meeting_prop = config["hubspot"]["meeting_date_property"]
    extra_filters = config["hubspot"].get("deal_filters") or []
    notification_config = config["notification"]

    deals = hs.get_deals_with_meeting_tomorrow(meeting_prop, extra_filters)
    print(f"[Check] {len(deals)} deal(s) encontrados.")

    for deal in deals:
        deal_name = deal.get("properties", {}).get("dealname", deal["id"])
        print(f"  → Procesando: {deal_name}")

        notes = hs.get_deal_notes(deal["id"])
        bant = analyzer.analyze_bant(notes)

        if not bant["has_bant"]:
            print(f"    [!] Sin BANT — enviando aviso.")
            notifier.send_no_bant(deal, notification_config)
        else:
            print(f"    [✓] BANT detectado — generando recap.")
            recap = analyzer.generate_recap(deal, notes, bant)
            notifier.send_recap(deal, recap, notification_config)

    print("[Check] Listo.\n")


if __name__ == "__main__":
    run_at = load_config().get("scheduler", {}).get("run_at", "09:00")
    print(f"[Scheduler] Ejecutando check diario a las {run_at}.")
    print("[Scheduler] Ejecutando check inicial ahora...")
    run_check()

    schedule.every().day.at(run_at).do(run_check)
    while True:
        schedule.run_pending()
        time.sleep(30)
