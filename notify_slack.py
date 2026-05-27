import os
import sys
import json
import urllib.request
from datetime import datetime, timezone

sys.stdout.reconfigure(line_buffering=True)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
SLACK_TOKEN = os.environ["SLACK_TOKEN"]
SLACK_USER = os.environ.get("SLACK_USER_ID", "U0AF9M5AXPE")


def supabase_query(path):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def slack_dm(text):
    body = json.dumps({"channel": SLACK_USER, "text": text}).encode()
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


def build_report():
    calls = supabase_query(
        "modjo_calls?select=id,contact_phone,synced_at"
        "&synced_at=gte." + datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        + "&order=synced_at.desc"
    )

    enriched = supabase_query(
        "partner_board?select=contact_phone,partner,partner_contact_name,"
        "relationship_stage,engagement,enriched_at"
        "&enriched_at=gte." + datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        + "&order=enriched_at.desc"
    )

    total_board = supabase_query("partner_board?select=id&limit=1000")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n_calls = len(calls)
    phones_called = set(c.get("contact_phone") for c in calls if c.get("contact_phone"))
    n_partners_enriched = len(enriched)
    n_total = len(total_board)

    by_partner = {}
    for r in enriched:
        org = r.get("partner") or "Unknown"
        by_partner[org] = by_partner.get(org, 0) + 1

    lines = [f"Partner Pipeline — {today}\n"]

    if n_calls == 0 and n_partners_enriched == 0:
        lines.append("No new calls or enrichments today.")
    else:
        lines.append(f"Modjo sync: {n_calls} calls synced ({len(phones_called)} unique contacts)")
        partner_breakdown = ", ".join(f"{v} {k}" for k, v in sorted(by_partner.items(), key=lambda x: -x[1]))
        lines.append(f"Partners enriched: {n_partners_enriched} of {n_total} total" +
                      (f" ({partner_breakdown})" if partner_breakdown else ""))

        top = enriched[:5]
        if top:
            lines.append("")
            for r in top:
                name = r.get("partner_contact_name") or "?"
                org = r.get("partner") or ""
                stage = r.get("relationship_stage") or "?"
                eng = r.get("engagement") or "?"
                lines.append(f"  {name} ({org}) — {stage}/{eng}")

    return "\n".join(lines)


if __name__ == "__main__":
    report = build_report()
    print(report)
    slack_dm(report)
