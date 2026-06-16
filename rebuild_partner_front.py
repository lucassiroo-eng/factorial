"""
Rebuilds partner_front from modjo_calls + partner_map.

Groups all calls by contact_phone, cross-references with partner_map
by phone (last 9 digits) or email, and upserts into partner_front.

Usage:
  python rebuild_partner_front.py
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from collections import defaultdict

sys.stdout.reconfigure(line_buffering=True)

SUPABASE_URL         = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def supabase_get(path):
    results = []
    offset = 0
    while True:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/{path}&limit=1000&offset={offset}",
            headers={
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            }
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            batch = json.loads(r.read())
        results.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    return results


def supabase_upsert(rows, conflict="contact_phone"):
    if not rows:
        return
    body = json.dumps(rows).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/partner_front?on_conflict={conflict}",
        data=body,
        headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


# ── Helpers ───────────────────────────────────────────────────────────────────

def norm_phone(p, tail=9):
    if not p:
        return None
    digits = ''.join(c for c in p if c.isdigit())
    return digits[-tail:] if len(digits) >= tail else None


# ── Main ──────────────────────────────────────────────────────────────────────

def rebuild():
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Starting partner_front rebuild", flush=True)

    # 1. Load partner_map (all partners)
    print("  Loading partner_map...", flush=True)
    pm_rows = supabase_get("partner_map?select=*")
    pm_by_phone = {}
    pm_by_email = {}
    for r in pm_rows:
        p = norm_phone(r.get("phone_number"))
        if p:
            pm_by_phone[p] = r
        e = (r.get("mail") or "").lower()
        if e:
            pm_by_email[e] = r
    print(f"  partner_map: {len(pm_rows)} rows | {len(pm_by_phone)} phones | {len(pm_by_email)} emails", flush=True)

    # 2. Load all modjo_calls
    print("  Loading modjo_calls...", flush=True)
    calls = supabase_get(
        "modjo_calls?select=id,contact_phone,contact_name,contact_email,"
        "account_name,account_crm_id,start_date,synced_at"
    )
    print(f"  modjo_calls: {len(calls)} rows", flush=True)

    # 3. Group calls by contact_phone (normalized)
    groups = defaultdict(list)
    no_phone = 0
    for c in calls:
        p = norm_phone(c.get("contact_phone"))
        if p:
            groups[p].append(c)
        else:
            no_phone += 1
    print(f"  Grouped into {len(groups)} unique phones ({no_phone} calls had no phone)", flush=True)

    # 4. Build partner_front rows
    rows = []
    matched = 0
    unmatched = 0

    for phone_norm, group_calls in groups.items():
        # Find partner_map match
        pm = pm_by_phone.get(phone_norm)

        # Try email match if no phone match
        if not pm:
            for c in group_calls:
                e = (c.get("contact_email") or "").lower()
                if e and e in pm_by_email:
                    pm = pm_by_email[e]
                    break

        in_partner_map = pm is not None
        if in_partner_map:
            matched += 1
        else:
            unmatched += 1

        # Pick representative call for contact metadata
        rep = sorted(group_calls, key=lambda x: x.get("start_date") or "", reverse=True)[0]
        call_ids = [c["id"] for c in group_calls]
        dates = [c["start_date"] for c in group_calls if c.get("start_date")]
        first_call = min(dates) if dates else None
        last_call  = max(dates) if dates else None

        row = {
            "contact_phone":        rep.get("contact_phone"),
            "contact_name":         rep.get("contact_name"),
            "contact_email":        rep.get("contact_email"),
            "account_name":         rep.get("account_name"),
            "account_crm_id":       rep.get("account_crm_id"),
            "call_count":           len(call_ids),
            "call_ids":             call_ids,
            "first_call_at":        first_call,
            "last_call_at":         last_call,
            "in_partner_map":       in_partner_map,
            "partner":              pm.get("partner") if pm else None,
            "partner_contact_name": pm.get("name") if pm else None,
            "territory":            pm.get("territory") if pm else None,
            "zone":                 pm.get("zone") if pm else None,
            "office":               pm.get("office") if pm else None,
            "partner_role":         pm.get("role") if pm else None,
            "team":                 pm.get("team") if pm else None,
            "updated_at":           now,
        }
        rows.append(row)

    print(f"\n  Built {len(rows)} partner_front rows:", flush=True)
    print(f"    in_partner_map=true:  {matched}", flush=True)
    print(f"    in_partner_map=false: {unmatched}", flush=True)

    # 5. Upsert in batches of 200
    print(f"\n  Upserting to partner_front...", flush=True)
    batch_size = 200
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        supabase_upsert(batch)
        print(f"    {min(i + batch_size, len(rows))}/{len(rows)} upserted", flush=True)

    # 6. Summary by partner
    from collections import Counter
    partner_counts = Counter(r["partner"] for r in rows if r.get("partner"))
    print(f"\n  Partners found:", flush=True)
    for partner, count in partner_counts.most_common():
        print(f"    {partner}: {count} contacts", flush=True)

    print(f"\n  Done. {len(rows)} rows in partner_front.", flush=True)


if __name__ == "__main__":
    rebuild()
