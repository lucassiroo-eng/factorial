import os
import requests
from datetime import date, timedelta

HUBSPOT_BASE = "https://api.hubapi.com"


class HubSpotClient:
    def __init__(self):
        self.token = os.environ["HUBSPOT_API_KEY"]
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })

    def get_deals_with_meeting_tomorrow(self, meeting_property: str, extra_filters: list) -> list:
        tomorrow = date.today() + timedelta(days=1)
        # HubSpot almacena fechas como timestamps en ms (medianoche UTC)
        day_start = int(tomorrow.strftime("%s")) * 1000  # no disponible en todos los OS
        import calendar, datetime
        dt = datetime.datetime.combine(tomorrow, datetime.time.min)
        day_start_ms = int(calendar.timegm(dt.timetuple())) * 1000
        dt_end = datetime.datetime.combine(tomorrow + timedelta(days=1), datetime.time.min)
        day_end_ms = int(calendar.timegm(dt_end.timetuple())) * 1000

        filters = [
            {"propertyName": meeting_property, "operator": "GTE", "value": str(day_start_ms)},
            {"propertyName": meeting_property, "operator": "LT",  "value": str(day_end_ms)},
        ]
        for f in extra_filters:
            filters.append({
                "propertyName": f["property"],
                "operator": f["operator"],
                "value": str(f["value"]),
            })

        payload = {
            "filterGroups": [{"filters": filters}],
            "properties": ["dealname", "amount", "dealstage", "hubspot_owner_id", meeting_property],
            "limit": 100,
        }
        resp = self.session.post(f"{HUBSPOT_BASE}/crm/v3/objects/deals/search", json=payload)
        resp.raise_for_status()
        return resp.json().get("results", [])

    def get_deal_notes(self, deal_id: str) -> list:
        # Obtener asociaciones deal → notas
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
                body = props.get("hs_note_body", "").strip()
                if body:
                    notes.append({"id": note_id, "body": body, "timestamp": props.get("hs_timestamp")})

        # Ordenar por fecha descendente (más recientes primero)
        notes.sort(key=lambda n: n.get("timestamp") or "", reverse=True)
        return notes
