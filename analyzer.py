import os
import re
import requests

# ── Azure Anthropic client ────────────────────────────────────────────────────
_AZURE_ENDPOINT = os.environ.get("AZURE_ANTHROPIC_ENDPOINT", "https://partners-bizdev-ai.services.ai.azure.com/anthropic")
_AZURE_KEY      = os.environ.get("AZURE_ANTHROPIC_API_KEY", "")
_MODEL          = os.environ.get("AZURE_ANTHROPIC_MODEL", "claude-opus-4-6")
def _call(prompt: str, max_tokens: int = 800) -> str:
    base = _AZURE_ENDPOINT.rstrip("/")
    body = {
        "model": _MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    # Base sin el /anthropic sufijo para intentar rutas alternativas
    base_root = _AZURE_ENDPOINT.rstrip("/").replace("/anthropic", "")

    # Combinaciones (url, headers, params, body_override) a intentar en orden
    attempts = [
        # 1-4: Anthropic native format con distintos headers
        (f"{base}/v1/messages",
         {"api-key": _AZURE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}, {}, None),
        (f"{base}/v1/messages",
         {"api-key": _AZURE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
         {"api-version": "2024-10-01-preview"}, None),
        (f"{base}/v1/messages",
         {"Ocp-Apim-Subscription-Key": _AZURE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}, {}, None),
        (f"{base}/v1/messages",
         {"Authorization": f"Bearer {_AZURE_KEY}", "anthropic-version": "2023-06-01", "content-type": "application/json"}, {}, None),
        # 5. Azure AI Inference format (chat/completions)
        (f"{base_root}/models/{_MODEL}/chat/completions",
         {"api-key": _AZURE_KEY, "content-type": "application/json"},
         {"api-version": "2024-05-01-preview"},
         {"model": _MODEL, "max_tokens": max_tokens,
          "messages": [{"role": "user", "content": prompt}]}),
        # 6. Deployment en la ruta con formato Anthropic
        (f"{base}/deployments/{_MODEL}/v1/messages",
         {"api-key": _AZURE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}, {}, None),
    ]

    last_error = None
    for url, headers, params, body_override in attempts:
        actual_body = body_override or body
        resp = requests.post(url, headers=headers, params=params, json=actual_body, timeout=60)
        print(f"  [debug] {url.split('services.ai.azure.com')[1][:40]} | {list(headers.keys())[0]} → {resp.status_code}")
        if resp.ok:
            data = resp.json()
            # Anthropic format
            if "content" in data:
                return data["content"][0]["text"].strip()
            # OpenAI/Inference format
            if "choices" in data:
                return data["choices"][0]["message"]["content"].strip()
        last_error = f"[{resp.status_code}] {resp.text[:200]}"

    raise RuntimeError(f"Azure Anthropic — todos los formatos fallaron. Último error: {last_error}")


# ── Prompts ───────────────────────────────────────────────────────────────────

_BANT_PROMPT = """Tu es un analyste commercial B2B. Analyse les notes suivantes d'un deal et détermine si elles contiennent un BANT (Budget, Authority, Need, Timeline).

Notes :
{notes}

Réponds exactement dans ce format :
HAS_BANT: true/false
BUDGET: [ce qui est mentionné ou "non mentionné"]
AUTHORITY: [ce qui est mentionné ou "non mentionné"]
NEED: [ce qui est mentionné ou "non mentionné"]
TIMELINE: [ce qui est mentionné ou "non mentionné"]
MISSING: [champs BANT absents séparés par virgule, ou "aucun"]"""


_EMAIL_PROMPT = """Tu es un expert en vente B2B SaaS RH. Écris un email de confirmation de démo au nom de {owner_name}, Account Executive chez Factorial.

Contexte du deal (usage interne uniquement — ne jamais citer directement) :
- Entreprise : {company_name} | Secteur : {industry} | Taille : {employees} collaborateurs
- Décideur : {contact_name} ({contact_title})
- Besoins détectés : {need}
- Autorité : {authority}
- Timeline : {timeline}
- Notes : {notes}

Objectif : que le prospect se présente à la démo qu'il a déjà bookée demain.

Règles :
- Entièrement en français
- Voix de {owner_name} : chaleureuse, directe, confiante — pas corporate
- N'utilise JAMAIS le BANT de façon littérale ("je sais que vous avez X employés...")
- Objet accrocheur sur une ligne, préfixé par "Objet : "
- Corps : 4-5 phrases max. Accroche sur leur situation (sans la nommer), ce qu'ils repartiront avec après la démo (résultats, pas features), clôture chaleureuse
- Avant la signature : une phrase naturelle qui offre de répondre pour couvrir des points supplémentaires, de se réorganiser si l'horaire ne convient plus
- Signature : {owner_name} / Account Executive — Factorial
- Pas de bullet points, pas de liste de features. Texte fluide et humain."""


_RECAP_PROMPT = """Tu es un assistant commercial. Explique en quelques lignes POURQUOI les arguments de cet email ont été choisis pour ce prospect spécifique.

Email envoyé :
{email}

Contexte BANT :
- Budget : {budget}
- Authority : {authority}
- Need : {need}
- Timeline : {timeline}

Entreprise : {company_name} | {industry} | {employees} collaborateurs
Décideur : {contact_name} ({contact_title})

Rédige un recap court (5-8 lignes max) qui explique :
1. Ce qu'on sait de ce prospect (sans répéter les données brutes)
2. Pourquoi ces arguments spécifiques ont été choisis
3. Le ou les points de risque à surveiller pour ce deal

En español. Directo y accionable."""


# ── Public functions ──────────────────────────────────────────────────────────

def analyze_bant(notes: list) -> dict:
    empty = {"has_bant": False, "budget": "non mentionné", "authority": "non mentionné",
             "need": "non mentionné", "timeline": "non mentionné",
             "missing": ["Budget", "Authority", "Need", "Timeline"]}
    if not notes:
        return empty

    notes_text = "\n\n---\n\n".join(_strip_html(n["body"]) for n in notes)
    text = _call(_BANT_PROMPT.format(notes=notes_text[:4000]), max_tokens=400)

    result = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip().upper()] = v.strip()

    has_bant = result.get("HAS_BANT", "false").lower() == "true"
    missing  = [m.strip() for m in result.get("MISSING", "").split(",")
                if m.strip() and m.strip().lower() != "aucun"]
    return {
        "has_bant":  has_bant,
        "budget":    result.get("BUDGET",    "non mentionné"),
        "authority": result.get("AUTHORITY", "non mentionné"),
        "need":      result.get("NEED",      "non mentionné"),
        "timeline":  result.get("TIMELINE",  "non mentionné"),
        "missing":   missing,
    }


def generate_email(context: dict, bant: dict) -> str:
    owner   = context.get("owner", {})
    contact = (context.get("contacts") or [{}])[0]
    company = context.get("company", {})
    deal    = context.get("deal", {})
    notes_text = "\n\n---\n\n".join(_strip_html(n["body"]) for n in context.get("notes", []))

    return _call(_EMAIL_PROMPT.format(
        owner_name   = f"{owner.get('firstName','')} {owner.get('lastName','')}".strip() or "Votre Account Executive",
        company_name = company.get("name") or deal.get("dealname", ""),
        industry     = deal.get("industry") or company.get("industry", "N/A"),
        employees    = company.get("numberofemployees", "N/A"),
        contact_name = f"{contact.get('firstname','')} {contact.get('lastname','')}".strip() or "le prospect",
        contact_title= contact.get("jobtitle", "N/A"),
        need         = bant["need"],
        authority    = bant["authority"],
        timeline     = bant["timeline"],
        notes        = notes_text[:3000],
    ), max_tokens=600)


def generate_recap(context: dict, bant: dict, email: str) -> str:
    contact = (context.get("contacts") or [{}])[0]
    company = context.get("company", {})
    deal    = context.get("deal", {})

    return _call(_RECAP_PROMPT.format(
        email        = email,
        budget       = bant["budget"],
        authority    = bant["authority"],
        need         = bant["need"],
        timeline     = bant["timeline"],
        company_name = company.get("name") or deal.get("dealname", ""),
        industry     = deal.get("industry") or company.get("industry", "N/A"),
        employees    = company.get("numberofemployees", "N/A"),
        contact_name = f"{contact.get('firstname','')} {contact.get('lastname','')}".strip() or "le prospect",
        contact_title= contact.get("jobtitle", "N/A"),
    ), max_tokens=400)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()
