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

_MASTER_PROMPT = """You are a top-performing B2B SaaS sales expert at Factorial (HR software). You have full access to every piece of intelligence gathered on a prospect who has a demo tomorrow.

Your goal: write the most personalised, human confirmation email possible to maximise demo attendance — then an internal recap explaining your reasoning.

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

STEP 1 — MANDATORY EXTRACTION (do this silently before writing anything):
Read every note and extract:
  A) Current tools / software they use (HR, payroll, time-tracking, spreadsheets, etc.)
  B) Specific pain points or frustrations — use their exact words if mentioned
  C) Their primary goal — WHY they booked this demo
  D) Other people involved in the decision (names + roles)
  E) Timeline or urgency signals (go-live date, project deadline, headcount growth)
  F) Objections, conditions or hesitations mentioned
  G) Concrete numbers: headcount, offices, countries, hours lost, manual tasks, etc.
  H) Any recent event: funding, acquisition, reorg, new HR hire, compliance issue

STEP 2 — WRITE THE EMAIL in French, signed as {owner_name}:
  - Open with {contact_name}'s first name
  - Hook: reference a SPECIFIC situation, tool, or pain point extracted from the notes — do NOT open generically ("suite à notre échange" is forbidden)
  - Weave at least 2-3 concrete details from the notes naturally into the body — show you were listening
  - Value: frame what they'll get from the demo in terms of THEIR specific problem, not generic features
  - Tone: warm, direct, human — like a message from a colleague, not a sales template
  - Length: 5-7 sentences maximum
  - Close: invite them to reply if they want to add topics or reschedule
  - Signature: {owner_name} / Account Executive — Factorial

STEP 3 — INTERNAL RECAP in English (for the AE's eyes only):
  - What you found in the notes (specific signals used)
  - Which angle you chose for the email and why
  - 2 deal risk factors or open questions
  - 1-2 suggested angles or questions to open the demo with

If there is ZERO useful information in the notes AND all properties are N/A, output only: NO_INFO

Otherwise output EXACTLY this format (keep the delimiters):

EMAIL_START
Objet : [subject line that mirrors their specific situation — not generic]

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
