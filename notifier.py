import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def _slack_send(channel: str, text: str):
    client = WebClient(token=os.environ["SLACK_TOKEN"])
    try:
        client.chat_postMessage(channel=channel, text=text, mrkdwn=True)
    except SlackApiError as e:
        print(f"[Slack error] {e.response['error']}")


def _email_send(subject: str, body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", 587))) as server:
        server.starttls()
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        server.sendmail(os.environ["EMAIL_FROM"], os.environ["EMAIL_TO"], msg.as_string())


def send_no_bant(deal: dict, notification_config: dict):
    deal_name = deal.get("properties", {}).get("dealname", "Sin nombre")
    message = (
        f":warning: *Demo mañana — {deal_name}*\n\n"
        "No hay suficiente info para darte un mail personalizado.\n"
        "Las notas del deal no contienen un BANT. Añade Budget, Authority, Need y Timeline antes de la demo."
    )
    _dispatch(message, f"[Sin BANT] Demo mañana: {deal_name}", notification_config)


def send_recap(deal: dict, recap: str, notification_config: dict):
    deal_name = deal.get("properties", {}).get("dealname", "Sin nombre")
    message = f":rocket: *Recap demo mañana — {deal_name}*\n\n{recap}"
    _dispatch(message, f"Recap demo mañana: {deal_name}", notification_config)


def _dispatch(slack_text: str, email_subject: str, config: dict):
    notif_type = config.get("type", "slack")

    if notif_type in ("slack", "both"):
        channel = os.environ.get("SLACK_CHANNEL", config.get("slack", {}).get("channel", "#general"))
        _slack_send(channel, slack_text)

    if notif_type in ("email", "both"):
        _email_send(email_subject, slack_text)
