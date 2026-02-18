"""
CV-to-offer TF-IDF matching for JobHunter.

Compares the user's CV text against offer titles and descriptions using
TF-IDF vectorization + cosine similarity, producing a 0-100 match score.

Usage:
    from app.services.cv_matcher import CVMatcher

    matcher = CVMatcher(cv_text)
    scores = matcher.score_offers(offers)   # {offer_id: float 0-100}
"""

import logging
import re

logger = logging.getLogger(__name__)


def _check_deps():
    """Import heavy ML deps lazily so the rest of the app still loads without them."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        return TfidfVectorizer, cosine_similarity
    except ImportError:
        raise ImportError(
            "scikit-learn is required for CV matching. "
            "Install it with: pip install scikit-learn"
        )


def _normalize(text):
    """Lower-case and strip accents/punctuation for consistent tokenization."""
    if not text:
        return ""
    text = text.lower()
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _offer_text(offer):
    """Build a single text blob from the most signal-rich offer fields."""
    parts = [
        offer.title or "",
        offer.company or "",
        offer.description or "",
    ]
    return _normalize(" ".join(parts))


class CVMatcher:
    """
    Fits a TF-IDF model on a set of job offers + the user's CV, then
    returns cosine-similarity scores between the CV and each offer.
    """

    def __init__(self, cv_text: str):
        if not cv_text or not cv_text.strip():
            raise ValueError("CV text is empty")
        self.cv_text = _normalize(cv_text)

    def score_offers(self, offers) -> dict:
        """
        Compute a 0-100 match score for each offer.

        Args:
            offers: iterable of Offer ORM objects (need .id, .title,
                    .company, .description)

        Returns:
            dict mapping offer.id -> float (0-100, rounded to 1 decimal)
        """
        TfidfVectorizer, cosine_similarity = _check_deps()

        offer_list = list(offers)
        if not offer_list:
            return {}

        offer_texts = [_offer_text(o) for o in offer_list]
        corpus = offer_texts + [self.cv_text]

        try:
            vectorizer = TfidfVectorizer(
                analyzer="word",
                ngram_range=(1, 2),
                sublinear_tf=True,
                min_df=1,
                max_features=20_000,
                stop_words=_french_stop_words(),
            )
            tfidf = vectorizer.fit_transform(corpus)
        except ValueError as e:
            logger.warning(f"[cv_matcher] TF-IDF error: {e}")
            return {o.id: 0.0 for o in offer_list}

        # Last row is the CV vector
        cv_vec = tfidf[-1]
        offer_vecs = tfidf[:-1]

        similarities = cosine_similarity(cv_vec, offer_vecs).flatten()

        scores = {}
        for offer, sim in zip(offer_list, similarities):
            scores[offer.id] = round(float(sim) * 100, 1)

        return scores


def _french_stop_words():
    """Minimal French stop-word list for TF-IDF."""
    return [
        "le", "la", "les", "de", "du", "des", "et", "en", "au", "aux",
        "un", "une", "pour", "par", "sur", "avec", "dans", "qui", "que",
        "est", "son", "sa", "ses", "ce", "se", "ou", "à", "il", "elle",
        "ils", "elles", "nous", "vous", "je", "tu", "me", "te", "lui",
        "y", "en", "ne", "pas", "plus", "très", "bien", "tout", "tous",
        "cette", "cet", "ces", "mon", "ma", "mes", "ton", "ta", "tes",
        "notre", "votre", "leur", "leurs", "ont", "été", "être", "avoir",
        "fait", "faire", "comme", "mais", "si", "car", "donc", "or",
        "ni", "on", "autres", "même", "aussi", "encore", "déjà",
        "toute", "toutes", "ainsi", "afin", "lors", "dont", "d", "l",
        "s", "n", "j", "m", "qu",
    ]
