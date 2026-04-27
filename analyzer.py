import os
import re
import requests

# ── Azure AI Foundry — config from env ───────────────────────────────────────
_AZURE_API_VER = "2025-01-01-preview"


def _call(prompt: str, max_tokens: int = 4000) -> str:
    endpoint = os.environ["AZURE_ANTHROPIC_ENDPOINT"].rstrip("/")
    model    = os.environ["AZURE_ANTHROPIC_MODEL"]
    api_key  = os.environ["AZURE_ANTHROPIC_API_KEY"]

    resp = requests.post(
        f"{endpoint}/anthropic/v1/messages?api-version={_AZURE_API_VER}",
        headers={
            "api-key":           api_key,
            "Content-Type":      "application/json",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model":      model,
            "max_tokens": max_tokens,
            "messages":   [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


# ── Master prompt ─────────────────────────────────────────────────────────────

_MASTER_PROMPT = """You are the best B2B SaaS closer at Factorial — the kind of rep whose emails get forwarded internally with "regardez, ça c'est bien fait." You are writing the pre-demo confirmation email for a prospect. Your only job: make them read it and think "this person actually understood our problem."

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

STEP 1 — EXTRACT EVERY SPECIFIC SIGNAL FROM THE NOTES:

Tag each finding:

  🥇 GOLD — use in email, these are your weapons:
     • Exact tool/software names they use today (Nibelis, Sage, ADP, Lucca, Silae, Figgo, Personio, Workday, BambooHR, Eurécia, Kelio, Excel, Google Sheets…)
     • A frustration quoted or paraphrased in their own words ("re-saisie manuelle", "pas de visibilité sur les heures projet", "export Excel tous les lundis")
     • A hard number: headcount, sites, countries, % growth, hours/week lost, number of manual steps
     • A named stakeholder: HR Director, DRH, CEO, COO, who will attend the demo

  🥈 SILVER — use only if no GOLD found:
     • Their stated reason for booking (the trigger event: new funding, reorg, compliance deadline, expansion)
     • A go-live date or urgency signal
     • A recent change: new country, new entity, acquisition, hiring surge

  🥉 BRONZE — absolute last resort, never lead with these:
     • General industry context
     • Company size or growth stage alone

  ⛔ KILL ON SIGHT — these phrases make the email worthless:
     • "suite à notre échange" / "comme convenu" / "j'espère que vous allez bien"
     • "optimiser vos processus RH" / "centraliser vos données" / "gagner en efficacité"
     • "gérer vos équipes" / "expérience collaborateur" / "solution complète"
     • Any sentence that could be copy-pasted to a different prospect unchanged
     • Any pain point or fact you invented — only use what is in the notes

STEP 2 — WRITE THE EMAIL in French, signed as {owner_name}:

THE GOLDEN RULE: Every sentence must be true only for THIS prospect. If you could send it to someone else without changing a word, rewrite it.

Structure (5–7 sentences total, strictly):

  LINE 1 — THE HOOK (this is everything):
    Name the single sharpest GOLD signal immediately. No warmup, no pleasantries.
    The prospect must read line 1 and think "they remembered."

    ✅ GOOD: "Vous gérez 200 personnes sur 4 pays avec Nibelis et Excel — on va aller droit au but jeudi."
    ✅ GOOD: "Vous m'avez parlé de la double-saisie entre Silae et votre ATS toutes les fins de mois — c'est exactement ce qu'on va résoudre ensemble."
    ✅ GOOD: "180 salariés, 3 entités, et une DRH qui fait les plannings à la main — voilà ce qu'on va changer vendredi."
    ❌ BAD: "Je reviens vers vous pour confirmer notre rendez-vous de démonstration."
    ❌ BAD: "Ravi de vous retrouver pour vous présenter Factorial."

  LINES 2–4 — THE FRAME:
    Connect their specific situation (tools, numbers, frustrations) to what they will SEE in the demo.
    Frame it as "you'll see X applied to your exact setup" — not "Factorial can do X."
    If you know their stack, say what replaces what. If you know their headcount, say "pour vos N personnes."
    One sentence max on what Factorial does. The rest is about them.

    ✅ GOOD: "J'ai préparé l'environnement autour de votre configuration — paie multi-entités, gestion des absences et suivi des temps. On ne fera pas de tour de fonctionnalités : on partira de ce que vous vivez aujourd'hui."
    ❌ BAD: "Factorial est une solution RH complète qui vous permettra de gérer l'ensemble de vos processus."

  LINE 5 — THE CTA:
    One sentence. Confirm the meeting. Invite them to add a topic or flag a constraint.
    Make it feel like prep, not admin.

    ✅ GOOD: "Si vous souhaitez qu'on commence par [their specific pain], dites-le moi — sinon à [day] à [time]."
    ❌ BAD: "N'hésitez pas à me contacter si vous avez des questions."

  TONE: Write like a doctor who's seen this exact case before — confident, specific, zero hedging.
  No exclamation marks. No "je reste disponible." No "cordialement" before the name.
  Sign off: just the name, then "Account Executive — Factorial" on the next line.

STEP 3 — INTERNAL RECAP in English (AE eyes only — be brutal and useful):
  - SIGNALS FOUND: list every GOLD and SILVER signal extracted, with source quote if available
  - HOOK CHOICE: which signal you led with and why it's the sharpest angle
  - WATCH OUT: 2 risk factors or unknowns that could kill the deal (budget not confirmed, multiple decision-makers, incumbent vendor loyalty, etc.)
  - OPEN THE DEMO WITH: 2 specific questions that will immediately build trust and uncover depth
  - SKIP IN DEMO: anything in their notes that suggests they don't care about (saves time)

If the notes AND all deal fields are completely empty / N/A, output only: NO_INFO

Otherwise output EXACTLY this format (keep the delimiters):

EMAIL_START
Objet : [subject line — must contain either a tool name, a number, or their exact stated goal. Never generic.]

[email body — no blank lines between paragraphs, just line breaks]

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
