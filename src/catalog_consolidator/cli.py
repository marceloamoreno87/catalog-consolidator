"""Ponto de entrada da aplicação local e tradução de configuração para o domínio."""

from __future__ import annotations

import json
import os
from contextlib import nullcontext
from pathlib import Path

from dotenv import load_dotenv

from .agent import CatalogAgent
from .domain import ComparisonFields, ProductEntry
from .langfuse import LangfuseCatalogObserver, LangfuseSettings
from .matching import DEFAULT_MATCH_THRESHOLD
from .repository import CatalogRepository
from .service import Consolidator, ProgressDecision


def parse_entries(path: Path) -> list[ProductEntry]:
    """Lê um array JSON e valida cada posição antes de iniciar a consolidação."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read input {path}: {error}") from error
    if not isinstance(raw, list):
        raise ValueError("input must be a JSON array")
    return [ProductEntry.from_json(value, position + 1) for position, value in enumerate(raw)]


def required_env_value(name: str) -> str:
    """Obtém uma configuração obrigatória, com erro apropriado para a pessoa usuária."""
    env_value = os.getenv(name)
    if not env_value:
        raise ValueError(f"{name} deve ser definido no arquivo .env")
    return env_value


def match_threshold_from_env() -> float:
    """Converte e valida o limite opcional de similaridade."""
    env_value = os.getenv("CATALOG_MATCH_THRESHOLD")
    if env_value is None:
        return DEFAULT_MATCH_THRESHOLD
    try:
        threshold = float(env_value)
    except ValueError as error:
        raise ValueError("CATALOG_MATCH_THRESHOLD deve ser um número entre 0 e 1") from error
    if not 0 <= threshold <= 1:
        raise ValueError("CATALOG_MATCH_THRESHOLD deve estar entre 0 e 1")
    return threshold


def prompt_comparison_fields() -> ComparisonFields:
    """Pede os campos opcionais que acompanharão Nome na comparação."""
    while True:
        print("Vou comparar sempre pelo Nome.")
        print("Escolha os campos adicionais: 1. Marca  2. Categoria")
        try:
            selected = input("Digite 1 e/ou 2 separados por vírgula (Enter para somente Nome): ").strip()
        except EOFError as error:
            raise ValueError("não foi possível ler a seleção de campos") from error
        if not selected:
            return ComparisonFields(include_brand=False, include_category=False)
        choices = {choice.strip() for choice in selected.split(",")}
        if choices <= {"1", "2"} and len(choices) == len(selected.split(",")):
            return ComparisonFields(include_brand="1" in choices, include_category="2" in choices)
        print("Opção inválida. Informe 1, 2 ou 1,2.")


SIMPLE_DECISIONS = {
    ProgressDecision.DUPLICATE_SOURCE: "é uma repetição; deixei de lado",
    ProgressDecision.EXACT_MATCH: "já estava no catálogo",
    ProgressDecision.REPEATED_IN_FILE: "já apareceu neste arquivo",
    ProgressDecision.AGENT_MATCH: "achei um igual",
    ProgressDecision.NEW_PRODUCT: "é um produto novo",
}


def simple_decision(decision: ProgressDecision) -> str:
    return SIMPLE_DECISIONS[decision]


def main() -> int:
    load_dotenv(".env")
    try:
        comparison_fields = prompt_comparison_fields()
        print("Estou lendo o arquivo...")
        entries = parse_entries(Path(required_env_value("CATALOG_INPUT")))
        repository = CatalogRepository(Path(required_env_value("CATALOG_DATABASE")))
        print("Estou olhando o catálogo...")
        repository.prepare_catalog()
        products_before, links_before = repository.count_catalog()
        print(f"Antes: {products_before} produtos e {links_before} ofertas.")
        print("Agora vou comparar os produtos...")
        langfuse_settings = LangfuseSettings.from_environment()
        observer = LangfuseCatalogObserver(langfuse_settings) if langfuse_settings else None
        threshold = match_threshold_from_env()
        consolidation = observer.consolidation(len(entries), comparison_fields, threshold) if observer else nullcontext(None)
        with consolidation as run_observation:
            planning = observer.start_stage("catalog-matching", {"entries": len(entries)}) if observer else nullcontext(None)
            with planning as planning_observation:
                plan, summary = Consolidator(
                    repository,
                    CatalogAgent(required_env_value("OPENAI_MODEL"), comparison_fields, observer),
                    threshold,
                    comparison_fields,
                ).build_plan(
                    entries,
                    lambda position, total, entry, decision, _reason: print(
                        f"[{position} de {total}] {entry.seller_name}: {entry.name} — {simple_decision(decision)}."
                    ),
                )
                if planning_observation is not None:
                    planning_observation.update(
                        output={
                            "exact_matches": summary.exact_matches,
                            "agent_matches": summary.agent_matches,
                            "new_products": summary.new_products,
                        }
                    )
            print("Estou guardando tudo...")
            persistence = observer.start_stage("catalog-persistence", {"planned_entries": len(plan)}) if observer else nullcontext(None)
            with persistence as persistence_observation:
                apply_result = repository.save_plan(plan, comparison_fields)
                if persistence_observation is not None:
                    persistence_observation.update(
                        output={
                            "products_inserted": apply_result.products_inserted,
                            "seller_links_inserted": apply_result.seller_links_inserted,
                        }
                    )
            if run_observation is not None:
                observer.complete_consolidation(run_observation, summary, apply_result)
        products_after, links_after = repository.count_catalog()
        print("Pronto!")
        print(f"Li {summary.entries} itens.")
        print(f"Deixei de lado {summary.duplicate_source_entries} itens repetidos.")
        print(f"{summary.exact_matches} itens já estavam no catálogo.")
        print(f"Achei {summary.agent_matches} itens iguais.")
        print(f"Guardei {apply_result.products_inserted} produtos novos e {apply_result.seller_links_inserted} ofertas.")
        print(f"Agora: {products_after} produtos e {links_after} ofertas.")
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print("Ops! Não consegui terminar. Confira os arquivos e tente de novo.")
        print(f"Detalhe: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
