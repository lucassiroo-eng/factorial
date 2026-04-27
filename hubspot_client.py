import os
import calendar
import datetime
import requests
from datetime import date, timedelta

HUBSPOT_BASE = "https://api.hubapi.com"

# ── Property names (verificados con discover_properties.py) ───────────────────
# ⚠️  Verify this property name in HubSpot: Settings → Properties → Deals
DEMO_HELD_PROP = "date_demo_held"

DEAL_PROPS = [
    "dealname", "amount", "dealstage", "hubspot_owner_id",
    "first_meeting_at", "industry",
    "country_qobra_samba",
    DEMO_HELD_PROP,
]
CONTACT_PROPS = ["firstname", "lastname", "jobtitle", "email"]
COMPANY_PROPS = ["name", "industry", "numberofemployees", "country"]
# ─────────────────────────────────────────────────────────────────────────────


_DAILY_CALL_LIMIT = 50_000


def _fallback_owner() -> dict:
    """Returns owner dict from AE_NAME / AE_EMAIL env vars when HubSpot scope is missing."""
    name  = os.environ.get("AE_NAME", "").strip()
    email = os.environ.get("AE_EMAIL", "").strip()
    first, *rest = name.split(" ", 1) if name else ("", [])
    last = rest[0] if rest else ""
    if name:
        print(f"[→] Owner fallback: {name} <{email}>")
    return {"firstName": first, "lastName": last, "email": email}


class HubSpotClient:
    def __init__(self):
        self.token = os.environ["HUBSPOT_API_KEY"]
        self._call_count = 0
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })

    def _get(self, *args, **kwargs):
        return self._request("GET", *args, **kwargs)

    def _post(self, *args, **kwargs):
        return self._request("POST", *args, **kwargs)

    def _request(self, method: str, url: str, **kwargs):
        self._call_count += 1
        if self._call_count > _DAILY_CALL_LIMIT:
            raise RuntimeError(
                f"[HARD STOP] HubSpot daily call limit reached ({_DAILY_CALL_LIMIT}). "
                "Aborting to protect API quota."
            )
        if self._call_count % 1000 == 0:
            print(f"[!] HubSpot API calls so far this run: {self._call_count}/{_DAILY_CALL_LIMIT}")
        return self.session.request(method, url, **kwargs)

    # ── Deal search ───────────────────────────────────────────────────────────

    def get_next_future_deal(self, filter_type: str, filter_value: str) -> dict | None:
        """
        Devuelve el deal con first_meeting_at más próximo a mañana en adelante.
        filter_type: "owner" | "market"
        """
        tomorrow_ms = str(_date_to_ms(date.today() + timedelta(days=1)))

        base_filters = [
            {"propertyName": "first_meeting_at", "operator": "GTE", "value": tomorrow_ms},
            {"propertyName": "pipeline", "operator": "EQ", "value": PIPELINE_IDS["partners distribution"]},
            {"propertyName": DEMO_HELD_PROP, "operator": "NOT_HAS_PROPERTY"},
            _build_filter(filter_type, filter_value),
        ]

        payload = {
            "filterGroups": [{"filters": base_filters}],
            "properties": DEAL_PROPS,
            "sorts": [{"propertyName": "first_meeting_at", "direction": "ASCENDING"}],
            "limit": 1,
        }
        resp = self._post(f"{HUBSPOT_BASE}/crm/v3/objects/deals/search", json=payload)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return results[0] if results else None

    def get_all_future_deals(self, filter_type: str, filter_value: str, target_date: date | None = None) -> list:
        """Devuelve todos los deals para target_date (o desde mañana si no se indica)."""
        if target_date:
            lower_ms = str(_date_to_ms(target_date))
            upper_ms = str(_date_to_ms(target_date + timedelta(days=1)))
            date_filters = [
                {"propertyName": "first_meeting_at", "operator": "GTE", "value": lower_ms},
                {"propertyName": "first_meeting_at", "operator": "LT",  "value": upper_ms},
            ]
        else:
            date_filters = [
                {"propertyName": "first_meeting_at", "operator": "GTE", "value": str(_date_to_ms(date.today() + timedelta(days=1)))},
            ]

        base_filters = [
            *date_filters,
            {"propertyName": "pipeline", "operator": "EQ", "value": PIPELINE_IDS["partners distribution"]},
            {"propertyName": DEMO_HELD_PROP, "operator": "NOT_HAS_PROPERTY"},
            _build_filter(filter_type, filter_value),
        ]

        all_deals, after = [], None
        while True:
            payload = {
                "filterGroups": [{"filters": base_filters}],
                "properties": DEAL_PROPS,
                "sorts": [{"propertyName": "first_meeting_at", "direction": "ASCENDING"}],
                "limit": 100,
            }
            if after:
                payload["after"] = after
            resp = self._post(f"{HUBSPOT_BASE}/crm/v3/objects/deals/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
            all_deals.extend(data.get("results", []))
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return all_deals

    # ── Associations ──────────────────────────────────────────────────────────

    def get_deal_contacts(self, deal_id: str) -> list:
        resp = self._get(f"{HUBSPOT_BASE}/crm/v4/objects/deals/{deal_id}/associations/contacts")
        resp.raise_for_status()
        contacts = []
        for r in resp.json().get("results", []):
            c = self._get(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{r['toObjectId']}",
                params={"properties": ",".join(CONTACT_PROPS)},
            )
            if c.ok:
                contacts.append(c.json().get("properties", {}))
        return contacts

    def get_deal_company(self, deal_id: str) -> dict:
        resp = self._get(f"{HUBSPOT_BASE}/crm/v4/objects/deals/{deal_id}/associations/companies")
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return {}
        r = self._get(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies/{results[0]['toObjectId']}",
            params={"properties": ",".join(COMPANY_PROPS)},
        )
        return r.json().get("properties", {}) if r.ok else {}

    def get_deal_owner(self, owner_id: str) -> dict:
        if not owner_id:
            return _fallback_owner()
        # Try v3 first; fall back to legacy v2 which only needs contacts scope
        for url in [
            f"{HUBSPOT_BASE}/crm/v3/owners/{owner_id}",
            f"{HUBSPOT_BASE}/owners/v2/owners/{owner_id}",
        ]:
            r = self._get(url)
            if r.ok:
                data = r.json()
                print(f"[✓] Owner: {data.get('firstName')} {data.get('lastName')} <{data.get('email')}>")
                return data
        print(f"[!] get_deal_owner failed on both v3 and v2 — using AE_NAME/AE_EMAIL fallback.")
        return _fallback_owner()

    def find_owner_by_name(self, name: str) -> dict | None:
        """Returns the owner whose full name matches (case-insensitive, partial ok)."""
        r = self._get(f"{HUBSPOT_BASE}/crm/v3/owners", params={"limit": 100})
        if not r.ok:
            return None
        name_lower = name.lower()
        for o in r.json().get("results", []):
            full = f"{o.get('firstName', '')} {o.get('lastName', '')}".strip()
            if full.lower() == name_lower or name_lower in full.lower():
                return o
        return None

    def get_deal_by_id(self, deal_id: str) -> dict | None:
        r = self._get(
            f"{HUBSPOT_BASE}/crm/v3/objects/deals/{deal_id}",
            params={"properties": ",".join(DEAL_PROPS)},
        )
        return r.json() if r.ok else None

    def get_all_owners(self) -> dict:
        """Returns {owner_id: full_name} for all HubSpot owners in one API call."""
        r = self._get(f"{HUBSPOT_BASE}/crm/v3/owners", params={"limit": 100})
        if not r.ok:
            print(f"[!] get_all_owners failed: {r.status_code} {r.text[:200]}")
            print("[!] Make sure the HubSpot token has 'crm.objects.owners.read' scope.")
            return {}
        result = {}
        for o in r.json().get("results", []):
            name = f"{o.get('firstName') or ''} {o.get('lastName') or ''}".strip()
            result[str(o["id"])] = name or o.get("email", "")
        print(f"[✓] Loaded {len(result)} owner(s).")
        return result

    def get_deal_notes(self, deal_id: str) -> list:
        resp = self._get(f"{HUBSPOT_BASE}/crm/v4/objects/deals/{deal_id}/associations/notes")
        resp.raise_for_status()
        note_ids = [r["toObjectId"] for r in resp.json().get("results", [])]
        if not note_ids:
            return []

        # Batch read all notes in a single API call instead of N sequential calls
        batch = self._post(
            f"{HUBSPOT_BASE}/crm/v3/objects/notes/batch/read",
            json={
                "properties": ["hs_note_body", "hs_timestamp"],
                "inputs": [{"id": str(nid)} for nid in note_ids],
            },
        )

        # Fallback to sequential reads if batch API fails
        if not batch.ok:
            print(f"[!] Batch notes failed ({batch.status_code}), falling back to sequential reads.")
            notes = []
            for nid in note_ids:
                n = self._get(
                    f"{HUBSPOT_BASE}/crm/v3/objects/notes/{nid}",
                    params={"properties": "hs_note_body,hs_timestamp"},
                )
                if n.ok:
                    props = n.json().get("properties", {})
                    body  = (props.get("hs_note_body") or "").strip()
                    if body:
                        notes.append({"id": str(nid), "body": body, "timestamp": props.get("hs_timestamp")})
            notes.sort(key=lambda n: n.get("timestamp") or "", reverse=True)
            return notes

        notes = []
        for result in batch.json().get("results", []):
            props = result.get("properties", {})
            body  = (props.get("hs_note_body") or "").strip()
            if body:
                notes.append({
                    "id":        result["id"],
                    "body":      body,
                    "timestamp": props.get("hs_timestamp"),
                })
        notes.sort(key=lambda n: n.get("timestamp") or "", reverse=True)
        return notes

    def get_full_context(self, deal: dict) -> dict:
        did = deal["id"]
        return {
            "deal":     deal.get("properties", {}),
            "contacts": self.get_deal_contacts(did),
            "company":  self.get_deal_company(did),
            "owner":    self.get_deal_owner(deal.get("properties", {}).get("hubspot_owner_id", "")),
            "notes":    self.get_deal_notes(did),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

PIPELINE_IDS = {
    "partners distribution": "11834984",
}

def _build_filter(filter_type: str, filter_value: str) -> dict:
    if filter_type == "owner":
        return {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(filter_value)}
    if filter_type == "market":
        return {"propertyName": "country_qobra_samba", "operator": "EQ", "value": str(filter_value)}
    if filter_type == "provenance":
        pipeline_id = PIPELINE_IDS.get(filter_value.lower(), filter_value)
        return {"propertyName": "pipeline", "operator": "EQ", "value": pipeline_id}
    raise ValueError(f"filter_type desconocido: '{filter_type}'. Usa 'owner', 'market' o 'provenance'.")

def _date_to_ms(d: date) -> int:
    dt = datetime.datetime.combine(d, datetime.time.min)
    return int(calendar.timegm(dt.timetuple())) * 1000
