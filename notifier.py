import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

FALLBACK_SLACK_USER = os.environ.get("SLACK_USER_ID", "")


def _get_client() -> WebClient:
    return WebClient(token=os.environ["SLACK_TOKEN"])


def _resolve_user_id(client: WebClient, owner_email: str | None) -> str:
    """Returns Slack user ID for owner_email, falling back to FALLBACK_SLACK_USER."""
    if owner_email:
        try:
            result = client.users_lookupByEmail(email=owner_email)
            uid = result["user"]["id"]
            print(f"[✓] Slack user resolved: {owner_email} → {uid}")
            return uid
        except SlackApiError as e:
            print(f"[!] Could not resolve Slack user for {owner_email}: {e.response['error']}")
    if FALLBACK_SLACK_USER:
        return FALLBACK_SLACK_USER
    raise RuntimeError("No Slack recipient: owner email lookup failed and SLACK_USER_ID is not set.")


def _slack(client: WebClient, channel: str, text: str):
    try:
        client.chat_postMessage(channel=channel, text=text, mrkdwn=True)
    except SlackApiError as e:
        print(f"[Slack error] {e.response['error']}")


def send_no_bant(deal: dict, context: dict):
    owner_email = context.get("owner", {}).get("email")
    client      = _get_client()
    channel     = _resolve_user_id(client, owner_email)
    name        = deal.get("properties", {}).get("dealname", "Sin nombre")
    meeting     = deal.get("properties", {}).get("first_meeting_at", "?")
    _slack(client, channel,
        f":warning: *Demo mañana sin BANT — {name}*\n"
        f"Fecha: {meeting}\n\n"
        "No hay suficiente información para generar un mail personalizado.\n"
        "Las notas del deal no contienen un BANT completo. Añade Budget, Authority, Need y Timeline."
    )


def send_email_and_recap(deal: dict, email: str, recap: str, owner_email: str | None = None):
    client  = _get_client()
    channel = _resolve_user_id(client, owner_email)
    name    = deal.get("properties", {}).get("dealname", "Sin nombre")
    meeting = deal.get("properties", {}).get("first_meeting_at", "?")
    _slack(client, channel,
        f":rocket: *Demo mañana — {name}* | {meeting}\n"
        f"{'─' * 50}\n\n"
        f"*✉️ MAIL A ENVIAR:*\n\n"
        f"{email}\n\n"
        f"{'─' * 50}\n\n"
        f"*🧠 POR QUÉ ESTOS ARGUMENTOS:*\n\n"
        f"{recap}"
    )
