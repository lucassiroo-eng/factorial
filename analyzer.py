import os
import re
import datetime
import requests

_AZURE_ENDPOINT = "https://partners-bizdev-ai.services.ai.azure.com"
_AZURE_MODEL    = "claude-opus-4-6"
_AZURE_API_VER  = "2025-01-01-preview"

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
    cfg  = _azure_cfg()
    url = f"{_AZURE_ENDPOINT}/anthropic/v1/messages?api-version={_AZURE_API_VER}"
    resp = requests.post(
        url,
        headers={
            "api-key":           os.environ["AZURE_CONFIG"].strip(),
            "Content-Type":      "application/json",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model":      _AZURE_MODEL,
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

    closing = {
        "Spanish":    "¡Hasta mañana!",
        "French":     "À demain !",
        "Portuguese": "Até amanhã!",
        "German":     "Bis morgen!",
        "Italian":    "A domani!",
        "English":    "See you then!",
    }.get(lang, "¡Hasta mañana!")

    system = f"""You are {ae_name}, an Account Executive at Factorial (HR software).
You are writing a pre-demo email to {contact_first}.
LANGUAGE RULE: Write 100% in {lang}. Every single word must be in {lang}. No exceptions."""

    user = f"""Write a pre-demo confirmation email in {lang}.

DATA:
- Contact first name: {contact_first}
- Your name (AE): {ae_name}
- Demo date/time: {meeting}
- Company: {company} | {employees} employees | {industry}
- Notes from sales calls:
{notes}

EMAIL RULES:
1. Exactly 3-4 short sentences.
2. Every word in {lang} — absolutely no mixing.
3. Sentence 1: greet {contact_first} by name, introduce yourself as "{ae_name}, Account Executive at Factorial", confirm the exact demo date "{meeting}".
4. Sentence 2: acknowledge their pain with empathy first, then name the specific signal (software, frustration, hard number). Example: "Je sais que gérer X manuellement avec [outil] vous coûte du temps — c'est exactement ce qu'on va adresser." Show you understand, not just that you read their file.
5. Sentence 3: name the exact Factorial module or outcome that fixes that pain. "gestion RH" is forbidden — say "module Absences", "module Temps de travail", "automatiser les contrats", etc.
6. Add a blank line between each sentence for readability.
7. End with (use exactly): "{closing}"
8. Then the link sentence: "Le lien / El enlace / Der Link is dans l'invitation / en la invitación / in der Einladung."
7. FORBIDDEN: "optimizar procesos", "solución completa", generic phrases, asking questions, mentioning SDR.

OUTPUT FORMAT (keep delimiters, no extra text outside them):

EMAIL_START
[subject line in {lang} — mention a specific tool/pain/number, never generic]

[sentence 1]

[sentence 2]

[sentence 3]

[sentence 4 — use exactly: "{closing}"]

{ae_name}
Account Executive — Factorial
EMAIL_END

RECAP_START
PAIN: [exact quote or paraphrase from notes]
HOOK: [why this angle]
RISKS: [2 things that could kill the deal]
OPEN WITH: [2 demo-opening questions]
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
