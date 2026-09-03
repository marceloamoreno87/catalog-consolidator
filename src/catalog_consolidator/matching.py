"""Pré-seleção determinística de produtos possivelmente equivalentes."""

from __future__ import annotations

import difflib
from collections.abc import Iterable

from .domain import CatalogProduct, ComparisonFields, ProductEntry, normalize

DEFAULT_MATCH_THRESHOLD = 0.72


def _sorted_tokens(normalized_value: str) -> str:
    """Ordena os termos para comparar nomes cuja ordem foi invertida."""
    return " ".join(sorted(normalized_value.split()))


def rank_candidates(
    entry: ProductEntry,
    products: Iterable[CatalogProduct],
    limit: int = 5,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    comparison_fields: ComparisonFields = ComparisonFields(),
) -> list[CatalogProduct]:
    """Retorna candidatos plausíveis para a decisão do agente somente de leitura."""
    if not 0 <= threshold <= 1:
        raise ValueError("candidate threshold must be between 0 and 1")
    entry_name = normalize(entry.name)
    entry_brand = normalize(entry.brand)
    entry_category = normalize(entry.category)
    entry_name_with_sorted_tokens = _sorted_tokens(entry_name)
    ranked_candidates: list[tuple[float, CatalogProduct]] = []
    for product in products:
        product_brand = normalize(product.brand)
        if comparison_fields.include_brand and entry_brand and product_brand and entry_brand != product_brand:
            continue
        product_name = normalize(product.name)
        product_name_with_sorted_tokens = _sorted_tokens(product_name)
        name_score = max(
            difflib.SequenceMatcher(None, entry_name, product_name).ratio(),
            difflib.SequenceMatcher(
                None, entry_name_with_sorted_tokens, product_name_with_sorted_tokens
            ).ratio(),
        )
        category_score = difflib.SequenceMatcher(None, entry_category, normalize(product.category)).ratio()
        score = 0.85 * name_score + 0.15 * category_score if comparison_fields.include_category else name_score
        if score >= threshold:
            ranked_candidates.append((score, product))
    return [
        product
        for _, product in sorted(ranked_candidates, key=lambda item: (-item[0], item[1].product_id))[:limit]
    ]
