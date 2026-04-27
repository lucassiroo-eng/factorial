import os
import re
import datetime
from groq import Groq

_GROQ_MODEL = "llama-3.3-70b-versatile"


_SYSTEM = """You are a top-performing B2B SaaS Account Executive at Factorial (HR software).
You write pre-demo confirmation emails. You follow every rule exactly. You never leave placeholders unfilled. You never mix languages."""


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

_RULES = """## YOUR TASK
Write a 4-sentence pre-demo confirmation email + an internal recap.

## LANGUAGE — NON-NEGOTIABLE
Write the ENTIRE email in ONE language based on the country:
  Spain → Spanish | France/Belgium → French | Portugal → Portuguese | Germany → German | Italy → Italian | other → English
DO NOT mix languages. A Spanish email must be 100% Spanish — no French words, no English words.

## SENDER NAME — NON-NEGOTIABLE
The Account Executive name is given to you. Use it exactly in sentence 1 and in the signature.
NEVER write "Votre Account Executive", "your AE", or any placeholder. If name is N/A, write "your Account Executive".

## DEMO DATE/TIME — NON-NEGOTIABLE
The demo datetime is given to you. Extract day + time and write them naturally in the email language.
NEVER leave [hora], [time], [heure], [day] or any bracket placeholder in the output.

## EMAIL STRUCTURE — exactly 4 sentences
S1 LOGISTICS — greet by first name, introduce yourself as the AE leading the session, state day and time.
S2 CONTEXT — prove you know their situation: MUST include exact headcount + industry sector.
S3 VALUE — one specific outcome Factorial will deliver for THEIR exact pain (tool name / frustration / hard number from notes). No generic claims.
S4 CLOSE — tell them where the link is; say no reply needed. No questions, no "feel free to contact".

## FORBIDDEN PHRASES (any language)
"optimize your processes", "complete solution", "don't hesitate", "suite à notre échange", "comme convenu",
"n'hésitez pas", "no dudéis", "solución completa", "optimizar procesos", any phrase that could paste to any prospect.

## SIGNAL PRIORITY
Use notes to find: GOLD = software name, quoted frustration, hard number, named stakeholder.
SILVER = trigger event, urgency, recent change. BRONZE = industry context alone (last resort).
NEVER invent a fact not in the notes.

## OUTPUT FORMAT — copy exactly, keep delimiters
If notes AND all fields are empty → output only: NO_INFO

Otherwise:

EMAIL_START
Subject: [must contain a tool name OR a number OR their exact stated goal — never generic]

[S1]
[S2]
[S3]
[S4]

[AE full name]
Account Executive — Factorial
EMAIL_END

RECAP_START
SIGNALS FOUND: [list every GOLD/SILVER signal with quote]
HOOK CHOICE: [which signal and why]
WATCH OUT: [2 deal risks]
OPEN DEMO WITH: [2 specific questions]
SKIP IN DEMO: [what they don't care about]
RECAP_END"""

_USER_TEMPLATE = """## DEAL DATA

NOTES:
{notes}

DEAL: {deal_name} | Amount: {amount}
DEMO DATE/TIME: {meeting_date}
COMPANY: {company_name} | Industry: {company_industry} | Employees: {employees} | Country: {country}
CONTACT: {contact_name} | Title: {contact_title}
ACCOUNT EXECUTIVE (sender): {owner_name}

Write the email and recap now."""


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
