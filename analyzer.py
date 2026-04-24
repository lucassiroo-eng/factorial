import os
import re
from groq import Groq

# ── Groq client ───────────────────────────────────────────────────────────────
_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
_MODEL  = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def _call(prompt: str, max_tokens: int = 1200) -> str:
    response = _client.chat.completions.create(
        model=_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


# ── Master prompt ─────────────────────────────────────────────────────────────

_MASTER_PROMPT = """You are a top-performing B2B SaaS sales rep at Factorial (HR software). A prospect has a demo coming up. Your job: write the pre-demo confirmation email that makes them think "wow, this person actually listened."

━━━ NOTES — READ EVERY WORD ━━━
{notes}

━━━ DEAL ━━━
Name: {deal_name} | Amount: {amount} | Industry: {industry} | Demo: {meeting_date}

━━━ COMPANY ━━━
{company_name} · {company_industry} · {employees} employees · {country}

━━━ CONTACT ━━━
{contact_name} · {contact_title} · {contact_email}

━━━ ACCOUNT EXECUTIVE ━━━
{owner_name}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — MINE THE NOTES FOR SPECIFIC SIGNALS (do this before writing):

Scan every note and tag each finding by tier:

  🥇 GOLD (must use in email if found):
     • Named tools or software they currently use — exact product names (e.g. "Nibelis", "Sage", "ADP", "Excel", "Lucca", "Personio", "Workday", "Google Sheets for absences")
     • A specific frustration they described in their own words (e.g. "re-saisie manuelle des congés", "no visibility on hours per project")
     • A concrete number: headcount, offices, countries, % growth, hours/week lost, manual tasks count
     • A named person involved (HR Director name, CEO name, decision-maker)

  🥈 SILVER (use if no GOLD available):
     • Their primary goal or reason for the demo (WHY they booked it)
     • A deadline, go-live date, or urgency signal
     • A recent event: funding round, reorg, new hire, compliance issue, expansion to new country

  🥉 BRONZE (last resort only — do NOT lead with these):
     • General industry context
     • Company size / growth stage

  ⛔ FORBIDDEN — never use as hook or main angle:
     • "difficulty managing people / teams"
     • "HR processes are time-consuming"
     • "streamline your HR"
     • "improve employee experience"
     • "suite à notre échange" or any generic call-back opener
     • Any pain point you invented — only use what is explicitly in the notes

STEP 2 — WRITE THE EMAIL in French, signed as {owner_name}:
  - Greeting: {contact_name}'s first name only
  - Hook (sentence 1): lead with your single best GOLD signal. If it's a tool name, name it. If it's a specific frustration, echo it back. Make it clear you were paying attention.
  - Body (2-4 sentences): weave in 2-3 more specific details naturally — tools, numbers, context. Frame what the demo will cover in terms of THEIR exact situation, not generic features.
  - CTA: one clear sentence confirming the meeting and inviting them to add topics or reschedule.
  - Tone: direct, warm, human — like a colleague following up, not a sales template. No filler phrases.
  - Length: 5-7 sentences total, no more.
  - Signature: {owner_name} / Account Executive — Factorial

STEP 3 — INTERNAL RECAP in English (AE eyes only):
  - GOLD/SILVER signals found in notes (list them)
  - Angle chosen for the email and why it's the strongest hook
  - 2 open questions or risk factors for the deal
  - 1-2 sharp questions to open the demo with

If the notes AND all deal fields are completely empty / N/A, output only: NO_INFO

Otherwise output EXACTLY this format (keep the delimiters):

EMAIL_START
Objet : [subject line that names their specific situation — a tool, a number, or their exact goal]

[email body]

{owner_name}
Account Executive — Factorial
EMAIL_END

RECAP_START
[internal recap in English]
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

    prompt = _MASTER_PROMPT.format(
        deal_name      = deal.get("dealname", "N/A"),
        amount         = deal.get("amount", "N/A"),
        industry       = deal.get("industry", "N/A"),
        meeting_date   = deal.get("first_meeting_at", "N/A"),
        company_name   = company.get("name", "N/A"),
        company_industry = company.get("industry", "N/A"),
        employees      = company.get("numberofemployees", "N/A"),
        country        = deal.get("country_qobra_samba", company.get("country", "N/A")),
        contact_name   = f"{contact.get('firstname','')} {contact.get('lastname','')}".strip() or "N/A",
        contact_title  = contact.get("jobtitle", "N/A"),
        contact_email  = contact.get("email", "N/A"),
        owner_name     = f"{owner.get('firstName','')} {owner.get('lastName','')}".strip() or "Votre Account Executive",
        notes          = notes_text[:10000],
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
