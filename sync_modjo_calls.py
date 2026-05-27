import os
import sys
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(line_buffering=True)

MODJO_API_KEY = os.environ["MODJO_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

TAG_ID = 3136  # "991. Partners - PBD Partner Call"
MODJO_EXPORT_URL = "https://api.modjo.ai/v1/calls/exports"
PER_PAGE = 50
MAX_PAGES_PER_CHUNK = 120
MAX_RETRIES = 3


def _request_with_retry(req, timeout=60, parse_json=True):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if not parse_json or not body:
                    return body
                return json.loads(body)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == MAX_RETRIES:
                raise
            wait = 5 * attempt
            print(f"    Retry {attempt}/{MAX_RETRIES} after error: {e} (waiting {wait}s)")
            time.sleep(wait)
            req = urllib.request.Request(
                req.full_url, data=req.data, headers=dict(req.headers), method=req.method
            )


def modjo_export(page: int, start: str, end: str) -> dict:
    body = json.dumps({
        "pagination": {"page": page, "perPage": PER_PAGE},
        "filters": {
            "callStartDateRange": {"start": start, "end": end},
        },
        "relations": {
            "tags": True,
            "transcript": True,
            "users": True,
            "contacts": True,
            "summary": True,
            "speakers": True,
            "deal": True,
            "account": True,
        },
    }).encode()
    req = urllib.request.Request(
        MODJO_EXPORT_URL,
        data=body,
        headers={
            "x-api-key": MODJO_API_KEY,
            "Content-Type": "application/json",
        },
    )
    return _request_with_retry(req)


def has_991_tag(call: dict) -> bool:
    tags = call.get("relations", {}).get("tags") or []
    return any(t.get("tagId") == TAG_ID for t in tags)


def upsert_to_supabase(rows: list[dict]):
    if not rows:
        return
    body = json.dumps(rows).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/modjo_calls",
        data=body,
        headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
    )
    _request_with_retry(req, parse_json=False)


def transform(call: dict) -> dict:
    rels = call.get("relations") or {}

    transcript_parts = rels.get("transcript") or []
    transcript_text = "\n".join(
        f"[{p.get('startTime', '')}] {p.get('content', '')}"
        for p in transcript_parts
        if isinstance(p, dict)
    ) if isinstance(transcript_parts, list) else str(transcript_parts)

    summary_obj = rels.get("summary") or {}
    summary_text = summary_obj.get("content", "") if isinstance(summary_obj, dict) else str(summary_obj)

    users = rels.get("users") or []
    owner = next((u for u in users if u.get("isOwner")), users[0] if users else {})

    contacts = rels.get("contacts") or []
    contact = contacts[0] if contacts else {}

    account = rels.get("account") or {}
    deal = rels.get("deal") or {}

    return {
        "id": call["callId"],
        "provider_call_id": call.get("providerCallId"),
        "title": call.get("title"),
        "start_date": call.get("startDate"),
        "duration": call.get("duration"),
        "provider": call.get("provider"),
        "language": call.get("language"),
        "call_crm_id": call.get("callCrmId"),
        "tags": json.dumps(rels.get("tags") or []),
        "transcript": transcript_text or None,
        "users": json.dumps(users),
        "contacts": json.dumps(contacts),
        "summary": summary_text or None,
        "owner_name": owner.get("name"),
        "owner_email": owner.get("email"),
        "contact_name": contact.get("name"),
        "contact_email": contact.get("email"),
        "contact_phone": contact.get("phoneNumber"),
        "account_name": account.get("name") if isinstance(account, dict) else None,
        "account_crm_id": account.get("accountCrmId") if isinstance(account, dict) else None,
        "deal_name": deal.get("name") if isinstance(deal, dict) else None,
        "deal_crm_id": deal.get("dealCrmId") if isinstance(deal, dict) else None,
        "speakers": json.dumps(rels.get("speakers") or []),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def scan_range(start: str, end: str, label: str = "") -> int:
    page = 1
    total_991 = 0
    total_scanned = 0

    data = modjo_export(page, start, end)
    pag = data.get("pagination", {})
    last_page = pag.get("lastPage", 1)
    total_in_range = pag.get("totalValues", 0)
    print(f"  [{label}] {total_in_range} calls in range, {last_page} pages")

    while True:
        if page > 1:
            data = modjo_export(page, start, end)
            pag = data.get("pagination", {})
            last_page = pag.get("lastPage", 1)

        calls = data.get("values", [])
        total_scanned += len(calls)

        matched = [transform(c) for c in calls if has_991_tag(c)]
        total_991 += len(matched)

        if matched:
            upsert_to_supabase(matched)
            print(f"    page {page}/{last_page} → +{len(matched)} calls 991 (total: {total_991})")

        if page % 20 == 0 and not matched:
            print(f"    page {page}/{last_page} scanning... ({total_scanned} scanned, {total_991} matched)")

        if page >= last_page or page >= MAX_PAGES_PER_CHUNK:
            break
        page += 1

    print(f"  [{label}] done: {total_scanned} scanned, {total_991} with 991 synced")
    return total_991


def sync(hours_back: int = 26):
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    print(f"[{now.isoformat()}] Sync: {start} → {end}")
    total = scan_range(start, end, f"last {hours_back}h")
    print(f"  Done: {total} calls synced")


def backfill_month(year: int, month: int):
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Backfill: {year}-{month:02d}")

    start_date = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    if end_month > now:
        end_month = now

    grand_total = 0
    current = start_date
    while current < end_month:
        day_end = current + timedelta(days=1)
        if day_end > end_month:
            day_end = end_month
        s = current.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        e = day_end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        label = current.strftime("%Y-%m-%d")
        total = scan_range(s, e, label)
        grand_total += total
        current = day_end

    print(f"  Month done: {grand_total} total 991 calls synced")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        year = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
        month = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        backfill_month(year, month)
    else:
        sync()
