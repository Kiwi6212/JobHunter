"""
CV-to-offer matching using Claude Haiku via the Anthropic API.

Sends batches of 10 offers in a single prompt and asks Claude to return
a JSON object mapping offer IDs to compatibility scores (0-100).

Usage:
    from app.services.cv_matcher_claude import ClaudeCVMatcher

    matcher = ClaudeCVMatcher(cv_text)
    scores = matcher.score_offers(offers)   # {offer_id: float 0-100}
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

BATCH_SIZE = 10


def _offer_summary(offer):
    """Build a short text summary of an offer for the prompt."""
    parts = [offer.title or ""]
    if offer.company:
        parts.append(f"({offer.company})")
    if offer.description:
        # Limit description length to keep prompt size reasonable
        desc = re.sub(r"\s+", " ", offer.description).strip()
        parts.append(desc[:400])
    return " – ".join(p for p in parts if p)


def _build_prompt(cv_text: str, batch: list) -> str:
    offers_block = "\n".join(
        f'- ID {offer.id}: {_offer_summary(offer)}' for offer in batch
    )
    return f"""Tu es un expert RH. Évalue la compatibilité entre ce CV et chaque offre d'emploi.

CV DU CANDIDAT :
{cv_text[:3000]}

OFFRES D'EMPLOI :
{offers_block}

Réponds UNIQUEMENT avec un objet JSON valide (pas de markdown, pas de texte avant/après) :
{{
  "<id_offre>": {{"score": <0-100>, "raison": "<explication courte en 1 phrase>"}},
  ...
}}

Critères de scoring :
- 80-100 : compétences principales très bien alignées
- 50-79  : bon alignement partiel
- 20-49  : quelques points communs
- 0-19   : peu ou pas d'alignement"""


class ClaudeCVMatcher:
    """
    Scores job offers against a CV using Claude Haiku.
    Processes offers in batches of {BATCH_SIZE} to reduce API calls.
    """

    def __init__(self, cv_text: str):
        if not cv_text or not cv_text.strip():
            raise ValueError("CV text is empty")
        self.cv_text = cv_text.strip()

    def score_offers(self, offers) -> dict:
        """
        Compute a 0-100 match score for each offer using Claude.

        Args:
            offers: iterable of Offer ORM objects (need .id, .title,
                    .company, .description)

        Returns:
            dict mapping offer.id -> float (0-100, rounded to 1 decimal)
        """
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic is required for Claude CV matching. "
                "Install it with: pip install anthropic"
            )

        from config import APIKeys
        api_key = APIKeys.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file."
            )

        from config import APIKeys as _ak
        model = _ak.ANTHROPIC_MODEL

        client = anthropic.Anthropic(api_key=api_key)
        offer_list = list(offers)
        if not offer_list:
            return {}

        scores = {}
        batches = [
            offer_list[i: i + BATCH_SIZE]
            for i in range(0, len(offer_list), BATCH_SIZE)
        ]

        for idx, batch in enumerate(batches):
            logger.info(
                f"[cv_matcher_claude] Batch {idx + 1}/{len(batches)} "
                f"({len(batch)} offers)…"
            )
            prompt = _build_prompt(self.cv_text, batch)
            try:
                message = client.messages.create(
                    model=model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = message.content[0].text.strip()
                # Strip markdown code fences if present
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
                data = json.loads(raw)

                for offer in batch:
                    key = str(offer.id)
                    if key in data:
                        entry = data[key]
                        score = float(entry.get("score", 0))
                        scores[offer.id] = round(min(max(score, 0), 100), 1)
                    else:
                        scores[offer.id] = 0.0

            except json.JSONDecodeError as e:
                logger.warning(
                    f"[cv_matcher_claude] JSON parse error in batch {idx + 1}: {e}"
                )
                for offer in batch:
                    scores[offer.id] = 0.0
            except Exception as e:
                logger.error(
                    f"[cv_matcher_claude] API error in batch {idx + 1}: {e}"
                )
                for offer in batch:
                    scores[offer.id] = 0.0

        return scores
