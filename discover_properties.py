"""
Corre este script una vez con tu HubSpot token para ver los nombres
reales (API names) de las properties de deals, contactos y empresas.

Uso:
    HUBSPOT_API_KEY=pat-xxx python discover_properties.py
"""
import os
import requests

TOKEN = os.environ["HUBSPOT_API_KEY"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
BASE = "https://api.hubapi.com"

OBJECTS = {
    "deals":    "/crm/v3/properties/deals",
    "contacts": "/crm/v3/properties/contacts",
    "companies":"/crm/v3/properties/companies",
}

KEYWORDS = [
    "meeting", "demo", "industry", "budget", "owner",
    "stage", "amount", "timeline", "note", "first",
]

def fetch_and_filter(obj_type: str, path: str):
    resp = requests.get(f"{BASE}{path}", headers=HEADERS)
    resp.raise_for_status()
    props = resp.json().get("results", [])

    print(f"\n{'='*60}")
    print(f"  {obj_type.upper()} — properties relevantes")
    print(f"{'='*60}")

    for p in sorted(props, key=lambda x: x["name"]):
        name  = p["name"]
        label = p.get("label", "")
        ptype = p.get("type", "")
        # Mostrar solo las que matcheen alguna keyword
        combined = (name + label).lower()
        if any(k in combined for k in KEYWORDS):
            print(f"  {label:<40} → API name: {name:<45} [{ptype}]")

    print(f"\n  (Total properties en {obj_type}: {len(props)})")
    print(f"  Para ver todas: añade --all como argumento\n")

if __name__ == "__main__":
    import sys
    show_all = "--all" in sys.argv

    for obj_type, path in OBJECTS.items():
        resp = requests.get(f"{BASE}{path}", headers=HEADERS)
        resp.raise_for_status()
        props = resp.json().get("results", [])

        print(f"\n{'='*60}")
        print(f"  {obj_type.upper()}")
        print(f"{'='*60}")

        for p in sorted(props, key=lambda x: x["name"]):
            name  = p["name"]
            label = p.get("label", "")
            ptype = p.get("type", "")
            combined = (name + label).lower()
            if show_all or any(k in combined for k in KEYWORDS):
                print(f"  {label:<40} → {name:<45} [{ptype}]")
