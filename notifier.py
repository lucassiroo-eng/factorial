import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# DM del usuario por defecto (Lucas)
DEFAULT_SLACK_USER = os.environ.get("SLACK_USER_ID", "U0AF9M5AXPE")


def _slack(text: str, channel: str = None):
    client = WebClient(token=os.environ["SLACK_TOKEN"])
    target = channel or DEFAULT_SLACK_USER
    try:
        result = client.chat_postMessage(channel=target, text=text, mrkdwn=True)
        return result["ts"]
    except SlackApiError as e:
        print(f"[Slack error] {e.response['error']}")
        return None


def send_no_bant(deal: dict, context: dict):
    name = deal.get("properties", {}).get("dealname", "Sin nombre")
    meeting = deal.get("properties", {}).get("first_meeting_at", "?")
    _slack(
        f":warning: *Demo mañana sin BANT — {name}*\n"
        f"Fecha: {meeting}\n\n"
        "No hay suficiente información para generar un mail personalizado.\n"
        "Las notas del deal no contienen un BANT completo. Añade Budget, Authority, Need y Timeline."
    )


def send_email_and_recap(deal: dict, email: str, recap: str):
    name    = deal.get("properties", {}).get("dealname", "Sin nombre")
    meeting = deal.get("properties", {}).get("first_meeting_at", "?")
    contact = ""

    # Cabecera
    msg = (
        f":rocket: *Demo mañana — {name}* | {meeting}\n"
        f"{'─' * 50}\n\n"
        f"*✉️ MAIL A ENVIAR:*\n\n"
        f"{email}\n\n"
        f"{'─' * 50}\n\n"
        f"*🧠 POR QUÉ ESTOS ARGUMENTOS:*\n\n"
        f"{recap}"
    )
    _slack(msg)
