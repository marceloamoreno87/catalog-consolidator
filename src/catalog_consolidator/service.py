"""Orquestra a criação de um plano antes de qualquer escrita no catálogo."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .domain import CatalogProduct, ComparisonFields, MatchDecision, PlannedEntry, ProductEntry
from .matching import DEFAULT_MATCH_THRESHOLD, rank_candidates
from .repository import CatalogRepository


class MatchResolver(Protocol):
    def resolve(self, entry: ProductEntry, candidates: list[CatalogProduct]) -> MatchDecision: ...


@dataclass(frozen=True)
class PlanSummary:
    """Contagens do planejamento, usadas pela interface de linha de comando."""

    entries: int
    duplicate_source_entries: int
    exact_matches: int
    agent_matches: int
    new_products: int


class ProgressDecision(Enum):
    """Motivos tipados para o andamento, separados do texto apresentado na CLI."""

    DUPLICATE_SOURCE = "duplicate_source"
    EXACT_MATCH = "exact_match"
    REPEATED_IN_FILE = "repeated_in_file"
    AGENT_MATCH = "agent_match"
    NEW_PRODUCT = "new_product"


ProgressReporter = Callable[[int, int, ProductEntry, ProgressDecision, str | None], None]


class Consolidator:
    def __init__(
        self,
        repository: CatalogRepository,
        resolver: MatchResolver,
        minimum_match_score: float = DEFAULT_MATCH_THRESHOLD,
        comparison_fields: ComparisonFields = ComparisonFields(),
    ) -> None:
        self._repository = repository
        self._resolver = resolver
        self._minimum_match_score = minimum_match_score
        self._comparison_fields = comparison_fields

    def build_plan(
        self, entries: list[ProductEntry], report_progress: ProgressReporter | None = None
    ) -> tuple[list[PlannedEntry], PlanSummary]:
        """Resolve cada entrada em um plano; este método não persiste alterações."""
        product_ids_by_identity: dict[tuple[str, ...], int] = {}
        new_product_keys: set[tuple[str, ...]] = set()
        planned_entries: list[PlannedEntry] = []
        exact_matches = agent_matches = 0
        identity_by_seller_source: dict[tuple[str, str], tuple[str, ...]] = {}

        for position, entry in enumerate(entries, start=1):
            comparison_key = self._comparison_fields.key_for(entry.name, entry.brand, entry.category)
            source_key = (entry.seller_name, entry.source_id)
            previous_identity = identity_by_seller_source.get(source_key)
            if previous_identity is not None:
                if previous_identity == entry.normalized_product_key:
                    self._report(report_progress, position, len(entries), entry, ProgressDecision.DUPLICATE_SOURCE)
                    continue
                raise ValueError(f"conflicting seller source id in input: {entry.seller_name}/{entry.source_id}")
            identity_by_seller_source[source_key] = entry.normalized_product_key
            product_id = product_ids_by_identity.get(comparison_key)
            if product_id is None:
                product_id = self._repository.find_exact_product_id(comparison_key, self._comparison_fields)
            if product_id is not None:
                planned_entries.append(PlannedEntry(entry, product_id, None))
                product_ids_by_identity[comparison_key] = product_id
                exact_matches += 1
                self._report(report_progress, position, len(entries), entry, ProgressDecision.EXACT_MATCH)
                continue
            if comparison_key in new_product_keys:
                planned_entries.append(PlannedEntry(entry, None, comparison_key))
                exact_matches += 1
                self._report(report_progress, position, len(entries), entry, ProgressDecision.REPEATED_IN_FILE)
                continue
            ranked_candidates = rank_candidates(
                entry,
                self._repository.load_candidate_products(entry, self._comparison_fields),
                threshold=self._minimum_match_score,
                comparison_fields=self._comparison_fields,
            )
            if ranked_candidates:
                match_decision = self._resolver.resolve(entry, ranked_candidates)
            else:
                match_decision = MatchDecision(None, "não há candidatos para comparar")
            if match_decision.product_id is not None:
                planned_entries.append(PlannedEntry(entry, match_decision.product_id, None))
                product_ids_by_identity[comparison_key] = match_decision.product_id
                agent_matches += 1
                self._report(
                    report_progress,
                    position,
                    len(entries),
                    entry,
                    ProgressDecision.AGENT_MATCH,
                    match_decision.reason,
                )
            else:
                planned_entries.append(PlannedEntry(entry, None, comparison_key))
                new_product_keys.add(comparison_key)
                self._report(
                    report_progress,
                    position,
                    len(entries),
                    entry,
                    ProgressDecision.NEW_PRODUCT,
                    match_decision.reason,
                )

        return planned_entries, PlanSummary(
            len(entries),
            len(entries) - len(planned_entries),
            exact_matches,
            agent_matches,
            len(new_product_keys),
        )

    @staticmethod
    def _report(
        report_progress: ProgressReporter | None,
        position: int,
        total: int,
        entry: ProductEntry,
        decision: ProgressDecision,
        reason: str | None = None,
    ) -> None:
        if report_progress is not None:
            report_progress(position, total, entry, decision, reason)
