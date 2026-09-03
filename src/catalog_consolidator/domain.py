"""Tipos e regras de identidade usados na consolidação."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError


def normalize(value: str | None) -> str:
    """Gera uma chave conservadora para comparação, nunca para exibição."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"['’]", "", text.casefold())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalized_product_key(name: str, brand: str | None, category: str) -> tuple[str, str, str]:
    """Normaliza todos os campos persistidos que identificam um produto."""
    return (normalize(name), normalize(brand), normalize(category))


@dataclass(frozen=True)
class ComparisonFields:
    """Campos opcionais que acompanham o nome na comparação."""

    include_brand: bool = True
    include_category: bool = True

    @property
    def labels(self) -> tuple[str, ...]:
        labels = ["Nome"]
        if self.include_brand:
            labels.append("Marca")
        if self.include_category:
            labels.append("Categoria")
        return tuple(labels)

    def key_for(self, name: str, brand: str | None, category: str) -> tuple[str, ...]:
        """Normaliza os campos que participam da identidade atual."""
        selected_fields = (True, self.include_brand, self.include_category)
        return tuple(
            value
            for value, included in zip(normalized_product_key(name, brand, category), selected_fields)
            if included
        )


class ProductEntry(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True, str_strip_whitespace=True)

    source_id: str = Field(validation_alias="Id", min_length=1)
    seller_name: str = Field(validation_alias="SellerName", min_length=1)
    name: str = Field(validation_alias="Name", min_length=1)
    brand: str | None = Field(validation_alias="Brand", min_length=1)
    category: str = Field(validation_alias="Category", min_length=1)

    @classmethod
    def from_json(cls, value: object, position: int) -> "ProductEntry":
        try:
            return cls.model_validate(value)
        except ValidationError as error:
            raise ValueError(f"entry {position}: {error}") from error

    @property
    def normalized_product_key(self) -> tuple[str, str, str]:
        return normalized_product_key(self.name, self.brand, self.category)


@dataclass(frozen=True)
class CatalogProduct:
    """Produto já persistido, reduzido aos atributos necessários para comparar."""
    product_id: int
    name: str
    brand: str | None
    category: str

    @property
    def normalized_product_key(self) -> tuple[str, str, str]:
        return normalized_product_key(self.name, self.brand, self.category)


@dataclass(frozen=True)
class MatchDecision:
    """Resultado seguro e explicável do agente para uma entrada ambígua."""

    product_id: int | None
    reason: str


@dataclass(frozen=True)
class PlannedEntry:
    """Entrada resolvida para um produto existente ou pendente de criação."""

    entry: ProductEntry
    product_id: int | None
    pending_key: tuple[str, ...] | None


@dataclass(frozen=True)
class ApplyResult:
    """Contadores das inserções efetivamente realizadas na aplicação do plano."""

    products_inserted: int
    seller_links_inserted: int
