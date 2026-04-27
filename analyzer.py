import os
import re
import requests

# ── Azure AI Foundry — config from env ───────────────────────────────────────
_AZURE_API_VER = "2025-01-01-preview"


def _call(prompt: str, max_tokens: int = 4000) -> str:
    raw_endpoint = os.environ["AZURE_ANTHROPIC_ENDPOINT"].rstrip("/")
    model        = os.environ["AZURE_ANTHROPIC_MODEL"]
    api_key      = os.environ["AZURE_ANTHROPIC_API_KEY"]

    # Strip /anthropic suffix if already in endpoint to avoid duplication
    base = raw_endpoint[:-len("/anthropic")] if raw_endpoint.endswith("/anthropic") else raw_endpoint

    resp = requests.post(
        f"{base}/anthropic/v1/messages?api-version={_AZURE_API_VER}",
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

STEP 2 — WRITE THE EMAIL following the mandatory guardrails below:

  LANGUAGE RULE: Write in the language of the prospect's country.
    France / Belgium → French | Spain → Spanish | Portugal → Portuguese | Germany → German | Italy → Italian | Default → French

  LENGTH RULE: Exactly 4 sentences. Not 3, not 5. Every word that can be cut must be cut.

  MANDATORY STRUCTURE — one sentence per line, in this exact order:

    SENTENCE 1 — Logistical confirmation:
      Greet by first name, introduce the PAE as the one leading the session, confirm day and time.
      Template: "Hola [first name], soy [PAE name] y lideraré nuestra sesión de [day] a las [time]."
      ✅ GOOD (FR): "Bonjour [Prénom], je suis [PAE] et j'animerai notre session de demain à [heure]."

    SENTENCE 2 — Context validation (MANDATORY: employee count + industry):
      Show you've done your homework. Use the exact headcount and industry. Be precise — "42 collaborateurs" beats "votre équipe".
      Template: "J'ai analysé votre situation chez [Company] — [N] collaborateurs dans le secteur [Industry]."
      ✅ GOOD: "J'ai préparé notre session en tenant compte de vos 180 collaborateurs répartis sur 3 entités dans le secteur de la construction."
      ❌ BAD: "J'ai bien pris note de votre contexte." (too vague — use the actual numbers)

    SENTENCE 3 — Personalised value proposition (the GOLD signal goes here):
      State directly how Factorial will solve THEIR specific pain. Name the tool, the frustration, or the exact number.
      Focus on outcome, not feature. Never say "Factorial est une solution complète."
      ✅ GOOD: "J'ai configuré la session pour vous montrer concrètement comment éliminer la double-saisie entre Nibelis et votre ATS."
      ✅ GOOD: "Nous nous concentrerons sur la suppression des exports Excel manuels qui vous coûtent plusieurs heures chaque fin de mois."
      ❌ BAD: "Nous verrons comment Factorial peut répondre à vos besoins RH."

    SENTENCE 4 — Low-friction close:
      Tell them where to find the meeting link. Explicitly say no reply needed. No call to action, no questions.
      ✅ GOOD: "Vous trouverez le lien dans l'invitation ; aucune confirmation de votre part n'est nécessaire."
      ❌ BAD: "N'hésitez pas à me contacter si vous avez des questions."
      ❌ BAD: "Pouvez-vous confirmer votre présence ?"

  SIGNATURE: {owner_name} / Account Executive — Factorial
  (If a meeting link is available in the notes, include it. Otherwise omit.)

  ABSOLUTE PROHIBITIONS:
    • Never mention the SDR, a previous call with someone else, or any internal handoff
    • Never ask for confirmation of receipt or attendance
    • Never exceed 4 sentences in the body
    • Never use generic phrases: "optimiser vos processus", "solution complète", "n'hésitez pas"

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
