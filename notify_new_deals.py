import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(line_buffering=True)

HUBSPOT_TOKEN = os.environ["HUBSPOT_TOKEN"]
SLACK_TOKEN = os.environ["SLACK_TOKEN"]
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_DEALS", "C0B9TQMPN77")
PORTAL_ID = os.environ.get("HUBSPOT_PORTAL_ID", "4960096")
CREATED_BY = os.environ.get("DEAL_CREATED_BY", "86980590")
SINCE_DATE = os.environ.get("DEAL_SINCE_DATE", "2026-06-09")


def hubspot_search(after_date, before_date):
    url = "https://api.hubapi.com/crm/v3/objects/deals/search"
    all_results = []
    after_cursor = None

    while True:
        payload = {
            "filterGroups": [{
                "filters": [
                    {"propertyName": "created_by", "operator": "EQ", "value": CREATED_BY},
                    {"propertyName": "createdate", "operator": "GTE", "value": after_date},
                    {"propertyName": "createdate", "operator": "LT", "value": before_date},
                ]
            }],
            "properties": [
                "dealname", "createdate", "amount", "dealstage",
                "pipeline", "hubspot_owner_id", "hs_object_id",
            ],
            "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}],
            "limit": 100,
        }
        if after_cursor:
            payload["after"] = after_cursor

        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Authorization": f"Bearer {HUBSPOT_TOKEN}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        all_results.extend(data.get("results", []))
        paging = data.get("paging", {}).get("next", {})
        after_cursor = paging.get("after")
        if not after_cursor:
            break

    return all_results


def get_contact_info(deal_id):
    url = (
        f"https://api.hubapi.com/crm/v4/objects/deals/{deal_id}"
        f"/associations/contacts"
    )
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [])
            if not results:
                return None, None
            contact_id = results[0].get("toObjectId")
    except Exception:
        return None, None

    url = (
        f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"
        f"?properties=country,company"
    )
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            props = json.loads(resp.read()).get("properties", {})
            return props.get("country", ""), props.get("company", "")
    except Exception:
        return None, None


def slack_post(text, blocks=None):
    payload = {"channel": SLACK_CHANNEL, "text": text}
    if blocks:
        payload["blocks"] = blocks
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=body,
        headers={
            "Authorization": f"Bearer {SLACK_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        if not data.get("ok"):
            print(f"Slack error: {data.get('error')}")
        else:
            print("Slack message sent")


def format_date(iso_str):
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return iso_str[:10]


COUNTRIES = {
    "re": ("La Réunion", "🇷🇪"), "gp": ("Guadeloupe", "🇬🇵"), "mq": ("Martinique", "🇲🇶"),
    "gf": ("Guyane", "🇬🇫"), "yt": ("Mayotte", "🇾🇹"), "nc": ("Nouvelle-Calédonie", "🇳🇨"),
    "pf": ("Polynésie française", "🇵🇫"), "ci": ("Côte d'Ivoire", "🇨🇮"), "sn": ("Sénégal", "🇸🇳"),
    "cm": ("Cameroun", "🇨🇲"), "mg": ("Madagascar", "🇲🇬"), "dz": ("Algérie", "🇩🇿"),
    "tn": ("Tunisie", "🇹🇳"), "ma": ("Maroc", "🇲🇦"), "ml": ("Mali", "🇲🇱"),
    "bf": ("Burkina Faso", "🇧🇫"), "ne": ("Niger", "🇳🇪"), "tg": ("Togo", "🇹🇬"),
    "bj": ("Bénin", "🇧🇯"), "cg": ("Congo", "🇨🇬"), "cd": ("RD Congo", "🇨🇩"),
    "ga": ("Gabon", "🇬🇦"), "td": ("Tchad", "🇹🇩"), "gn": ("Guinée", "🇬🇳"),
    "mu": ("Maurice", "🇲🇺"), "fr": ("France", "🇫🇷"), "be": ("Belgique", "🇧🇪"),
    "ch": ("Suisse", "🇨🇭"), "lu": ("Luxembourg", "🇱🇺"), "ca": ("Canada", "🇨🇦"),
    "ht": ("Haïti", "🇭🇹"), "lb": ("Liban", "🇱🇧"), "es": ("Espagne", "🇪🇸"),
    "de": ("Allemagne", "🇩🇪"), "it": ("Italie", "🇮🇹"), "pt": ("Portugal", "🇵🇹"),
    "gb": ("Royaume-Uni", "🇬🇧"), "us": ("États-Unis", "🇺🇸"), "br": ("Brésil", "🇧🇷"),
    "mx": ("Mexique", "🇲🇽"), "ar": ("Argentine", "🇦🇷"), "co": ("Colombie", "🇨🇴"),
    "cl": ("Chili", "🇨🇱"),
}


def country_label(code):
    if not code:
        return "🌍 Inconnu"
    entry = COUNTRIES.get(code.lower())
    if entry:
        return f"{entry[1]} {entry[0]}"
    return f"🌍 {code.upper()}"


IRVING_SLACK_ID = os.environ.get("IRVING_SLACK_ID", "U0A8723GPNV")


def build_blocks(deals_with_info, yesterday_str):
    n = len(deals_with_info)
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 Alerte — Nouveaux inbound leads, ready to call!!",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":sage: <@{IRVING_SLACK_ID}> : *{n}* nouveau(x) lead(s) sont entrés le *{yesterday_str}*. À toi de jouer ! 🔥",
            },
        },
        {"type": "divider"},
    ]

    for i, (deal, country, company) in enumerate(deals_with_info, 1):
        props = deal.get("properties", {})
        deal_id = props.get("hs_object_id", deal.get("id", ""))
        name = props.get("dealname", "Sans nom")
        created = format_date(props.get("createdate"))
        link = f"https://app.hubspot.com/contacts/{PORTAL_ID}/deal/{deal_id}"
        ctry = country_label(country)

        line = f"*{i}.* {ctry}  ·  <{link}|{name}>"
        if company:
            line += f"\n      🏢 *{company}*"
        line += f"\n      📅 {created}"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": line},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": ":sage: Bot Factorial · Leads hors-France · Chaque jour à 8h"}],
    })

    return blocks


def run():
    now = datetime.now(timezone.utc)

    if len(sys.argv) > 1:
        target = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        target = now - timedelta(days=1)

    day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    yesterday_str = day_start.strftime("%d/%m/%Y")

    after_ms = str(int(day_start.timestamp() * 1000))
    before_ms = str(int(day_end.timestamp() * 1000))

    print(f"[{now.isoformat()}] Deals créés le {yesterday_str}")

    deals = hubspot_search(after_ms, before_ms)
    print(f"  {len(deals)} deal(s) trouvé(s)")

    if not deals:
        print("  Aucun deal — pas de notification")
        return

    non_fr = []
    fr_skipped = 0

    for deal in deals:
        deal_id = deal.get("id", "")
        country, company = get_contact_info(deal_id)

        if country and country.upper() == "FR":
            fr_skipped += 1
            continue

        non_fr.append((deal, country or "", company or ""))

    print(f"  {len(non_fr)} hors-FR, {fr_skipped} FR (ignorés)")

    if not non_fr:
        print("  Tous les deals sont FR — pas de notification")
        return

    blocks = build_blocks(non_fr, yesterday_str)
    fallback = f"🌍 {len(non_fr)} deal(s) hors-France créés le {yesterday_str}"
    slack_post(fallback, blocks)


if __name__ == "__main__":
    run()
