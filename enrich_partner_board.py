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
You analyze call transcripts between Factorial PBDs (Partner Business Developers) and partner contacts.
Partners are employees at banks or telcos (Santander, Telekom, TIM) who refer Factorial to their SMB clients.

Respond in the SAME LANGUAGE as the transcript.

## DICTIONARIES — follow these strictly

### relationship_stage (pick ONE):
- "new": First interaction ever. No prior history.
- "developing": 2-4 calls. Getting to know each other. No leads generated yet.
- "active": 5+ calls OR partner has referred/committed to refer clients. Regular cadence.
- "dormant": Last call was 14+ days ago AND no pending action mentioned in last call.

### engagement (pick ONE, deterministic rules):
- "Low": 1-2 calls total AND last call > 7 days ago. Or partner was unresponsive/disinterested.
- "Medium": 3-5 calls total OR partner showed interest but no concrete commitments yet.
- "High": 6+ calls OR partner actively generating leads, sharing contacts, scheduling joint events.
- "Julio Iglesias": Partner is a champion. Evidence of ALL: (a) proactively sharing client lists/contacts, (b) co-organizing events or meetings, (c) advocating for Factorial internally. Reserved for exceptional partners only.

## OUTPUT FORMAT (strict JSON, no markdown, no explanation):
{
  "relationship_stage": "new|developing|active|dormant",
  "engagement": "Low|Medium|High|Julio Iglesias",
  "next_action": "1-2 concrete next actions with owner (rep or partner)",
  "next_action_date": "YYYY-MM-DD or null if not mentioned",
  "pains": "partner's frustrations, difficulties, or unmet needs expressed in calls (or 'none')",
  "summary": "2-3 sentence summary of the relationship status and latest interaction"
}"""


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
        "partner,partner_contact_name,call_count,last_call_at,call_ids,"
        "territory,zone,partner_role,team"
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


def get_all_reps(call_ids: list) -> str:
    if not call_ids:
        return ""
    ids_filter = ",".join(str(cid) for cid in call_ids)
    calls = supabase_query(
        f"modjo_calls?id=in.({ids_filter})&select=owner_name"
    )
    reps = sorted(set(c["owner_name"] for c in (calls or []) if c.get("owner_name")))
    return ", ".join(reps)


def build_prompt(partner: dict, calls: list) -> str:
    lines = [
        f"Partner: {partner.get('partner_contact_name') or partner.get('contact_name') or 'Unknown'}",
        f"Organization: {partner.get('partner') or 'Unknown'}",
        f"Role: {partner.get('partner_role') or 'Unknown'}",
        f"Territory: {partner.get('territory') or 'Unknown'}",
        f"Zone: {partner.get('zone') or 'Unknown'}",
        f"Total calls: {partner.get('call_count', 0)}",
        f"Last contact: {partner.get('last_call_at', 'unknown')[:10] if partner.get('last_call_at') else 'unknown'}",
        f"Today: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        "=== CALL TRANSCRIPTS (most recent first) ===",
    ]
    for call in calls:
        lines.append(f"\n--- {call.get('title', '')} | {call.get('start_date', '')[:10]} | Rep: {call.get('owner_name', '')} | {call.get('duration', 0):.0f}s ---")
        transcript = call.get("transcript") or ""
        if len(transcript) > 4000:
            transcript = transcript[:4000] + "\n[...truncated]"
        if transcript.strip():
            lines.append(transcript)
        summary = call.get("summary") or ""
        if summary.strip():
            lines.append(f"\nAI Summary: {summary[:1000]}")

    return "\n".join(lines)


def get_partners_to_enrich(incremental=True):
    partners = get_partners_with_calls()
    if not incremental:
        return partners

    board = supabase_query("partner_board?select=contact_phone,enriched_at") or []
    enriched_map = {r["contact_phone"]: r.get("enriched_at") for r in board}

    result = []
    for p in partners:
        phone = p["contact_phone"]
        enriched_at = enriched_map.get(phone)
        last_call = p.get("last_call_at")
        if not enriched_at or (last_call and last_call > enriched_at):
            result.append(p)
    return result


def enrich(incremental=True):
    now = datetime.now(timezone.utc)
    mode = "incremental" if incremental else "full"
    print(f"[{now.isoformat()}] Starting partner board enrichment ({mode})")

    partners = get_partners_to_enrich(incremental)
    print(f"  {len(partners)} partners to enrich")

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

        has_content = any(len((c.get("transcript") or "").strip()) > 50 for c in calls)
        reps = get_all_reps(call_ids)
        last_call = calls[0] if calls else {}

        base_row = {
            "partner_front_id": p["id"],
            "partner": p.get("partner"),
            "partner_contact_name": p.get("partner_contact_name"),
            "contact_name": p.get("contact_name"),
            "contact_phone": p["contact_phone"],
            "contact_email": p.get("contact_email"),
            "territory": p.get("territory"),
            "zone": p.get("zone"),
            "partner_role": p.get("partner_role"),
            "team": p.get("team"),
            "call_count": p.get("call_count", 0),
            "last_call_at": p.get("last_call_at"),
            "last_call_id": last_call.get("id"),
            "reps": reps,
            "updated_at": now.isoformat(),
        }

        if not has_content:
            base_row.update({
                "relationship_stage": "new" if p.get("call_count", 0) <= 1 else "developing",
                "engagement": "Low",
                "next_action": "No transcript available for analysis",
            })
            supabase_query("partner_board", method="POST", body=[base_row])
            skipped += 1
            continue

        prompt = build_prompt(p, calls)
        insights = call_claude(prompt)

        if insights:
            base_row.update({
                "relationship_stage": insights.get("relationship_stage", "unknown"),
                "engagement": insights.get("engagement", "Low"),
                "next_action": insights.get("next_action", ""),
                "next_action_date": insights.get("next_action_date"),
                "pains": insights.get("pains", ""),
                "call_summary": insights.get("summary", ""),
                "enriched_at": now.isoformat(),
            })
        else:
            base_row.update({
                "relationship_stage": "unknown",
                "engagement": "Low",
                "next_action": "AI analysis failed - retry needed",
            })

        supabase_query("partner_board", method="POST", body=[base_row])
        enriched += 1
        name = p.get("partner_contact_name") or p.get("contact_name") or "?"
        stage = base_row.get("relationship_stage", "?")
        eng = base_row.get("engagement", "?")
        print(f"  [{i+1}/{len(partners)}] {name[:30]:30} | {p.get('partner','?'):10} | {stage:12} | {eng:16} | {p.get('call_count',0)} calls")

        time.sleep(0.5)

    print(f"\n  Done: {enriched} enriched, {skipped} skipped")


if __name__ == "__main__":
    full = "--full" in sys.argv
    enrich(incremental=not full)
