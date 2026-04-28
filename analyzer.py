import os
import re
import datetime
import requests

def _azure_cfg() -> tuple[str, str, str]:
    """Parse AZURE_CONFIG secret: 'endpoint|model|key'"""
    raw = os.environ["AZURE_CONFIG"].strip()
    parts = raw.split("|")
    if len(parts) != 3:
        raise ValueError(f"AZURE_CONFIG must be 'endpoint|model|key', got {len(parts)} parts")
    endpoint, model, key = [p.strip() for p in parts]
    # Ensure base URL ends at /v1
    base = endpoint.rstrip("/")
    if not base.endswith("/v1"):
        base = base.rstrip("/anthropic").rstrip("/") + "/anthropic/v1"
    return base, model, key

# ── Language detection — done in Python, never delegated to the model ─────────

_COUNTRY_LANG = {
    # Spanish
    "spain": "Spanish", "españa": "Spanish", "es": "Spanish",
    # French
    "france": "French", "francia": "French", "fr": "French",
    "belgium": "French", "bélgica": "French", "belgique": "French", "be": "French",
    # Portuguese
    "portugal": "Portuguese", "pt": "Portuguese",
    # German
    "germany": "German", "alemania": "German", "deutschland": "German", "de": "German",
    # Italian
    "italy": "Italian", "italia": "Italian", "it": "Italian",
    # English fallback
    "united kingdom": "English", "uk": "English",
    "united states": "English", "us": "English",
}

def _detect_language(country: str) -> str:
    return _COUNTRY_LANG.get((country or "").lower().strip(), "Spanish")


def _format_meeting(raw, lang: str = "Spanish") -> str:
    if not raw:
        return "N/A"
    days = {
        "Spanish":    ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"],
        "French":     ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"],
        "Portuguese": ["segunda-feira","terça-feira","quarta-feira","quinta-feira","sexta-feira","sábado","domingo"],
        "German":     ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"],
        "Italian":    ["lunedì","martedì","mercoledì","giovedì","venerdì","sabato","domenica"],
        "English":    ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
    }
    try:
        v = str(raw).strip()
        # Millisecond timestamp (13 digits)
        if v.isdigit() and len(v) >= 12:
            dt = datetime.datetime.fromtimestamp(int(v) / 1000, tz=datetime.timezone.utc)
        # ISO date "2026-04-28" or datetime "2026-04-28T10:00:00Z"
        else:
            dt = datetime.datetime.fromisoformat(v.replace("Z", "+00:00").split("T")[0])
        day = days.get(lang, days["Spanish"])[dt.weekday()]
        time_str = f" à {dt.hour:02d}h{dt.minute:02d}" if dt.hour else ""
        return f"{day} {dt.day:02d}/{dt.month:02d}{time_str}"
    except Exception:
        return str(raw)


# ── LLM call ──────────────────────────────────────────────────────────────────

def _call(system: str, user: str) -> str:
    endpoint, model, key = _azure_cfg()
    # endpoint already ends with /anthropic/v1 — strip back to base for URL construction
    base = endpoint.replace("/anthropic/v1", "").replace("/anthropic", "").rstrip("/")
    url  = f"{base}/anthropic/v1/messages?api-version=2025-01-01-preview"
    resp = requests.post(
        url,
        headers={
            "Authorization":     f"Bearer {key}",
            "Content-Type":      "application/json",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model":      model,
            "max_tokens": 2000,
            "system":     system,
            "messages":   [{"role": "user", "content": user}],
        },
        timeout=120,
    )
    if not resp.ok:
        print(f"[!] Azure {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


# ── Prompt builders ───────────────────────────────────────────────────────────

def _build_prompt(*, lang: str, contact_first: str, ae_name: str, meeting: str,
                  company: str, employees: str, industry: str, notes: str) -> tuple[str, str]:

    system = f"""You are {ae_name}, an Account Executive at Factorial (HR software).
Write entirely in {lang}. Not a single word in any other language."""

    user = f"""Write a short pre-demo email to {contact_first} before our demo on {meeting}.

Context:
- Company: {company} | {employees} employees | {industry}
- AE sending this: {ae_name}
- Notes from sales calls:
{notes}

Guidelines (not rigid rules — use your judgement):
- 3-4 sentences, professional but warm — you are a trusted consultant, not a salesperson
- From the notes, extract only PAIN POINTS, frustrations, and tool names — never use company names, people names or specific references from notes, they may belong to other deals
- The company name and contact name come ONLY from the deal data above, never from notes
- Mention a concrete Factorial module or outcome relevant to their pain
- Confident and direct tone — no fluff, no filler phrases
- Short closing, no need to ask for confirmation
- Blank line between each sentence

Then write a brief internal recap.

OUTPUT FORMAT:

EMAIL_START
[subject line — specific to their situation]

[email]

{ae_name}
Account Executive — Factorial
EMAIL_END

RECAP_START
[key signals found, risks, 2 questions to open the demo with]
RECAP_END"""

    return system, user


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_and_generate(context: dict) -> tuple[str | None, str | None]:
    deal    = context.get("deal", {})
    company = context.get("company", {})
    owner   = context.get("owner", {})
    contact = (context.get("contacts") or [{}])[0]
    notes   = context.get("notes", [])

    country = deal.get("country_qobra_samba") or company.get("country") or ""
    lang    = _detect_language(country)
    print(f"[→] Language detected: {lang} (country='{country}')")

    owner_name    = f"{owner.get('firstName','')} {owner.get('lastName','')}".strip() \
                    or os.environ.get("AE_NAME", "").strip() \
                    or "tu Account Executive"
    contact_name  = f"{contact.get('firstname','')} {contact.get('lastname','')}".strip() or "N/A"
    contact_first = contact_name.split()[0] if contact_name != "N/A" else "there"

    notes_text = "\n\n".join(_strip_html(n["body"]) for n in notes) if notes else "(no notes)"
    print(f"[→] Owner: '{owner_name}' | Contact: '{contact_name}' | Notes: {len(notes)}")

    system, user = _build_prompt(
        lang          = lang,
        contact_first = contact_first,
        ae_name       = owner_name,
        meeting       = _format_meeting(deal.get("first_meeting_at"), lang),
        company       = company.get("name", "N/A"),
        employees     = company.get("numberofemployees", "N/A"),
        industry      = company.get("industry") or deal.get("industry") or "N/A",
        notes         = notes_text[:8000],
    )

    print(f"[→] Sending to Claude — company='{company.get('name')}' contact='{contact_name}' notes_len={len(notes_text)}")
    print(f"    Notes preview: {notes_text[:200]}")

    result = _call(system, user)

    if "NO_INFO" in result:
        return None, None

    email = _extract(result, "EMAIL_START", "EMAIL_END")
    recap = _extract(result, "RECAP_START", "RECAP_END")
    return email, recap


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract(text: str, start: str, end: str) -> str:
    try:
        return text.split(start)[1].split(end)[0].strip()
    except IndexError:
        return text.strip()


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()
