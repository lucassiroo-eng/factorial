import os
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

BANT_CHECK_PROMPT = """Eres un analista de ventas B2B. Analiza las siguientes notas de un deal y determina si contienen un análisis BANT completo o parcial.

BANT = Budget (presupuesto), Authority (autoridad/decisor), Need (necesidad), Timeline (plazo).

Notas del deal:
{notes}

Responde en este formato exacto:
HAS_BANT: true/false
BUDGET: [lo que se menciona o "no mencionado"]
AUTHORITY: [lo que se menciona o "no mencionado"]
NEED: [lo que se menciona o "no mencionado"]
TIMELINE: [lo que se menciona o "no mencionado"]
MISSING: [lista de campos BANT que faltan completamente, separados por coma, o "ninguno"]"""

EMAIL_PROMPT = """Tu es un expert en vente B2B SaaS RH. Tu dois écrire un email de confirmation de démo au nom de {owner_name}, Account Executive chez Factorial.

Contexte du deal (usage interne — ne pas citer directement) :
- Entreprise : {company_name} | Secteur : {industry} | Taille : {employees} collaborateurs
- Décideur : {contact_name} ({contact_title})
- Besoins détectés : {need}
- Autorité : {authority}
- Timeline : {timeline}
- Notes complètes : {notes}

Objectif de l'email : que le prospect se présente à la démo qu'il a déjà bookée demain.

Règles impératives :
- Écrit entièrement en français
- Voix de {owner_name} : chaleureuse, directe, confiante — pas corporate
- N'utilise JAMAIS les infos du BANT de façon littérale ("je sais que vous avez X employés...") — utilise-les pour rendre le message pertinent et personnalisé sans que ça se voie
- L'objet doit donner envie d'ouvrir
- Corps court : 4-5 phrases max. Une phrase d'accroche sur leur situation (sans la nommer), 2-3 lignes sur ce qu'ils vont repartir avec après la démo (résultats, pas features), une phrase de clôture chaleureuse
- Avant la signature, ajoute une phrase courte et naturelle qui donne au prospect trois options sans les nommer explicitement : répondre s'il a des points à couvrir, se réorganiser si l'horaire ne convient plus, ou simplement confirmer sa présence. Le tout en une seule phrase fluide, pas une liste.
- Termine par la signature de {owner_name} avec son titre : Account Executive — Factorial
- Pas de bullet points. Pas de liste de fonctionnalités. Juste du texte fluide et humain."""

RECAP_PROMPT = """Eres un asistente de ventas B2B experto. Basándote en el BANT y las notas del deal, genera un recap conciso para preparar la demo de mañana.

Deal: {deal_name}
Importe: {amount}

BANT detectado:
- Budget: {budget}
- Authority: {authority}
- Need: {need}
- Timeline: {timeline}

Notas completas:
{notes}

Genera un mensaje de preparación para la demo que incluya:
1. **Contexto del cliente** (quién es, qué problema tiene)
2. **Temas a tocar en la demo** (basados en sus necesidades)
3. **Preguntas/problemas que responder** (según el BANT)
4. **Puntos de atención** (objeciones probables, decisor, urgencia)

Sé directo y accionable. Máximo 250 palabras."""


def analyze_bant(notes: list) -> dict:
    if not notes:
        return {"has_bant": False, "budget": "no mencionado", "authority": "no mencionado",
                "need": "no mencionado", "timeline": "no mencionado", "missing": ["Budget", "Authority", "Need", "Timeline"]}

    notes_text = "\n\n---\n\n".join(n["body"] for n in notes)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": BANT_CHECK_PROMPT.format(notes=notes_text)}],
    )
    text = response.content[0].text.strip()

    result = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip().upper()] = val.strip()

    has_bant = result.get("HAS_BANT", "false").lower() == "true"
    missing = [m.strip() for m in result.get("MISSING", "").split(",") if m.strip() and m.strip().lower() != "ninguno"]

    return {
        "has_bant": has_bant,
        "budget": result.get("BUDGET", "no mencionado"),
        "authority": result.get("AUTHORITY", "no mencionado"),
        "need": result.get("NEED", "no mencionado"),
        "timeline": result.get("TIMELINE", "no mencionado"),
        "missing": missing,
    }


def generate_email(context: dict, bant: dict) -> str:
    notes_text = "\n\n---\n\n".join(n["body"] for n in context.get("notes", []))
    owner = context.get("owner", {})
    contact = context.get("contacts", [{}])[0] if context.get("contacts") else {}
    company = context.get("company", {})
    deal = context.get("deal", {})

    owner_name = f"{owner.get('firstName', '')} {owner.get('lastName', '')}".strip() or "Votre Account Executive"
    contact_name = f"{contact.get('firstname', '')} {contact.get('lastname', '')}".strip() or "le prospect"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": EMAIL_PROMPT.format(
                owner_name=owner_name,
                company_name=company.get("name", deal.get("dealname", "")),
                industry=deal.get("industry", company.get("industry", "N/A")),
                employees=company.get("numberofemployees", "N/A"),
                contact_name=contact_name,
                contact_title=contact.get("jobtitle", "N/A"),
                need=bant["need"],
                authority=bant["authority"],
                timeline=bant["timeline"],
                notes=notes_text[:3000],
            )
        }],
    )
    return response.content[0].text.strip()


def generate_recap(deal: dict, notes: list, bant: dict) -> str:
    props = deal.get("properties", {})
    notes_text = "\n\n---\n\n".join(n["body"] for n in notes)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": RECAP_PROMPT.format(
                deal_name=props.get("dealname", "Sin nombre"),
                amount=props.get("amount", "No especificado"),
                budget=bant["budget"],
                authority=bant["authority"],
                need=bant["need"],
                timeline=bant["timeline"],
                notes=notes_text,
            )
        }],
    )
    return response.content[0].text.strip()
