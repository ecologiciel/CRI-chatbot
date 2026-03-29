"""Tests for the supervised learning API router.

Covers: import checks, route definitions, schema validation,
and response model correctness.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import UnansweredStatus


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestRouterImport:
    """Verify the learning API router is importable and correctly configured."""

    def test_router_importable(self):
        from app.api.v1.learning import router

        assert router is not None

    def test_router_prefix(self):
        from app.api.v1.learning import router

        assert router.prefix == "/learning"

    def test_router_tags(self):
        from app.api.v1.learning import router

        assert "learning" in router.tags


# ---------------------------------------------------------------------------
# Route definition tests
# ---------------------------------------------------------------------------


class TestRouteDefinitions:
    """Verify all required routes are defined with correct methods."""

    def _get_routes(self):
        from app.api.v1.learning import router

        routes = []
        for route in router.routes:
            if hasattr(route, "path") and hasattr(route, "methods"):
                routes.append((route.path, route.methods))
        return routes

    def test_list_questions_route(self):
        routes = self._get_routes()
        assert any(
            "/learning/questions" == path and "GET" in methods
            for path, methods in routes
        )

    def test_get_question_route(self):
        routes = self._get_routes()
        assert any(
            "/learning/questions/{question_id}" == path and "GET" in methods
            for path, methods in routes
        )

    def test_generate_route(self):
        routes = self._get_routes()
        assert any(
            "/learning/questions/{question_id}/generate" == path
            and "POST" in methods
            for path, methods in routes
        )

    def test_approve_route(self):
        routes = self._get_routes()
        assert any(
            "/learning/questions/{question_id}/approve" == path
            and "POST" in methods
            for path, methods in routes
        )

    def test_reject_route(self):
        routes = self._get_routes()
        assert any(
            "/learning/questions/{question_id}/reject" == path
            and "POST" in methods
            for path, methods in routes
        )

    def test_edit_route(self):
        routes = self._get_routes()
        assert any(
            "/learning/questions/{question_id}/edit" == path
            and "POST" in methods
            for path, methods in routes
        )

    def test_stats_route(self):
        routes = self._get_routes()
        assert any(
            "/learning/stats" == path and "GET" in methods
            for path, methods in routes
        )

    def test_total_route_count(self):
        """7 endpoints total: list, get, generate, approve, reject, edit, stats."""
        routes = self._get_routes()
        assert len(routes) == 7


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemaImports:
    """Verify learning-specific schemas are importable and validate correctly."""

    def test_approve_request_importable(self):
        from app.schemas.learning import ApproveRequest

        req = ApproveRequest()
        assert req.proposed_answer is None
        assert req.review_note is None

    def test_approve_request_with_override(self):
        from app.schemas.learning import ApproveRequest

        req = ApproveRequest(
            proposed_answer="La réponse corrigée.",
            review_note="Corrigée manuellement",
        )
        assert req.proposed_answer == "La réponse corrigée."
        assert req.review_note == "Corrigée manuellement"

    def test_reject_request_importable(self):
        from app.schemas.learning import RejectRequest

        req = RejectRequest(review_note="Hors périmètre")
        assert req.review_note == "Hors périmètre"

    def test_reject_request_allows_none_note(self):
        from app.schemas.learning import RejectRequest

        req = RejectRequest()
        assert req.review_note is None

    def test_edit_request_requires_answer(self):
        from app.schemas.learning import EditRequest

        req = EditRequest(proposed_answer="Nouvelle réponse")
        assert req.proposed_answer == "Nouvelle réponse"

    def test_edit_request_rejects_empty_answer(self):
        from app.schemas.learning import EditRequest

        with pytest.raises(Exception):
            EditRequest(proposed_answer="")

    def test_learning_stats_response(self):
        from app.schemas.learning import LearningStatsResponse

        stats = LearningStatsResponse(
            total=100,
            by_status={
                "pending": 50,
                "approved": 20,
                "modified": 10,
                "rejected": 15,
                "injected": 5,
            },
            approval_rate=0.6667,
            avg_review_time_hours=2.5,
            top_questions=[
                {"id": str(uuid.uuid4()), "question": "Test?", "frequency": 5},
            ],
        )
        assert stats.total == 100
        assert stats.by_status["pending"] == 50
        assert stats.approval_rate == 0.6667


# ---------------------------------------------------------------------------
# Response schema reuse tests
# ---------------------------------------------------------------------------


class TestResponseSchemas:
    """Verify that response schemas from feedback.py work for learning data."""

    def test_unanswered_question_response_from_attributes(self):
        from app.schemas.feedback import UnansweredQuestionResponse

        # Simulate ORM model attributes
        class FakeQuestion:
            id = uuid.uuid4()
            question = "Comment créer une entreprise ?"
            language = "fr"
            frequency = 3
            proposed_answer = "Pour créer une entreprise..."
            status = UnansweredStatus.approved
            reviewed_by = uuid.uuid4()
            review_note = None
            source_conversation_id = None
            created_at = "2026-01-01T00:00:00"
            updated_at = "2026-01-02T00:00:00"

        resp = UnansweredQuestionResponse.model_validate(FakeQuestion())
        assert resp.question == "Comment créer une entreprise ?"
        assert resp.status == UnansweredStatus.approved

    def test_unanswered_question_list_schema(self):
        from app.schemas.feedback import UnansweredQuestionList

        data = UnansweredQuestionList(
            items=[],
            total=0,
            page=1,
            page_size=20,
        )
        assert data.total == 0
        assert data.page == 1


# ---------------------------------------------------------------------------
# Router registration test
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    """Verify the learning router is registered in the main app."""

    def test_learning_router_in_main_app(self):
        from app.main import app

        paths = []
        for route in app.routes:
            if hasattr(route, "path"):
                paths.append(route.path)

        assert any("/api/v1/learning" in p for p in paths)
