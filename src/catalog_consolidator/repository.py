"""Fronteira de persistência SQLite do catálogo."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .domain import ApplyResult, CatalogProduct, ComparisonFields, PlannedEntry, ProductEntry, normalize


IDENTITY_COLUMNS = ("NormalizedName", "NormalizedBrand", "NormalizedCategory")
COMPARISON_COLUMNS = {
    "name": "NormalizedName",
    "brand": "NormalizedBrand",
    "category": "NormalizedCategory",
}
CANDIDATE_LIMIT = 100


class CatalogRepository:
    def __init__(self, database_path: Path) -> None:
        self._path = database_path

    def open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def prepare_catalog(self) -> None:
        """Valida o esquema recebido e prepara identidades normalizadas indexadas."""
        required = {
            "Product": {"Id", "Name", "Brand", "Category"},
            "SellerProduct": {"Id", "SellerName", "ProductId", "SellerProductId"},
        }
        with self.open_connection() as connection:
            for table, expected_columns in required.items():
                columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                missing = expected_columns - columns
                if missing:
                    raise ValueError(f"table {table} is missing columns: {', '.join(sorted(missing))}")
            product_columns = {row["name"] for row in connection.execute("PRAGMA table_info(Product)")}
            for column in IDENTITY_COLUMNS:
                if column not in product_columns:
                    connection.execute(f"ALTER TABLE Product ADD COLUMN {column} TEXT")
            rows = connection.execute("SELECT Id, Name, Brand, Category, NormalizedName, NormalizedBrand, NormalizedCategory FROM Product")
            updates = []
            for row in rows:
                normalized_values = (normalize(row["Name"]), normalize(row["Brand"]), normalize(row["Category"]))
                if normalized_values != (row["NormalizedName"], row["NormalizedBrand"], row["NormalizedCategory"]):
                    updates.append((*normalized_values, row["Id"]))
            connection.executemany(
                "UPDATE Product SET NormalizedName = ?, NormalizedBrand = ?, NormalizedCategory = ? WHERE Id = ?",
                updates,
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_product_identity "
                "ON Product(NormalizedName, NormalizedBrand, NormalizedCategory)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_product_candidates_by_brand "
                "ON Product(NormalizedBrand, NormalizedCategory)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_product_candidates_by_category "
                "ON Product(NormalizedCategory)"
            )

    @staticmethod
    def _comparison_columns(fields: ComparisonFields) -> tuple[str, ...]:
        columns = [COMPARISON_COLUMNS["name"]]
        if fields.include_brand:
            columns.append(COMPARISON_COLUMNS["brand"])
        if fields.include_category:
            columns.append(COMPARISON_COLUMNS["category"])
        return tuple(columns)

    def find_exact_product_id(
        self, normalized_product_key: tuple[str, ...], fields: ComparisonFields = ComparisonFields()
    ) -> int | None:
        """Busca a equivalência determinística antes de envolver similaridade ou IA."""
        conditions = " AND ".join(f"{column} = ?" for column in self._comparison_columns(fields))
        with self.open_connection() as connection:
            row = connection.execute(
                f"SELECT Id FROM Product WHERE {conditions} ORDER BY Id LIMIT 1",
                normalized_product_key,
            ).fetchone()
        return None if row is None else int(row["Id"])

    def load_candidate_products(
        self,
        entry: ProductEntry,
        fields: ComparisonFields = ComparisonFields(),
        limit: int = CANDIDATE_LIMIT,
    ) -> list[CatalogProduct]:
        """Carrega um conjunto pequeno de candidatos, do filtro mais específico ao menos específico."""
        if limit < 1:
            raise ValueError("candidate limit must be positive")
        brand = normalize(entry.brand)
        category = normalize(entry.category)
        with self.open_connection() as connection:
            if fields.include_brand and fields.include_category and brand and category:
                candidates = self._load_products_by_conditions(
                    connection,
                    ("NormalizedBrand = ?", "NormalizedCategory = ?"),
                    (brand, category),
                    limit,
                )
                if candidates:
                    return candidates
            if fields.include_brand and brand:
                return self._load_products_by_conditions(
                    connection, ("NormalizedBrand = ?",), (brand,), limit
                )
            if fields.include_category and category:
                return self._load_products_by_conditions(
                    connection, ("NormalizedCategory = ?",), (category,), limit
                )
            return self._load_products_by_conditions(connection, (), (), limit)

    @staticmethod
    def _load_products_by_conditions(
        connection: sqlite3.Connection,
        conditions: tuple[str, ...],
        values: tuple[str, ...],
        limit: int,
    ) -> list[CatalogProduct]:
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return [
            CatalogProduct(row["Id"], row["Name"], row["Brand"], row["Category"])
            for row in connection.execute(
                f"SELECT Id, Name, Brand, Category FROM Product{where} ORDER BY Id LIMIT ?",
                (*values, limit),
            )
        ]

    def count_catalog(self) -> tuple[int, int]:
        """Retorna os totais para o resumo da execução, sem alterar o banco."""
        with self.open_connection() as connection:
            products = connection.execute("SELECT COUNT(*) FROM Product").fetchone()[0]
            seller_links = connection.execute("SELECT COUNT(*) FROM SellerProduct").fetchone()[0]
        return products, seller_links

    def save_plan(
        self, plan: Iterable[PlannedEntry], fields: ComparisonFields = ComparisonFields()
    ) -> ApplyResult:
        """Persiste um plano já resolvido em uma única transação."""
        inserted_product_count = 0
        inserted_seller_link_count = 0
        with self.open_connection() as connection:
            product_ids_by_pending_key: dict[tuple[str, ...], int] = {}
            comparison_conditions = " AND ".join(
                f"{column} = ?" for column in self._comparison_columns(fields)
            )
            for planned_entry in plan:
                product_id = planned_entry.product_id
                if product_id is None:
                    assert planned_entry.pending_key is not None
                    product_id = product_ids_by_pending_key.get(planned_entry.pending_key)
                    if product_id is None:
                        existing_product = connection.execute(
                            f"SELECT Id FROM Product WHERE {comparison_conditions} ORDER BY Id LIMIT 1",
                            planned_entry.pending_key,
                        ).fetchone()
                        if existing_product is not None:
                            product_id = int(existing_product["Id"])
                        else:
                            cursor = connection.execute(
                                "INSERT INTO Product("
                                "Name, Brand, Category, NormalizedName, NormalizedBrand, NormalizedCategory"
                                ") VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    planned_entry.entry.name,
                                    planned_entry.entry.brand,
                                    planned_entry.entry.category,
                                    *planned_entry.entry.normalized_product_key,
                                ),
                            )
                            product_id = int(cursor.lastrowid)
                            inserted_product_count += 1
                        product_ids_by_pending_key[planned_entry.pending_key] = product_id
                existing_source_link = connection.execute(
                    "SELECT ProductId FROM SellerProduct WHERE SellerName = ? AND SellerProductId = ?",
                    (planned_entry.entry.seller_name, planned_entry.entry.source_id),
                ).fetchone()
                if existing_source_link is not None:
                    if existing_source_link["ProductId"] != product_id:
                        raise ValueError(
                            "seller source id "
                            f"{planned_entry.entry.seller_name}/{planned_entry.entry.source_id} "
                            f"is linked to product {existing_source_link['ProductId']}, "
                            f"but the plan selected product {product_id}"
                        )
                    continue
                existing_seller_link = connection.execute(
                    "SELECT 1 FROM SellerProduct WHERE SellerName = ? AND ProductId = ?",
                    (planned_entry.entry.seller_name, product_id),
                ).fetchone()
                if existing_seller_link is not None:
                    continue
                connection.execute(
                    "INSERT INTO SellerProduct(SellerName, ProductId, SellerProductId) VALUES (?, ?, ?)",
                    (planned_entry.entry.seller_name, product_id, planned_entry.entry.source_id),
                )
                inserted_seller_link_count += 1
        return ApplyResult(inserted_product_count, inserted_seller_link_count)
