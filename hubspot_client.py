import os
import calendar
import datetime
import requests
from datetime import date, timedelta

HUBSPOT_BASE = "https://api.hubapi.com"

# ── Property names ────────────────────────────────────────────────────────────
# Verificados con discover_properties.py — cambiar aquí si difieren en tu portal
DEAL_PROPS = [
    "dealname",
    "amount",
    "dealstage",
    "hubspot_owner_id",
    "industry",           # ← pendiente verificar API name
    "first_meeting_at",   # ← pendiente verificar API name
]

CONTACT_PROPS = [
    "firstname",
    "lastname",
    "jobtitle",
    "email",
]

COMPANY_PROPS = [
    "name",
    "industry",           # ← pendiente verificar API name
    "numberofemployees",
]
# ─────────────────────────────────────────────────────────────────────────────


class HubSpotClient:
    def __init__(self):
        self.token = os.environ["HUBSPOT_API_KEY"]
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })

    # ── Deals ─────────────────────────────────────────────────────────────────

    def get_deals_with_meeting_in_range(self, meeting_property: str, from_date: date, to_date: date, extra_filters: list) -> list:
        start_ms = _date_to_ms(from_date)
        end_ms   = _date_to_ms(to_date)

        filters = [
            {"propertyName": meeting_property, "operator": "GTE", "value": str(start_ms)},
            {"propertyName": meeting_property, "operator": "LT",  "value": str(end_ms)},
        ]
        for f in extra_filters:
            filters.append({
                "propertyName": f["property"],
                "operator":     f["operator"],
                "value":        str(f["value"]),
            })

        payload = {
            "filterGroups": [{"filters": filters}],
            "properties": DEAL_PROPS,
            "limit": 100,
        }
        resp = self.session.post(f"{HUBSPOT_BASE}/crm/v3/objects/deals/search", json=payload)
        resp.raise_for_status()
        return resp.json().get("results", [])

    def get_deals_with_meeting_tomorrow(self, meeting_property: str, extra_filters: list) -> list:
        tomorrow = date.today() + timedelta(days=1)
        return self.get_deals_with_meeting_in_range(meeting_property, tomorrow, tomorrow + timedelta(days=1), extra_filters)

    # ── Contacts & companies ──────────────────────────────────────────────────

    def get_deal_contacts(self, deal_id: str) -> list:
        resp = self.session.get(
            f"{HUBSPOT_BASE}/crm/v4/objects/deals/{deal_id}/associations/contacts"
        )
        resp.raise_for_status()
        contact_ids = [r["toObjectId"] for r in resp.json().get("results", [])]

        contacts = []
        for cid in contact_ids:
            r = self.session.get(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{cid}",
                params={"properties": ",".join(CONTACT_PROPS)},
            )
            if r.ok:
                contacts.append(r.json().get("properties", {}))
        return contacts

    def get_deal_company(self, deal_id: str) -> dict:
        resp = self.session.get(
            f"{HUBSPOT_BASE}/crm/v4/objects/deals/{deal_id}/associations/companies"
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return {}

        company_id = results[0]["toObjectId"]
        r = self.session.get(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies/{company_id}",
            params={"properties": ",".join(COMPANY_PROPS)},
        )
        return r.json().get("properties", {}) if r.ok else {}

    def get_deal_owner(self, owner_id: str) -> dict:
        if not owner_id:
            return {}
        r = self.session.get(f"{HUBSPOT_BASE}/crm/v3/owners/{owner_id}")
        return r.json() if r.ok else {}

    # ── Notes ─────────────────────────────────────────────────────────────────

    def get_deal_notes(self, deal_id: str) -> list:
        resp = self.session.get(
            f"{HUBSPOT_BASE}/crm/v4/objects/deals/{deal_id}/associations/notes"
        )
        resp.raise_for_status()
        note_ids = [r["toObjectId"] for r in resp.json().get("results", [])]

        notes = []
        for note_id in note_ids:
            r = self.session.get(
                f"{HUBSPOT_BASE}/crm/v3/objects/notes/{note_id}",
                params={"properties": "hs_note_body,hs_timestamp"},
            )
            if r.ok:
                props = r.json().get("properties", {})
                body  = props.get("hs_note_body", "").strip()
                if body:
                    notes.append({
                        "id":        note_id,
                        "body":      body,
                        "timestamp": props.get("hs_timestamp"),
                    })

        notes.sort(key=lambda n: n.get("timestamp") or "", reverse=True)
        return notes

    # ── Full deal context (used by analyzer) ──────────────────────────────────

    def get_full_deal_context(self, deal: dict) -> dict:
        deal_id = deal["id"]
        return {
            "deal":     deal.get("properties", {}),
            "contacts": self.get_deal_contacts(deal_id),
            "company":  self.get_deal_company(deal_id),
            "owner":    self.get_deal_owner(deal.get("properties", {}).get("hubspot_owner_id")),
            "notes":    self.get_deal_notes(deal_id),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _date_to_ms(d: date) -> int:
    dt = datetime.datetime.combine(d, datetime.time.min)
    return int(calendar.timegm(dt.timetuple())) * 1000
