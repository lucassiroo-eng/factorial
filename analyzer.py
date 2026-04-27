import os
import re
import datetime
from groq import Groq

_GROQ_MODEL = "llama-3.3-70b-versatile"

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


def _format_meeting(ms_value, lang: str = "Spanish") -> str:
    if not ms_value:
        return "N/A"
    try:
        dt = datetime.datetime.fromtimestamp(int(ms_value) / 1000, tz=datetime.timezone.utc)
        days = {
            "Spanish":    ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"],
            "French":     ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"],
            "Portuguese": ["segunda-feira","terça-feira","quarta-feira","quinta-feira","sexta-feira","sábado","domingo"],
            "German":     ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"],
            "Italian":    ["lunedì","martedì","mercoledì","giovedì","venerdì","sabato","domenica"],
            "English":    ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
        }
        day = days.get(lang, days["Spanish"])[dt.weekday()]
        return f"{day} {dt.day:02d}/{dt.month:02d} a las {dt.hour:02d}:{dt.minute:02d}h"
    except Exception:
        return str(ms_value)


# ── LLM call ──────────────────────────────────────────────────────────────────

def _call(system: str, user: str) -> str:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    chat = client.chat.completions.create(
        model=_GROQ_MODEL,
        max_tokens=2000,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return chat.choices[0].message.content.strip()


# ── Prompt builders ───────────────────────────────────────────────────────────

def _build_prompt(*, lang: str, contact_first: str, ae_name: str, meeting: str,
                  company: str, employees: str, industry: str, notes: str) -> tuple[str, str]:

    closing = {
        "Spanish":    "Tienes el enlace en la invitación. Un saludo,",
        "French":     "Le lien est dans l'invitation. À demain,",
        "Portuguese": "O link está no convite. Até amanhã,",
        "German":     "Den Link findest du in der Einladung. Bis morgen,",
        "Italian":    "Il link è nell'invito. A domani,",
        "English":    "The link is in the invite. See you then,",
    }.get(lang, "Tienes el enlace en la invitación. Un saludo,")

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
3. Sentence 1: greet {contact_first} by name, say you are {ae_name}, confirm the exact demo date "{meeting}".
4. Sentence 2: mention the specific pain/need found in the notes above (name the tool, frustration, or situation — never invent).
5. Sentence 3: say you will show specifically how Factorial solves that pain (name the module or outcome).
6. Last sentence (use exactly): "{closing}"
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

    owner_name    = f"{owner.get('firstName','')} {owner.get('lastName','')}".strip() or "N/A"
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
