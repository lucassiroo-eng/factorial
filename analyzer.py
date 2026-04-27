import os
import re
import datetime
from groq import Groq

_GROQ_MODEL = "meta-llama/llama-4-maverick-17b-128e-instruct"


_SYSTEM = """You are a top Account Executive at Factorial (HR SaaS). You write short, casual, human pre-demo emails that sound like a real person wrote them — not a template. You follow the rules exactly, never leave placeholders, and never mix languages."""


def _call(system: str, user: str, max_tokens: int = 4000) -> str:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    chat = client.chat.completions.create(
        model=_GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return chat.choices[0].message.content.strip()


def _format_meeting(ms_value) -> str:
    """Convert HubSpot millisecond timestamp to readable date+time."""
    if not ms_value:
        return "N/A"
    try:
        dt = datetime.datetime.fromtimestamp(int(ms_value) / 1000, tz=datetime.timezone.utc)
        return dt.strftime("%A %d/%m/%Y at %H:%M UTC")
    except Exception:
        return str(ms_value)


# ── Prompt ────────────────────────────────────────────────────────────────────

_RULES = """## TASK
Write a casual, human pre-demo email (3-4 sentences) + a short internal recap.

## LANGUAGE — ABSOLUTE RULE
Detect the country and write the ENTIRE email in that language. Zero mixing.
  Spain → Spanish | France/Belgium → French | Portugal → Portuguese | Germany → German | Italy → Italian | other → English

## NAME — ABSOLUTE RULE
Use the Account Executive name given to you in sentence 1 and in the signature.
If it is "N/A" use "tu Account Executive". NEVER leave a placeholder.

## DATE/TIME — ABSOLUTE RULE
The demo datetime is given. Write the day and time naturally in the correct language.
NEVER write [hora], [time], [heure], [day] or any bracket. Fill them in.

## EMAIL STRUCTURE (3-4 sentences, casual and direct)

S1 — Greet by first name, say who you are, confirm day + time.
  Example ES: "Hola Jonathan, soy Lucas y mañana a las 10h lidero nuestra sesión."
  Example FR: "Bonjour Sophie, c'est Lucas, je serai avec toi demain à 10h."

S2 — Show you understand their main pain. Reference the specific need from the notes.
  "Entiendo que en [Empresa] la prioridad ahora mismo es [Need], así que enfocaremos la demo en eso."
  Do NOT pad with headcount or industry if the notes already give a clearer signal.

S3 — Name the specific Factorial module or feature that solves it.
  "Veremos el módulo de [X] para eliminar [frustración concreta]."
  Be specific. If notes mention a tool (Sage, ADP, Excel…), name it.

S4 (optional, only if needed) — Simple closing. Assumes attendance, no confirmation request.
  "Un saludo y hasta mañana." or "À demain !"

## TONE
Casual, warm, direct. Like a smart colleague, not a sales robot.
Short sentences. No filler words. No corporate speak.

## HARD PROHIBITIONS
- NEVER mix languages
- NEVER leave bracket placeholders
- NEVER mention the SDR or any handoff
- NEVER ask for confirmation or reply
- NEVER say: "optimizar procesos", "solución completa", "no dudes en contactar", "n'hésitez pas", "comme convenu"
- NEVER invent facts not in the notes

## SIGNAL PRIORITY (for S2/S3)
GOLD: tool/software name, quoted frustration, hard number, named stakeholder
SILVER: trigger event (funding, reorg, deadline), urgency signal
BRONZE: industry context alone — only if nothing better exists

## OUTPUT — copy format exactly, keep delimiters

If notes AND all fields are empty → output only: NO_INFO

EMAIL_START
Subject: [specific subject — tool name, number, or their exact pain — never generic]

[email body]

[AE name]
Account Executive — Factorial
EMAIL_END

RECAP_START
SIGNALS: [GOLD/SILVER signals found with source quote]
HOOK: [which signal you used and why]
WATCH OUT: [2 deal risks]
OPEN WITH: [2 specific demo-opening questions]
SKIP: [what they probably don't care about]
RECAP_END"""

_USER_TEMPLATE = """## DEAL DATA

NOTES (main source — read carefully):
{notes}

DEAL: {deal_name} | Amount: {amount}
DEMO: {meeting_date}
COMPANY: {company_name} | Industry: {company_industry} | Employees: {employees} | Country: {country}
CONTACT: {contact_name} | Title: {contact_title}
ACCOUNT EXECUTIVE (the sender, use this name): {owner_name}

Now write the email and recap."""


# ── Public functions ──────────────────────────────────────────────────────────

def analyze_and_generate(context: dict) -> tuple[str | None, str | None]:
    """
    Recibe el contexto completo del deal y devuelve (email, recap).
    Retorna (None, None) si no hay suficiente información.
    """
    deal    = context.get("deal", {})
    company = context.get("company", {})
    owner   = context.get("owner", {})
    contact = (context.get("contacts") or [{}])[0]
    notes   = context.get("notes", [])

    notes_text = "\n\n---\n\n".join(_strip_html(n["body"]) for n in notes) if notes else "(sin notas)"

    owner_name = f"{owner.get('firstName','')} {owner.get('lastName','')}".strip() or "N/A"
    print(f"[→] Owner resolved: '{owner_name}' (raw: {owner})")

    user_msg = _USER_TEMPLATE.format(
        deal_name        = deal.get("dealname", "N/A"),
        amount           = deal.get("amount", "N/A"),
        meeting_date     = _format_meeting(deal.get("first_meeting_at")),
        company_name     = company.get("name", "N/A"),
        company_industry = company.get("industry", "N/A"),
        employees        = company.get("numberofemployees", "N/A"),
        country          = deal.get("country_qobra_samba", company.get("country", "N/A")),
        contact_name     = f"{contact.get('firstname','')} {contact.get('lastname','')}".strip() or "N/A",
        contact_title    = contact.get("jobtitle", "N/A"),
        contact_email    = contact.get("email", "N/A"),
        owner_name       = owner_name,
        notes            = notes_text[:10000],
    )

    result = _call(_RULES, user_msg, max_tokens=4000)

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
