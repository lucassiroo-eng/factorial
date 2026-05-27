import os
import sys
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timezone

sys.stdout.reconfigure(line_buffering=True)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
AZURE_BASE_URL = os.environ["ANTHROPIC_FOUNDRY_BASE_URL"].rstrip("/")
AZURE_API_KEY = os.environ["ANTHROPIC_FOUNDRY_API_KEY"]
AZURE_MODEL = os.environ.get("AZURE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a sales intelligence analyst for Factorial (HR SaaS).
You analyze call transcripts between Factorial reps and partner contacts (bank/telco employees who refer Factorial to their clients).

Given a partner contact's call history, extract structured insights.
Always respond in the SAME LANGUAGE as the transcript (Spanish, German, French, or English).

OUTPUT FORMAT (strict JSON, no markdown):
{
  "status": "active|warm|cold|new",
  "next_steps": "1-3 concrete next actions from the conversation",
  "key_signals": "buying signals, interest indicators, or engagement patterns",
  "blockers": "objections, risks, or blockers mentioned (or 'none')",
  "sentiment": "positive|neutral|negative",
  "summary": "2-3 sentence summary of the relationship and latest interaction"
}

Rules for status:
- "active": recent call (<7 days), engaged, clear next steps
- "warm": recent call, interested but no firm commitment
- "cold": no recent activity or disengaged
- "new": first call ever"""


def supabase_query(path, method="GET", body=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if method == "POST" and "partner_board" in path:
        url += "?on_conflict=contact_phone"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal" if method in ("POST", "PATCH") else "",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def call_claude(user_prompt: str) -> dict:
    url = f"{AZURE_BASE_URL}/v1/messages?api-version=2025-01-01-preview"
    body = json.dumps({
        "model": AZURE_MODEL,
        "max_tokens": 1000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": f"Bearer {AZURE_API_KEY}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            })
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
                text = data["content"][0]["text"].strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                return json.loads(text)
        except Exception as e:
            if attempt < 2:
                print(f"    Retry Claude ({e}), waiting {5 * (attempt + 1)}s...")
                time.sleep(5 * (attempt + 1))
            else:
                print(f"    Claude failed: {e}")
                return None


def get_partners_with_calls():
    return supabase_query(
        "partner_front?in_partner_map=eq.true&select=id,contact_phone,contact_name,contact_email,"
        "account_name,partner,partner_contact_name,call_count,last_call_at,call_ids"
        "&order=call_count.desc"
    )


def get_last_calls(call_ids: list, limit: int = 3) -> list:
    if not call_ids:
        return []
    ids_filter = ",".join(str(cid) for cid in sorted(call_ids, reverse=True)[:limit])
    return supabase_query(
        f"modjo_calls?id=in.({ids_filter})&select=id,title,start_date,duration,transcript,summary,owner_name"
        "&order=start_date.desc"
    )


def build_prompt(partner: dict, calls: list) -> str:
    lines = [
        f"Partner: {partner.get('partner_contact_name') or partner.get('contact_name') or 'Unknown'}",
        f"Organization: {partner.get('partner') or 'Unknown'}",
        f"Phone: {partner.get('contact_phone')}",
        f"Total calls: {partner.get('call_count', 0)}",
        f"Last contact: {partner.get('last_call_at', 'unknown')[:10] if partner.get('last_call_at') else 'unknown'}",
        "",
        "=== CALL TRANSCRIPTS (most recent first) ===",
    ]
    for call in calls:
        lines.append(f"\n--- Call: {call.get('title', '')} | {call.get('start_date', '')[:10]} | Rep: {call.get('owner_name', '')} | {call.get('duration', 0):.0f}s ---")
        transcript = call.get("transcript") or ""
        if len(transcript) > 4000:
            transcript = transcript[:4000] + "\n[...truncated]"
        if transcript.strip():
            lines.append(transcript)
        summary = call.get("summary") or ""
        if summary.strip():
            lines.append(f"\nAI Summary: {summary[:1000]}")

    return "\n".join(lines)


def enrich():
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Starting partner board enrichment")

    partners = get_partners_with_calls()
    print(f"  {len(partners)} matched partners to enrich")

    enriched = 0
    skipped = 0

    for i, p in enumerate(partners):
        call_ids = p.get("call_ids") or []
        if not call_ids:
            skipped += 1
            continue

        calls = get_last_calls(call_ids)
        if not calls:
            skipped += 1
            continue

        has_content = any((c.get("transcript") or "").strip() and not all(
            line.strip().startswith("[") and "]" in line and line.strip().endswith("")
            for line in (c.get("transcript") or "").strip().split("\n")[:5]
            if line.strip()
        ) for c in calls)

        if not has_content:
            # Still insert but without AI enrichment
            row = {
                "partner_front_id": p["id"],
                "partner": p.get("partner"),
                "partner_contact_name": p.get("partner_contact_name"),
                "contact_name": p.get("contact_name"),
                "contact_phone": p["contact_phone"],
                "contact_email": p.get("contact_email"),
                "account_name": p.get("account_name"),
                "call_count": p.get("call_count", 0),
                "last_call_at": p.get("last_call_at"),
                "last_call_id": call_ids[-1] if call_ids else None,
                "status": "unknown",
                "next_steps": "No transcript available",
                "updated_at": now.isoformat(),
            }
            supabase_query("partner_board", method="POST", body=[row])
            skipped += 1
            continue

        prompt = build_prompt(p, calls)
        insights = call_claude(prompt)

        last_call = calls[0] if calls else {}
        row = {
            "partner_front_id": p["id"],
            "partner": p.get("partner"),
            "partner_contact_name": p.get("partner_contact_name"),
            "contact_name": p.get("contact_name"),
            "contact_phone": p["contact_phone"],
            "contact_email": p.get("contact_email"),
            "account_name": p.get("account_name"),
            "call_count": p.get("call_count", 0),
            "last_call_at": p.get("last_call_at"),
            "last_call_id": last_call.get("id"),
            "status": insights.get("status", "unknown") if insights else "error",
            "next_steps": insights.get("next_steps", "") if insights else "AI analysis failed",
            "key_signals": insights.get("key_signals", "") if insights else None,
            "blockers": insights.get("blockers", "") if insights else None,
            "sentiment": insights.get("sentiment", "") if insights else None,
            "call_summary": insights.get("summary", "") if insights else None,
            "enriched_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        supabase_query("partner_board", method="POST", body=[row])
        enriched += 1
        name = p.get("partner_contact_name") or p.get("contact_name") or "?"
        status = row["status"]
        print(f"  [{i+1}/{len(partners)}] {name[:35]:35} | {p.get('partner','?'):10} | {status:8} | {p.get('call_count',0)} calls")

        time.sleep(0.5)

    print(f"\n  Done: {enriched} enriched, {skipped} skipped (no transcript)")


if __name__ == "__main__":
    enrich()
