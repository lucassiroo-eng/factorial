import os
import re
import datetime
from groq import Groq

_GROQ_MODEL = "llama-3.3-70b-versatile"


def _call(prompt: str, max_tokens: int = 4000) -> str:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    chat = client.chat.completions.create(
        model=_GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
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


# ── Master prompt ─────────────────────────────────────────────────────────────

_MASTER_PROMPT = """You are a top-performing B2B SaaS Account Executive at Factorial (HR software). Your task: write a short pre-demo confirmation email that proves you actually understood the prospect's problem.

━━━ INPUT DATA ━━━

NOTES (read every word — these are your raw material):
{notes}

DEAL: {deal_name} | Amount: {amount} | Demo: {meeting_date}
COMPANY: {company_name} | Industry: {company_industry} | Employees: {employees} | Country: {country}
CONTACT: {contact_name} | Title: {contact_title} | Email: {contact_email}
ACCOUNT EXECUTIVE (the sender): {owner_name}

━━━ INSTRUCTIONS ━━━

STEP 1 — EXTRACT SIGNALS FROM THE NOTES:
Find the most specific, concrete detail you can use:
  GOLD (use this): exact software/tool name (Sage, ADP, Excel, Nibelis…), a quoted frustration, a hard number (headcount, hours lost, # of manual steps), named stakeholder
  SILVER (use if no GOLD): trigger event (funding, reorg, compliance deadline), urgency, recent change
  BRONZE (last resort only): general industry context, company size alone

STEP 2 — WRITE THE EMAIL:

CRITICAL LANGUAGE RULE — you MUST write the entire email in the language of the country. NO EXCEPTIONS. NO MIXING.
  Spain → 100% Spanish
  France / Belgium → 100% French
  Portugal → 100% Portuguese
  Germany → 100% German
  Italy → 100% Italian
  Other → English

CRITICAL NAME RULE — the sender name is: {owner_name}
  Use this exact name in sentence 1 and the signature. If it is "N/A", write "your Account Executive".
  NEVER write "Votre Account Executive" or any placeholder.

CRITICAL TIME RULE — the demo datetime is: {meeting_date}
  Extract the day name and time and write them naturally in the email language.
  NEVER write [hora], [time], [heure] or any placeholder.

EMAIL STRUCTURE — exactly 4 sentences, in this order:

  S1 — LOGISTICS: Greet by first name only, name yourself as the AE leading the session, state the day and time.
    Good example (Spanish): "Hola Jonathan, soy [AE name] y lideraré nuestra sesión del [day] a las [time]."
    Good example (French): "Bonjour Sophie, je suis [AE name] et j'animerai notre session [day] à [time]."

  S2 — CONTEXT VALIDATION: Show you know their situation. MUST include exact employee count + industry.
    Good: "He preparado la sesión teniendo en cuenta vuestros 250 empleados en el sector educativo."
    Bad: "He visto vuestro contexto." (too vague)

  S3 — PERSONALISED VALUE: State exactly how Factorial solves THEIR specific pain using the GOLD signal.
    Name the tool, the frustration, or the exact number. Focus on outcome, not feature.
    Good: "Nos centraremos en eliminar la doble entrada manual entre Sage y vuestro ERP, que os cuesta horas cada cierre de mes."
    Bad: "Veremos cómo Factorial puede optimizar vuestros procesos de RRHH." (generic — FORBIDDEN)

  S4 — LOW-FRICTION CLOSE: Direct them to the meeting link. Explicitly say no reply needed.
    Good: "Encontraréis el enlace en la invitación; no es necesario que confirmáis asistencia."
    Bad: "No dudéis en contactarme si tenéis preguntas." (FORBIDDEN)

ABSOLUTE PROHIBITIONS:
  • NEVER mix languages in a single email
  • NEVER leave placeholders like [hora], [time], [AE name], [heure]
  • NEVER mention the SDR or any internal handoff
  • NEVER ask for confirmation or attendance
  • NEVER exceed 4 sentences in the body
  • NEVER use: "optimizar procesos", "solución completa", "no dudéis en contactar", "suite à notre échange", "comme convenu"
  • NEVER invent facts not present in the notes

SIGNATURE: {owner_name} / Account Executive — Factorial

STEP 3 — INTERNAL RECAP (English, AE eyes only):
  SIGNALS FOUND: every GOLD/SILVER signal with source quote
  HOOK CHOICE: which signal you used and why
  WATCH OUT: 2 risks that could kill the deal
  OPEN DEMO WITH: 2 specific questions to build trust immediately
  SKIP IN DEMO: anything the notes suggest they don't care about

If notes AND all fields are empty/N/A → output only: NO_INFO

Otherwise output EXACTLY (keep the delimiters):

EMAIL_START
Subject: [subject line — must contain a tool name, a number, or their exact stated goal — NEVER generic]

[4-sentence email body]

{owner_name}
Account Executive — Factorial
EMAIL_END

RECAP_START
[internal recap]
RECAP_END"""


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

    prompt = _MASTER_PROMPT.format(
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

    result = _call(prompt, max_tokens=4000)

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
