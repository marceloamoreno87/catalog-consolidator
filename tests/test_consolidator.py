from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openai import OpenAIError

from catalog_consolidator.agent import AgentUnavailable, CatalogAgent
from catalog_consolidator.cli import (
    load_dotenv,
    main,
    match_threshold_from_env,
    prompt_comparison_fields,
    required_env_value,
    simple_decision,
)
from catalog_consolidator.domain import CatalogProduct, ComparisonFields, MatchDecision, PlannedEntry, ProductEntry, normalize
from catalog_consolidator.langfuse import mask_sensitive_data
from catalog_consolidator.matching import rank_candidates
from catalog_consolidator.repository import CatalogRepository
from catalog_consolidator.service import Consolidator, ProgressDecision


class FakeResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, entry: ProductEntry, candidates):
        self.calls += 1
        if entry.name == "Camera Canon EOS R6":
            return MatchDecision(candidates[0].product_id, "mesmo modelo Canon EOS R6")
        return MatchDecision(None, "nenhum candidato identifica o mesmo produto")


class ConsolidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "catalog.db"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE Product (Id INTEGER PRIMARY KEY AUTOINCREMENT, Name TEXT NOT NULL, Brand TEXT, Category TEXT);
            CREATE TABLE SellerProduct (Id INTEGER PRIMARY KEY AUTOINCREMENT, SellerName TEXT NOT NULL, ProductId INTEGER NOT NULL, SellerProductId INTEGER NOT NULL);
            INSERT INTO Product(Name, Brand, Category) VALUES ('Camera Canon EOS R6', 'Canon', 'Photography');
            """
        )
        connection.close()
        self.repository = CatalogRepository(self.database)
        self.repository.prepare_catalog()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_settings_use_dotenv_without_replacing_exported_values(self) -> None:
        environment_file = Path(self.directory.name) / ".env"
        environment_file.write_text("OPENAI_MODEL=from-file\nCATALOG_DATABASE=from-file.db\n", encoding="utf-8")
        with patch.dict("os.environ", {"OPENAI_MODEL": "exported"}, clear=True):
            load_dotenv(environment_file)
            self.assertEqual(required_env_value("OPENAI_MODEL"), "exported")
            self.assertEqual(required_env_value("CATALOG_DATABASE"), "from-file.db")
            with self.assertRaisesRegex(ValueError, "CATALOG_INPUT"):
                required_env_value("CATALOG_INPUT")

    def test_langfuse_mask_redacts_secrets_and_emails_without_hiding_catalog_data(self) -> None:
        masked = mask_sensitive_data(
            data={"seller": "Seller A", "token": "secret", "contact": "buyer@example.com"}
        )

        self.assertEqual(masked, {"seller": "Seller A", "token": "[REDACTED]", "contact": "[REDACTED_EMAIL]"})

    def test_candidate_threshold_defaults_and_rejects_invalid_values(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(match_threshold_from_env(), 0.72)
        with patch.dict("os.environ", {"CATALOG_MATCH_THRESHOLD": "0.65"}, clear=True):
            self.assertEqual(match_threshold_from_env(), 0.65)
        for value in ("invalid", "-0.01", "1.01", "nan"):
            with self.subTest(value=value), patch.dict(
                "os.environ", {"CATALOG_MATCH_THRESHOLD": value}, clear=True
            ):
                with self.assertRaisesRegex(ValueError, "CATALOG_MATCH_THRESHOLD"):
                    match_threshold_from_env()

    def test_prompt_comparison_fields_accepts_only_optional_valid_choices(self) -> None:
        with patch("builtins.input", side_effect=["3", "1,2"]), patch("builtins.print") as print_mock:
            fields = prompt_comparison_fields()

        self.assertEqual(fields, ComparisonFields(include_brand=True, include_category=True))
        self.assertTrue(any("Opção inválida" in str(call) for call in print_mock.call_args_list))

    def test_prompt_comparison_fields_allows_name_only(self) -> None:
        with patch("builtins.input", return_value=""):
            fields = prompt_comparison_fields()

        self.assertEqual(fields, ComparisonFields(include_brand=False, include_category=False))

    def test_simple_decision_hides_technical_details(self) -> None:
        self.assertEqual(simple_decision(ProgressDecision.EXACT_MATCH), "já estava no catálogo")
        self.assertEqual(simple_decision(ProgressDecision.AGENT_MATCH), "achei um igual")
        self.assertEqual(simple_decision(ProgressDecision.NEW_PRODUCT), "é um produto novo")
        self.assertEqual(simple_decision(ProgressDecision.REPEATED_IN_FILE), "já apareceu neste arquivo")
        self.assertEqual(simple_decision(ProgressDecision.DUPLICATE_SOURCE), "é uma repetição; deixei de lado")

    def test_main_prints_the_captured_error_detail(self) -> None:
        with (
            patch("catalog_consolidator.cli.load_dotenv"),
            patch("catalog_consolidator.cli.prompt_comparison_fields", side_effect=ValueError("erro de teste")),
            patch("builtins.print") as print_mock,
        ):
            self.assertEqual(main(), 2)

        print_mock.assert_any_call("Detalhe: erro de teste")

    def test_product_entry_validation_strips_values_and_rejects_empty_fields(self) -> None:
        entry = ProductEntry.from_json(
            {"Id": " source-1 ", "SellerName": " Seller A ", "Name": " Camera ", "Brand": None, "Category": " Photo "},
            1,
        )
        self.assertEqual((entry.source_id, entry.seller_name, entry.name, entry.brand, entry.category), ("source-1", "Seller A", "Camera", None, "Photo"))
        with self.assertRaisesRegex(ValueError, "entry 2"):
            ProductEntry.from_json(
                {"Id": "source-1", "SellerName": "Seller A", "Name": "Camera", "Brand": " ", "Category": "Photo"},
                2,
            )

    def test_normalize_ignores_apostrophes_inside_words(self) -> None:
        self.assertEqual(normalize("Levi's"), "levis")
        self.assertEqual(normalize("Levi’s"), "levis")

    def test_comparison_fields_builds_the_selected_normalized_key(self) -> None:
        self.assertEqual(
            ComparisonFields().key_for("Camera", "Canon", "Photography"),
            ("camera", "canon", "photography"),
        )
        self.assertEqual(
            ComparisonFields(include_brand=False, include_category=False).key_for(
                "Camera", "Canon", "Photography"
            ),
            ("camera",),
        )

    def test_prepare_catalog_recalculates_normalized_values_after_normalization_change(self) -> None:
        with self.repository.open_connection() as connection:
            connection.execute(
                "INSERT INTO Product(Name, Brand, Category, NormalizedName, NormalizedBrand, NormalizedCategory) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("Belt Leather Reversible", "Levis", "Accessories", "belt leather reversible", "levi s", "accessories"),
            )
            product_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]

        self.repository.prepare_catalog()

        with self.repository.open_connection() as connection:
            normalized_brand = connection.execute(
                "SELECT NormalizedBrand FROM Product WHERE Id = ?", (product_id,)
            ).fetchone()[0]
        self.assertEqual(normalized_brand, "levis")
        self.assertEqual(
            self.repository.find_exact_product_id(("belt leather reversible", "levis", "accessories")),
            product_id,
        )

    def test_rank_candidates_stays_outside_repository_and_respects_brand(self) -> None:
        entry = ProductEntry(
            source_id="source-1",
            seller_name="Seller A",
            name="Camera EOS R6",
            brand="Canon",
            category="Photography",
        )
        products = [
            CatalogProduct(1, "Camera Canon EOS R6", "Canon", "Photography"),
            CatalogProduct(2, "Camera EOS R6", "Nikon", "Photography"),
        ]

        self.assertEqual(rank_candidates(entry, products), [products[0]])
        self.assertEqual(
            rank_candidates(entry, products, comparison_fields=ComparisonFields(include_brand=False)),
            [products[1], products[0]],
        )

    def test_rank_candidates_uses_configured_threshold(self) -> None:
        entry = ProductEntry(
            source_id="source-1",
            seller_name="Seller A",
            name="Camera",
            brand="Canon",
            category="Photography",
        )
        product = CatalogProduct(1, "Notebook", "Canon", "Photography")

        self.assertEqual(rank_candidates(entry, [product]), [])
        self.assertEqual(rank_candidates(entry, [product], threshold=0), [product])

    def test_reordered_product_name_is_sent_to_the_agent_for_review(self) -> None:
        entry = ProductEntry(
            source_id="source-1",
            seller_name="Seller A",
            name="221 Cannon",
            brand="Canon",
            category="Photography",
        )
        product = CatalogProduct(2, "Camera Cannon 221", "Canon", "Photography")
        resolver = SimpleNamespace(
            calls=0,
            resolve=lambda reviewed_entry, candidates: MatchDecision(
                candidates[0].product_id, "mesmas palavras em ordem diferente"
            ),
        )

        with patch.object(self.repository, "load_candidate_products", return_value=[product]):
            plan, summary = Consolidator(self.repository, resolver).build_plan([entry])

        self.assertEqual(plan[0].product_id, product.product_id)
        self.assertEqual(summary.agent_matches, 1)

    def test_catalog_agent_uses_responses_api_for_tool_calling(self) -> None:
        agent_result = {
            "structured_response": SimpleNamespace(
                action="create", confidence="low", product_id=None, reason="modelo diferente"
            )
        }
        candidate = SimpleNamespace(product_id=1, name="Camera", brand="Canon", category="Photography")
        with (
            patch("langchain_openai.ChatOpenAI") as chat_model,
            patch("langchain.agents.create_agent") as create_agent,
        ):
            create_agent.return_value.invoke.return_value = agent_result
            resolved = CatalogAgent("gpt-5.6-luna").resolve(
            ProductEntry(source_id="source-1", seller_name="Seller A", name="Camera", brand="Canon", category="Photography"),
                [candidate],
            )

        self.assertEqual(resolved, MatchDecision(None, "modelo diferente"))
        chat_model.assert_called_once_with(
            model="gpt-5.6-luna", temperature=0, use_responses_api=True
        )

    def test_catalog_agent_hides_unselected_fields_from_the_request(self) -> None:
        agent_result = {
            "structured_response": SimpleNamespace(
                action="create", confidence="low", product_id=None, reason="modelo diferente"
            )
        }
        candidate = CatalogProduct(1, "Camera", "Canon", "Photography")
        entry = ProductEntry(
            source_id="source-1", seller_name="Seller A", name="Camera", brand="Canon", category="Photography"
        )
        with (
            patch("langchain_openai.ChatOpenAI"),
            patch("langchain.agents.create_agent") as create_agent,
        ):
            create_agent.return_value.invoke.return_value = agent_result
            CatalogAgent("gpt-5.6-luna", ComparisonFields(False, False)).resolve(entry, [candidate])

        request = json.loads(create_agent.return_value.invoke.call_args.args[0]["messages"][0]["content"])
        self.assertEqual(request, {"source_id": "source-1", "seller": "Seller A", "name": "Camera", "candidate_ids": [1]})
        candidate_payload = json.loads(create_agent.call_args.kwargs["tools"][0].invoke({"product_id": 1}))
        self.assertEqual(candidate_payload, {"product_id": 1, "name": "Camera"})
        self.assertIn("Nome", create_agent.call_args.kwargs["system_prompt"])
        self.assertNotIn("Marca", create_agent.call_args.kwargs["system_prompt"])

    def test_catalog_agent_accepts_only_a_high_confidence_allowed_candidate(self) -> None:
        agent_result = {
            "structured_response": SimpleNamespace(
                action="match", confidence="high", product_id=1, reason="  mesmo   produto  "
            )
        }
        candidate = CatalogProduct(1, "Camera", "Canon", "Photography")
        entry = ProductEntry(
            source_id="source-1", seller_name="Seller A", name="Camera", brand="Canon", category="Photography"
        )
        with (
            patch("langchain_openai.ChatOpenAI"),
            patch("langchain.agents.create_agent") as create_agent,
        ):
            create_agent.return_value.invoke.return_value = agent_result
            decision = CatalogAgent("gpt-5.6-luna").resolve(entry, [candidate])

        self.assertEqual(decision, MatchDecision(1, "mesmo produto"))

    def test_catalog_agent_translates_openai_errors(self) -> None:
        candidate = CatalogProduct(1, "Camera", "Canon", "Photography")
        entry = ProductEntry(
            source_id="source-1",
            seller_name="Seller A",
            name="Camera",
            brand="Canon",
            category="Photography",
        )

        with patch("langchain_openai.ChatOpenAI", side_effect=OpenAIError("missing credentials")):
            with self.assertRaisesRegex(AgentUnavailable, "OpenAI não está disponível"):
                CatalogAgent("gpt-5.6-luna").resolve(entry, [candidate])

    def test_prepare_adds_an_indexed_normalized_identity(self) -> None:
        self.repository.prepare_catalog()
        with self.repository.open_connection() as connection:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(Product)")}
            plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT Id FROM Product "
                "WHERE NormalizedName = ? AND NormalizedBrand = ? AND NormalizedCategory = ? "
                "ORDER BY Id LIMIT 1",
                ("camera canon eos r6", "canon", "photography"),
            ).fetchall()
        self.assertTrue({"NormalizedName", "NormalizedBrand", "NormalizedCategory"} <= columns)
        self.assertTrue(any("idx_product_identity" in row[3] for row in plan))
        self.assertEqual(
            self.repository.find_exact_product_id(("camera canon eos r6", "canon", "photography")), 1
        )

    def test_candidate_lookup_uses_a_bounded_brand_category_index(self) -> None:
        entry = ProductEntry(
            source_id="source-1",
            seller_name="Seller A",
            name="Camera Canon EOS R6 Mark II",
            brand="Canon",
            category="Photography",
        )
        with self.repository.open_connection() as connection:
            plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT Id, Name, Brand, Category FROM Product "
                "WHERE NormalizedBrand = ? AND NormalizedCategory = ? ORDER BY Id LIMIT ?",
                ("canon", "photography", 100),
            ).fetchall()

        self.assertEqual([product.product_id for product in self.repository.load_candidate_products(entry)], [1])
        self.assertTrue(any("idx_product_candidates_by_brand" in row[3] for row in plan))

    def test_exact_match_does_not_load_candidate_products(self) -> None:
        entry = ProductEntry(
            source_id="source-1",
            seller_name="Seller A",
            name="Câmera Canon EOS R6",
            brand="Canon",
            category="Photography",
        )
        with patch.object(self.repository, "load_candidate_products") as load_candidates:
            plan, summary = Consolidator(self.repository, FakeResolver()).build_plan([entry])

        self.assertEqual(plan[0].product_id, 1)
        self.assertEqual(summary.exact_matches, 1)
        load_candidates.assert_not_called()

    def test_name_only_comparison_ignores_brand_and_category(self) -> None:
        entry = ProductEntry(
            source_id="source-2",
            seller_name="Seller B",
            name="Camera Canon EOS R6",
            brand="Another Brand",
            category="Another Category",
        )
        fields = ComparisonFields(include_brand=False, include_category=False)

        plan, summary = Consolidator(self.repository, FakeResolver(), comparison_fields=fields).build_plan([entry])

        self.assertEqual(plan[0].product_id, 1)
        self.assertEqual(summary.exact_matches, 1)

    def test_name_only_comparison_groups_new_products_in_the_same_feed(self) -> None:
        entries = [
            ProductEntry(source_id="source-1", seller_name="Seller A", name="New Keyboard", brand="Acme", category="Accessories"),
            ProductEntry(source_id="source-2", seller_name="Seller B", name="New Keyboard", brand="Other", category="Office"),
        ]
        fields = ComparisonFields(include_brand=False, include_category=False)

        plan, summary = Consolidator(self.repository, FakeResolver(), comparison_fields=fields).build_plan(entries)
        result = self.repository.save_plan(plan, fields)

        self.assertEqual((summary.new_products, result.products_inserted, result.seller_links_inserted), (1, 1, 2))

    def test_save_plan_identifies_conflicting_seller_source_link(self) -> None:
        original = ProductEntry(
            source_id="source-1", seller_name="Seller A", name="Camera Canon EOS R6", brand="Canon", category="Photography"
        )
        self.repository.save_plan([PlannedEntry(original, 1, None)])
        conflicting = ProductEntry(
            source_id="source-1", seller_name="Seller A", name="Other Camera", brand="Other", category="Other"
        )

        with self.assertRaisesRegex(
            ValueError,
            r"Seller A/source-1 is linked to product 1, but the plan selected product 2",
        ):
            self.repository.save_plan([PlannedEntry(conflicting, 2, None)])

    def test_plan_and_apply_links_existing_agent_match_and_new_product(self) -> None:
        resolver = FakeResolver()
        entries = [
            ProductEntry(source_id="source-1", seller_name="Seller A", name="Câmera Canon EOS R6", brand="Canon", category="Photography"),
            ProductEntry(source_id="source-2", seller_name="Seller B", name="Camera Canon EOS R6", brand="Canon", category="Photo"),
            ProductEntry(source_id="source-3", seller_name="Seller C", name="New Keyboard", brand="Acme", category="Accessories"),
            ProductEntry(source_id="source-4", seller_name="Seller D", name="New Keyboard", brand="Acme", category="Accessories"),
        ]

        progress: list[tuple[int, int, ProgressDecision, str | None]] = []
        plan, summary = Consolidator(self.repository, resolver).build_plan(
            entries,
            lambda position, total, entry, decision, reason: progress.append((position, total, decision, reason)),
        )
        self.assertEqual((summary.exact_matches, summary.agent_matches, summary.new_products), (2, 1, 1))
        self.assertEqual(resolver.calls, 1)
        self.assertEqual(
            progress,
            [
                (1, 4, ProgressDecision.EXACT_MATCH, None),
                (2, 4, ProgressDecision.AGENT_MATCH, "mesmo modelo Canon EOS R6"),
                (3, 4, ProgressDecision.NEW_PRODUCT, "não há candidatos para comparar"),
                (4, 4, ProgressDecision.REPEATED_IN_FILE, None),
            ],
        )

        result = self.repository.save_plan(plan)
        self.assertEqual((result.products_inserted, result.seller_links_inserted), (1, 4))
        with self.repository.open_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM Product").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM SellerProduct").fetchone()[0], 4)
        self.assertEqual(self.repository.count_catalog(), (2, 4))
        self.assertEqual(self.repository.find_exact_product_id(entries[2].normalized_product_key), 2)
        repeated = self.repository.save_plan(plan)
        self.assertEqual((repeated.products_inserted, repeated.seller_links_inserted), (0, 0))

    def test_ignores_repeated_seller_source_id_with_same_normalized_product(self) -> None:
        entry = ProductEntry(source_id="source-1", seller_name="Seller A", name="New Keyboard", brand="Acme", category="Accessories")
        progress: list[tuple[ProgressDecision, str | None]] = []
        plan, summary = Consolidator(self.repository, FakeResolver()).build_plan(
            [entry, entry],
            lambda _position, _total, _entry, decision, reason: progress.append((decision, reason)),
        )
        self.assertEqual(len(plan), 1)
        self.assertEqual(summary.duplicate_source_entries, 1)
        self.assertEqual(progress[-1], (ProgressDecision.DUPLICATE_SOURCE, None))

    def test_rejects_conflicting_repeated_seller_source_id(self) -> None:
        first = ProductEntry(source_id="source-1", seller_name="Seller A", name="New Keyboard", brand="Acme", category="Accessories")
        conflicting = ProductEntry(source_id="source-1", seller_name="Seller A", name="New Mouse", brand="Acme", category="Accessories")
        with self.assertRaisesRegex(ValueError, "conflicting seller source id"):
            Consolidator(self.repository, FakeResolver()).build_plan([first, conflicting])
