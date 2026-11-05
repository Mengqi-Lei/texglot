"""Choose a translation backend without changing source or reader contracts."""

from .deepl import DEEPL_VERSION, DeepLTranslator
from .llm import (
    PROMPT_VERSION,
    normalize_language,
    strip_reasoning,
    validate_translation_language,
)
from .llm import Translator as LLMTranslator
from .providers import provider_for_url


def Translator(settings):
    if provider_for_url(settings.base_url) == "deepl":
        return DeepLTranslator(settings)
    return LLMTranslator(settings)


def cached_translation(value: str, item, settings) -> str:
    """Return a stored translation that can be restored into the source.

    A cache entry keeps the raw model answer, so an earlier run may still
    carry a reasoning block that must not reach the paper.
    """
    text = normalize_language(strip_reasoning(value), settings.target_language)
    validate_translation_language(item, text, settings.target_language)
    return item.restore(text)


def cache_settings(settings, context):
    values = {
        "version": PROMPT_VERSION,
        "base": settings.base_url,
        "model": settings.model,
        "language": settings.target_language,
        "glossary": settings.glossary,
        "paper_context": context,
        "context_guidance": settings.context_guidance,
    }
    # Preserve the exact old LLM cache identity. DeepL never interprets the
    # free-form LLM glossary or its prompt revision.
    if provider_for_url(settings.base_url) == "deepl":
        values.update(
            version=DEEPL_VERSION,
            glossary=settings.deepl_glossary_id,
            source_language=settings.deepl_source_language,
        )
    return values
