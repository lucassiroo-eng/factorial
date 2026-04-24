"""
Uso:
  python main.py --owner 86688154
  python main.py --market France

Busca el deal con first_meeting_at más próximo a hoy para el owner o mercado dado,
analiza el BANT, genera el mail y lo manda por Slack junto con el recap.
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

    print(f"[→] Buscando deals futuros ({filter_type}={filter_value})...")
    deal = hs.get_next_future_deal(filter_type, filter_value)

    if not deal:
        print("[!] No hay deals con first_meeting_at futura para este filtro.")
        return

    props   = deal.get("properties", {})
    name    = props.get("dealname", deal["id"])
    meeting = props.get("first_meeting_at", "?")
    print(f"[✓] Deal encontrado: {name} | Demo: {meeting}")

    print("[→] Obteniendo contexto completo (contactos, empresa, notas)...")
    context = hs.get_full_context(deal)
    notes   = context["notes"]
    print(f"    {len(notes)} nota(s) encontradas.")

    print("[→] Analizando BANT...")
    bant = analyzer.analyze_bant(notes)

    if not bant["has_bant"]:
        missing = ", ".join(bant["missing"]) or "todos los campos"
        print(f"[!] Sin BANT suficiente. Faltan: {missing}")
        notifier.send_no_bant(deal, context)
        return

    print("[→] Generando mail...")
    email = analyzer.generate_email(context, bant)

    print("[→] Generando recap de argumentos...")
    recap = analyzer.generate_recap(context, bant, email)

    print("[→] Enviando a Slack...")
    notifier.send_email_and_recap(deal, email, recap)
    print("[✓] Listo.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demo prep — HubSpot + Claude + Slack")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--owner",  help="Owner ID numérico de HubSpot (ej: 86688154)")
    group.add_argument("--market", help="Valor del campo Market SAMBA (ej: France)")
    args = parser.parse_args()

    if args.owner:
        run("owner", args.owner)
    else:
        run("market", args.market)
