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
    return f"""Tu es un recruteur senior exigeant. Évalue la compatibilité RÉELLE entre ce CV et chaque offre d'emploi. Sois STRICT et RÉALISTE dans tes scores — la plupart des offres doivent obtenir entre 20% et 60%.

CV DU CANDIDAT :
{cv_text[:3000]}

OFFRES D'EMPLOI :
{offers_block}

Réponds UNIQUEMENT avec un objet JSON valide (pas de markdown, pas de texte avant/après) :
{{
  "<id_offre>": {{"score": <0-100>, "raison": "<explication courte en 1 phrase>"}},
  ...
}}

BARÈME DE SCORING STRICT (respecte-le rigoureusement) :
- 0-20%   : aucun rapport — le CV et l'offre concernent des domaines complètement différents
- 20-40%  : quelques compétences communes mais le profil est fondamentalement différent (ex: un sysadmin pour un poste de développeur)
- 40-60%  : profil partiellement compatible — certaines compétences correspondent mais il manque des éléments clés (ex: bon domaine mais mauvais niveau ou technologies différentes)
- 60-80%  : bonne correspondance — la plupart des compétences requises sont présentes dans le CV, le domaine et le niveau correspondent
- 80-100% : correspondance excellente — le profil matche presque parfaitement l'offre, les compétences clés, le niveau d'expérience et le domaine sont tous alignés

RÈGLES IMPORTANTES :
- Un score > 70% exige que le candidat possède les compétences CLÉS demandées dans l'offre, pas juste des compétences vaguement liées
- Un score > 85% est RARE et ne devrait être donné que pour une correspondance quasi-parfaite
- Si l'offre demande un niveau d'expérience très différent du CV, pénalise fortement (-20 à -30 points)
- Si l'offre est dans un sous-domaine différent de celui du CV (ex: cybersécurité vs administration système), le score ne devrait pas dépasser 50%
- Ne sois PAS généreux : un score moyen de 40-50% pour un ensemble d'offres mixtes est normal"""


class ClaudeCVMatcher:
    """
    Scores job offers against a CV using Claude Haiku.
    Processes offers in batches of {BATCH_SIZE} to reduce API calls.
    """

    def __init__(self, cv_text: str):
        if not cv_text or not cv_text.strip():
            raise ValueError("CV text is empty")
        self.cv_text = cv_text.strip()
        self.total_tokens_used = 0

    def score_offers(self, offers, progress_callback=None) -> dict:
        """
        Compute a 0-100 match score for each offer using Claude.

        Args:
            offers:            iterable of Offer ORM objects (.id, .title, .company, .description)
            progress_callback: optional callable(batches_done, total_batches, offers_done)
                               called after each batch completes — used for async progress tracking.

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

        total_batches = len(batches)
        offers_done = 0

        for idx, batch in enumerate(batches):
            logger.info(
                f"[cv_matcher_claude] Batch {idx + 1}/{total_batches} "
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
                if hasattr(message, 'usage') and message.usage:
                    self.total_tokens_used += (
                        (message.usage.input_tokens or 0) +
                        (message.usage.output_tokens or 0)
                    )
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
            except anthropic.BadRequestError as e:
                logger.error(f"[cv_matcher_claude] 400 error in batch {idx + 1}: {e}")
                raise RuntimeError(f"Erreur API Claude (400) : {e}") from e
            except anthropic.APIStatusError as e:
                msg = str(e).lower()
                if "credit balance is too low" in msg or e.status_code in (400, 402):
                    logger.error(
                        f"[cv_matcher_claude] Fatal API error (status {e.status_code}), "
                        "stopping early."
                    )
                    raise RuntimeError(
                        f"Crédit Anthropic insuffisant ou erreur fatale "
                        f"(HTTP {e.status_code}) : {e}"
                    ) from e
                logger.error(
                    f"[cv_matcher_claude] API error in batch {idx + 1}: {e}"
                )
                for offer in batch:
                    scores[offer.id] = 0.0
            except Exception as e:
                logger.error(
                    f"[cv_matcher_claude] API error in batch {idx + 1}: {e}"
                )
                for offer in batch:
                    scores[offer.id] = 0.0

            offers_done += len(batch)
            if progress_callback is not None:
                progress_callback(idx + 1, total_batches, offers_done)

        return scores
