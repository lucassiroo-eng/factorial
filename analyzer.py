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

_MASTER_PROMPT = """Tu es un expert en vente B2B SaaS RH chez Factorial. Tu as accès à toutes les informations disponibles sur un prospect qui a une démo demain.

Ton objectif : générer le meilleur email de confirmation possible pour maximiser la présence à la démo, ET un recap interne expliquant tes choix.

━━━ INFORMATIONS DU DEAL ━━━
Deal : {deal_name}
Montant estimé : {amount}
Secteur : {industry}
Date de démo : {meeting_date}

━━━ ENTREPRISE ━━━
Nom : {company_name}
Secteur : {company_industry}
Employés : {employees}
Pays : {country}

━━━ CONTACT PRINCIPAL ━━━
Nom : {contact_name}
Titre : {contact_title}
Email : {contact_email}

━━━ ACCOUNT EXECUTIVE ━━━
Nom : {owner_name}

━━━ TOUTES LES NOTES DU DEAL ━━━
{notes}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INSTRUCTIONS :

1. Analyse TOUTES les informations ci-dessus — notes, propriétés, contexte — même si elles sont partielles, en emojis, en français, anglais ou espagnol.
2. Extrais les signaux clés : qui décide, quel problème urgent, quel timing, quel budget indicatif, quels outils actuels, quelles objections probables.
3. S'il n'y a AUCUNE information utile (notes vides ET propriétés vides), réponds uniquement avec : NO_INFO

Sinon, génère EXACTEMENT ce format (garde les séparateurs) :

EMAIL_START
Objet : [objet accrocheur]

[corps de l'email en français, 4-5 phrases max, voix de {owner_name}, chaleureux et direct, jamais corporate. Accroche sur leur situation sans la nommer littéralement. Ce qu'ils repartiront avec (résultats, pas features). Une phrase offrant de répondre pour couvrir des points ou se réorganiser si besoin. Signature : {owner_name} / Account Executive — Factorial]
EMAIL_END

RECAP_START
[recap in English, 5-8 lines. Explain: what we know about the prospect, why those specific arguments, 1-2 deal risk points]
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
        notes          = notes_text[:5000],
    )

    result = _call(prompt, max_tokens=1200)

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
