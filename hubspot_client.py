import os
import calendar
import datetime
import requests
from datetime import date, timedelta

HUBSPOT_BASE = "https://api.hubapi.com"

# ── Property names (verificados con discover_properties.py) ───────────────────
DEAL_PROPS = [
    "dealname", "amount", "dealstage", "hubspot_owner_id",
    "first_meeting_at", "industry",
    "country_qobra_samba",
]
CONTACT_PROPS = ["firstname", "lastname", "jobtitle", "email"]
COMPANY_PROPS = ["name", "industry", "numberofemployees"]
# ─────────────────────────────────────────────────────────────────────────────


class HubSpotClient:
    def __init__(self):
        self.token = os.environ["HUBSPOT_API_KEY"]
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })

    # ── Deal search ───────────────────────────────────────────────────────────

    def get_next_future_deal(self, filter_type: str, filter_value: str) -> dict | None:
        """
        Devuelve el deal con first_meeting_at más próximo a hoy (futuro).
        filter_type: "owner" | "market" | "provenance"
        """
        today_ms = str(_date_to_ms(date.today()))

        base_filters = [
            {"propertyName": "first_meeting_at", "operator": "GTE", "value": today_ms},
            {"propertyName": "pipeline", "operator": "EQ", "value": PIPELINE_IDS["partners distribution"]},
            _build_filter(filter_type, filter_value),
        ]

        payload = {
            "filterGroups": [{"filters": base_filters}],
            "properties": DEAL_PROPS,
            "sorts": [{"propertyName": "first_meeting_at", "direction": "ASCENDING"}],
            "limit": 1,
        }
        resp = self.session.post(f"{HUBSPOT_BASE}/crm/v3/objects/deals/search", json=payload)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return results[0] if results else None

    def get_all_future_deals(self, filter_type: str, filter_value: str) -> list:
        """Devuelve todos los deals futuros para el filtro dado, ordenados por fecha."""
        today_ms = str(_date_to_ms(date.today()))

        base_filters = [
            {"propertyName": "first_meeting_at", "operator": "GTE", "value": today_ms},
            {"propertyName": "pipeline", "operator": "EQ", "value": PIPELINE_IDS["partners distribution"]},
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
            resp = self.session.post(f"{HUBSPOT_BASE}/crm/v3/objects/deals/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
            all_deals.extend(data.get("results", []))
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return all_deals

    # ── Associations ──────────────────────────────────────────────────────────

    def get_deal_contacts(self, deal_id: str) -> list:
        resp = self.session.get(f"{HUBSPOT_BASE}/crm/v4/objects/deals/{deal_id}/associations/contacts")
        resp.raise_for_status()
        contacts = []
        for r in resp.json().get("results", []):
            c = self.session.get(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{r['toObjectId']}",
                params={"properties": ",".join(CONTACT_PROPS)},
            )
            if c.ok:
                contacts.append(c.json().get("properties", {}))
        return contacts

    def get_deal_company(self, deal_id: str) -> dict:
        resp = self.session.get(f"{HUBSPOT_BASE}/crm/v4/objects/deals/{deal_id}/associations/companies")
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return {}
        r = self.session.get(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies/{results[0]['toObjectId']}",
            params={"properties": ",".join(COMPANY_PROPS)},
        )
        return r.json().get("properties", {}) if r.ok else {}

    def get_deal_owner(self, owner_id: str) -> dict:
        if not owner_id:
            return {}
        r = self.session.get(f"{HUBSPOT_BASE}/crm/v3/owners/{owner_id}")
        return r.json() if r.ok else {}

    def get_deal_notes(self, deal_id: str) -> list:
        resp = self.session.get(f"{HUBSPOT_BASE}/crm/v4/objects/deals/{deal_id}/associations/notes")
        resp.raise_for_status()
        notes = []
        for r in resp.json().get("results", []):
            n = self.session.get(
                f"{HUBSPOT_BASE}/crm/v3/objects/notes/{r['toObjectId']}",
                params={"properties": "hs_note_body,hs_timestamp"},
            )
            if n.ok:
                props = n.json().get("properties", {})
                body  = (props.get("hs_note_body") or "").strip()
                if body:
                    notes.append({"id": r["toObjectId"], "body": body, "timestamp": props.get("hs_timestamp")})
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
