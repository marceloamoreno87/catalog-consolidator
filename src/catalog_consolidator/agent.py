"""Adaptador da IA usado exclusivamente para desempatar produtos parecidos."""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from contextlib import nullcontext
from typing import Literal

from pydantic import BaseModel, Field

from .domain import CatalogProduct, ComparisonFields, MatchDecision, ProductEntry
from .langfuse import DEFAULT_SYSTEM_PROMPT, LangfuseCatalogObserver


class AgentUnavailable(RuntimeError):
    """Indica ausência de dependência ou falha de acesso ao serviço de IA."""


class AgentResponse(BaseModel):
    """Resposta estruturada aceita do agente de correspondência."""

    action: Literal["match", "create"] = Field(
        description="Escolha match apenas quando for claramente o mesmo produto vendável."
    )
    product_id: int | None = Field(
        default=None,
        description="O id do candidato inspecionado quando action for match; caso contrário, nulo.",
    )
    confidence: Literal["high", "low"]
    reason: str = Field(
        description="Explique em uma frase curta quais dados confirmam ou impedem a correspondência."
    )


def _comparison_payload(
    product: ProductEntry | CatalogProduct, fields: ComparisonFields
) -> dict[str, str | None]:
    """Retorna somente os dados selecionados para comparação pelo agente."""
    payload: dict[str, str | None] = {"name": product.name}
    if fields.include_brand:
        payload["brand"] = product.brand
    if fields.include_category:
        payload["category"] = product.category
    return payload


class CatalogAgent:
    """Agente restrito e somente de leitura para decidir correspondências incertas."""

    def __init__(
        self,
        model_name: str,
        comparison_fields: ComparisonFields = ComparisonFields(),
        observer: LangfuseCatalogObserver | None = None,
    ) -> None:
        self._model_name = model_name
        self._comparison_fields = comparison_fields
        self._observer = observer

    def resolve(self, entry: ProductEntry, candidates: Sequence[CatalogProduct]) -> MatchDecision:
        if not candidates:
            return MatchDecision(None, "não há candidatos para comparar")
        try:
            from langchain.agents import create_agent
            from langchain.tools import tool
            from langchain_openai import ChatOpenAI
            from openai import OpenAIError
        except ImportError as error:
            raise AgentUnavailable("install project dependencies to resolve ambiguous products") from error

        candidates_by_id = {candidate.product_id: candidate for candidate in candidates}

        @tool
        def inspect_candidate(product_id: int) -> str:
            """Retorna um candidato permitido do catálogo. Use somente um id listado na solicitação."""
            product = candidates_by_id.get(product_id)
            if product is None:
                return "O candidato não está disponível. Escolha criar quando nenhum candidato listado for o mesmo produto."
            candidate_data = {
                "product_id": product.product_id,
                **_comparison_payload(product, self._comparison_fields),
            }
            return json.dumps(candidate_data)

        try:
            system_prompt, prompt = self._system_prompt()
            invocation_config = self._invocation_config()
            agent = create_agent(
                model=ChatOpenAI(model=self._model_name, temperature=0, use_responses_api=True),
                tools=[inspect_candidate],
                response_format=AgentResponse,
                system_prompt=system_prompt,
            )
            request = self._request(entry, candidates_by_id)
            with self._prompt_context(prompt), self._decision_observation(request) as observation:
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": json.dumps(request)}]}, config=invocation_config
                )
                decision = self._match_decision(result["structured_response"], candidates_by_id)
                if observation is not None:
                    try:
                        self._observer.complete_decision(observation, decision)
                    except Exception:
                        pass
        except OpenAIError as error:
            raise AgentUnavailable("OpenAI não está disponível para avaliar produtos ambíguos") from error

        return decision

    def _system_prompt(self) -> tuple[str, object | None]:
        if self._observer is not None:
            try:
                return self._observer.prompt(self._comparison_fields)
            except Exception:
                pass
        return DEFAULT_SYSTEM_PROMPT.replace("{{comparison_fields}}", ", ".join(self._comparison_fields.labels)), None

    def _invocation_config(self) -> dict[str, object]:
        if self._observer is None:
            return {}
        try:
            return self._observer.invocation_config()
        except Exception:
            return {}

    def _prompt_context(self, prompt: object | None):
        if self._observer is None:
            return nullcontext()
        try:
            return self._observer.prompt_context(prompt)
        except Exception:
            return nullcontext()

    def _decision_observation(self, request: dict[str, object]):
        if self._observer is None:
            return nullcontext(None)
        try:
            return self._observer.start_decision(request)
        except Exception:
            return nullcontext(None)

    def _request(self, entry: ProductEntry, candidate_ids: Collection[int]) -> dict[str, object]:
        return {
            "source_id": entry.source_id,
            "seller": entry.seller_name,
            **_comparison_payload(entry, self._comparison_fields),
            "candidate_ids": sorted(candidate_ids),
        }

    @staticmethod
    def _match_decision(decision: AgentResponse, candidate_ids: Collection[int]) -> MatchDecision:
        reason = " ".join(decision.reason.split())[:300] or "o agente não informou uma justificativa"
        if (
            decision.action == "match"
            and decision.confidence == "high"
            and decision.product_id in candidate_ids
        ):
            return MatchDecision(decision.product_id, reason)
        return MatchDecision(None, reason)
