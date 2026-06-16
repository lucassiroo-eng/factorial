"""
Backfill partner calls from Modjo into modjo_calls table.

Includes ALL calls to contacts in partner_map (by phone or email),
not just calls tagged with 991. Skips calls already in modjo_calls.

Usage:
  python backfill_partner_calls.py 2026 1   # January 2026
  python backfill_partner_calls.py 2026 6   # June 2026
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(line_buffering=True)

MODJO_API_KEY      = os.environ["MODJO_API_KEY"]
SUPABASE_URL       = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

TAG_991       = 3136
MODJO_EXPORT  = "https://api.modjo.ai/v1/calls/exports"
PER_PAGE      = 50
MAX_RETRIES   = 3


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _request(req, timeout=60, parse_json=True):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                return json.loads(body) if (parse_json and body) else body
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 60 * attempt  # rate limit: back off hard
                print(f"    [429 rate limit] waiting {wait}s (attempt {attempt}/{MAX_RETRIES})", flush=True)
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(wait)
            else:
                raise
            req = urllib.request.Request(
                req.full_url, data=req.data,
                headers=dict(req.headers), method=req.get_method()
            )
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == MAX_RETRIES:
                raise
            wait = 5 * attempt
            print(f"    [retry {attempt}/{MAX_RETRIES}] {e} — waiting {wait}s", flush=True)
            time.sleep(wait)
            req = urllib.request.Request(
                req.full_url, data=req.data,
                headers=dict(req.headers), method=req.get_method()
            )


def supabase_get(path):
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        }
    )
    return _request(req)


def supabase_upsert(rows):
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
        }
    )
    _request(req, parse_json=False)


def modjo_export(page, start, end):
    body = json.dumps({
        "pagination": {"page": page, "perPage": PER_PAGE},
        "filters": {"callStartDateRange": {"start": start, "end": end}},
        "relations": {
            "tags": True, "transcript": True, "users": True,
            "contacts": True, "summary": True, "speakers": True,
            "deal": True, "account": True,
        },
    }).encode()
    req = urllib.request.Request(
        MODJO_EXPORT, data=body,
        headers={"x-api-key": MODJO_API_KEY, "Content-Type": "application/json"}
    )
    return _request(req)


# ── Matching helpers ──────────────────────────────────────────────────────────

def norm_phone(p, tail=9):
    """Strip non-digits, return last `tail` digits."""
    if not p:
        return None
    digits = ''.join(c for c in p if c.isdigit())
    return digits[-tail:] if len(digits) >= tail else None


def has_991_tag(call):
    tags = call.get("relations", {}).get("tags") or []
    return any(t.get("tagId") == TAG_991 for t in tags)


def match_source(call, partner_phones, partner_emails):
    """Return match reason or None."""
    if has_991_tag(call):
        return "tag_991"
    contacts = call.get("relations", {}).get("contacts") or []
    for c in contacts:
        p = norm_phone(c.get("phoneNumber"))
        if p and p in partner_phones:
            return "phone_match"
        e = (c.get("email") or "").lower()
        if e and e in partner_emails:
            return "email_match"
    return None


# ── Transform ────────────────────────────────────────────────────────────────

def transform(call, source):
    rels = call.get("relations") or {}

    transcript_parts = rels.get("transcript") or []
    transcript_text = "\n".join(
        f"[{p.get('startTime', '')}] {p.get('content', '')}"
        for p in transcript_parts if isinstance(p, dict)
    ) if isinstance(transcript_parts, list) else str(transcript_parts)

    summary_obj = rels.get("summary") or {}
    summary_text = summary_obj.get("content", "") if isinstance(summary_obj, dict) else str(summary_obj)

    users    = rels.get("users") or []
    owner    = next((u for u in users if u.get("isOwner")), users[0] if users else {})
    contacts = rels.get("contacts") or []
    contact  = contacts[0] if contacts else {}
    account  = rels.get("account") or {}
    deal     = rels.get("deal") or {}

    tags = rels.get("tags") or []
    if source != "tag_991":
        tags = tags + [{"tagId": 0, "name": f"auto:{source}"}]

    return {
        "id":               call["callId"],
        "provider_call_id": call.get("providerCallId"),
        "title":            call.get("title"),
        "start_date":       call.get("startDate"),
        "duration":         call.get("duration"),
        "provider":         call.get("provider"),
        "language":         call.get("language"),
        "call_crm_id":      call.get("callCrmId"),
        "tags":             json.dumps(tags),
        "transcript":       transcript_text or None,
        "users":            json.dumps(users),
        "contacts":         json.dumps(contacts),
        "summary":          summary_text or None,
        "owner_name":       owner.get("name"),
        "owner_email":      owner.get("email"),
        "contact_name":     contact.get("name"),
        "contact_email":    contact.get("email"),
        "contact_phone":    contact.get("phoneNumber"),
        "account_name":     account.get("name") if isinstance(account, dict) else None,
        "account_crm_id":   account.get("accountCrmId") if isinstance(account, dict) else None,
        "deal_name":        deal.get("name") if isinstance(deal, dict) else None,
        "deal_crm_id":      deal.get("dealCrmId") if isinstance(deal, dict) else None,
        "speakers":         json.dumps(rels.get("speakers") or []),
        "synced_at":        datetime.now(timezone.utc).isoformat(),
    }


# ── Main backfill ─────────────────────────────────────────────────────────────

def load_partner_map():
    """Load partner phones (last 9 digits) and emails from Supabase."""
    rows = supabase_get("partner_map?select=phone_number,mail&limit=5000")
    phones = set()
    emails = set()
    for r in rows:
        p = norm_phone(r.get("phone_number"))
        if p:
            phones.add(p)
        e = (r.get("mail") or "").lower()
        if e:
            emails.add(e)
    print(f"  Partner map loaded: {len(phones)} phones, {len(emails)} emails", flush=True)
    return phones, emails


def load_existing_ids():
    """Load all call IDs already in modjo_calls."""
    rows = supabase_get("modjo_calls?select=id&limit=10000")
    ids = {r["id"] for r in rows}
    print(f"  Existing modjo_calls: {len(ids)} records", flush=True)
    return ids


def backfill_month(year, month):
    now = datetime.now(timezone.utc)
    label = f"{year}-{month:02d}"
    print(f"\n{'='*60}", flush=True)
    print(f"  BACKFILL {label}", flush=True)
    print(f"{'='*60}", flush=True)

    partner_phones, partner_emails = load_partner_map()
    existing_ids = load_existing_ids()

    start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
    end_dt   = datetime(year, month + 1, 1, tzinfo=timezone.utc) if month < 12 \
               else datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    if end_dt > now:
        end_dt = now

    total_days   = (end_dt - start_dt).days
    grand_new    = 0
    grand_skip   = 0
    grand_scanned = 0

    current = start_dt
    day_num = 0
    while current < end_dt:
        day_num += 1
        day_end = current + timedelta(days=1)
        if day_end > end_dt:
            day_end = end_dt
        s = current.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        e = day_end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        day_label = current.strftime("%Y-%m-%d")

        data      = modjo_export(1, s, e)
        pag       = data.get("pagination", {})
        last_page = pag.get("lastPage", 1) or 1
        day_total = pag.get("totalValues", 0)

        day_new  = 0
        day_skip = 0

        print(f"\n  [{day_label}] day {day_num}/{total_days} — {day_total} calls, {last_page} pages", flush=True)

        page = 1
        while page <= last_page:
            if page > 1:
                data = modjo_export(page, s, e)

            calls = data.get("values", [])
            grand_scanned += len(calls)

            rows_to_upsert = []
            for call in calls:
                cid = call["callId"]
                if cid in existing_ids:
                    day_skip += 1
                    continue
                src = match_source(call, partner_phones, partner_emails)
                if src:
                    rows_to_upsert.append(transform(call, src))
                    existing_ids.add(cid)

            if rows_to_upsert:
                supabase_upsert(rows_to_upsert)
                day_new += len(rows_to_upsert)

            print(
                f"    page {page:>4}/{last_page} "
                f"| +{len(rows_to_upsert):>3} new "
                f"| {day_skip:>4} skipped "
                f"| day total new: {day_new}",
                flush=True
            )

            page += 1
            if page <= last_page:
                time.sleep(1.0)

        grand_new  += day_new
        grand_skip += day_skip
        print(f"  [{day_label}] done — {day_new} new partner calls upserted", flush=True)
        current = day_end

    print(f"\n{'='*60}", flush=True)
    print(f"  {label} COMPLETE", flush=True)
    print(f"  Scanned: {grand_scanned} | New: {grand_new} | Skipped (existing): {grand_skip}", flush=True)
    print(f"{'='*60}\n", flush=True)
    return grand_new


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python backfill_partner_calls.py <year> <month>")
        sys.exit(1)
    year  = int(sys.argv[1])
    month = int(sys.argv[2])
    backfill_month(year, month)
