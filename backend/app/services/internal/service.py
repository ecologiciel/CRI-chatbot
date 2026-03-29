"""InternalAgentService — business logic for the CRI internal agent (Agent 2).

Provides read-only consultation capabilities for CRI employees
authenticated via WhatsApp phone whitelist. No orchestrator imports
(avoids circular dependencies).

Capabilities:
- Whitelist verification (direct DB lookup, no cache)
- Dashboard statistics (conversations, contacts, unanswered questions)
- FAQ search (same RAG pipeline as public agent, internal-oriented prompt)
- Natural language report generation via Gemini
"""

from __future__ import annotations

import structlog
from sqlalchemy import func, select

from app.core.tenant import TenantContext
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.feedback import UnansweredQuestion
from app.models.whitelist import InternalWhitelist
from app.schemas.rag import GenerationRequest
from app.services.ai.gemini import GeminiService, get_gemini_service
from app.services.audit.service import AuditService, get_audit_service
from app.services.rag.generation import GenerationService, get_generation_service
from app.services.rag.prompts import PromptTemplates
from app.services.rag.retrieval import RetrievalService, get_retrieval_service

logger = structlog.get_logger()

# Valid sub-intents for the internal agent
_VALID_SUB_INTENTS = {"stats", "faq", "report"}

REFUSAL_MESSAGES: dict[str, str] = {
    "fr": (
        "Désolé, ce service est réservé aux collaborateurs du CRI. "
        "Si vous êtes un investisseur, je peux vous aider avec vos "
        "questions sur les procédures et incitations."
    ),
    "ar": (
        "عذرًا، هذه الخدمة مخصصة لموظفي المركز الجهوي للاستثمار. "
        "إذا كنت مستثمرًا، يمكنني مساعدتك في أسئلتك حول الإجراءات والحوافز."
    ),
    "en": (
        "Sorry, this service is reserved for CRI staff members. "
        "If you are an investor, I can help you with questions "
        "about procedures and incentives."
    ),
}

WELCOME_MESSAGES: dict[str, str] = {
    "fr": (
        "Bonjour ! Vous êtes connecté en tant que collaborateur CRI. "
        "Je peux vous fournir :\n"
        "• Statistiques du jour\n"
        "• Recherche dans la base de connaissances\n"
        "• Rapports à la demande\n\n"
        "Que souhaitez-vous consulter ?"
    ),
    "ar": (
        "مرحبًا! أنت متصل كموظف في المركز الجهوي للاستثمار. "
        "يمكنني تقديم:\n"
        "• إحصائيات اليوم\n"
        "• البحث في قاعدة المعرفة\n"
        "• تقارير عند الطلب\n\n"
        "ماذا تريد أن تطلع عليه؟"
    ),
    "en": (
        "Hello! You are connected as a CRI staff member. "
        "I can provide:\n"
        "• Today's statistics\n"
        "• Knowledge base search\n"
        "• On-demand reports\n\n"
        "What would you like to look up?"
    ),
}


class InternalAgentService:
    """Business logic for the CRI internal agent.

    All methods are read-only (R11 requirement). No write operations
    on dossiers, contacts, or any tenant data.

    Attributes:
        _retrieval: RAG retrieval service for chunk search.
        _generation: RAG generation service for answer synthesis.
        _gemini: Gemini service for sub-intent classification and reports.
        _audit: Audit service for access logging.
    """

    def __init__(
        self,
        retrieval: RetrievalService,
        generation: GenerationService,
        gemini: GeminiService,
        audit: AuditService,
    ) -> None:
        self._retrieval = retrieval
        self._generation = generation
        self._gemini = gemini
        self._audit = audit
        self._logger = logger.bind(service="internal_agent_service")

    # ------------------------------------------------------------------
    # Whitelist
    # ------------------------------------------------------------------

    async def verify_whitelist(
        self,
        tenant: TenantContext,
        phone: str,
    ) -> bool:
        """Check if a phone number is in the tenant's active whitelist.

        Direct DB lookup on every call — intentionally no cache for
        security (whitelist changes must take effect immediately).

        Args:
            tenant: Tenant context (DB schema selection).
            phone: E.164 phone number to check.

        Returns:
            True if the phone is whitelisted and active, False otherwise.
            Returns False on any DB error (fail-closed).
        """
        try:
            async with tenant.db_session() as session:
                result = await session.execute(
                    select(InternalWhitelist.id)
                    .where(
                        InternalWhitelist.phone == phone,
                        InternalWhitelist.is_active.is_(True),
                    )
                    .limit(1),
                )
                return result.scalar_one_or_none() is not None
        except Exception as exc:
            self._logger.error(
                "whitelist_check_failed",
                error=str(exc),
                tenant=tenant.slug,
            )
            return False  # fail-closed

    # ------------------------------------------------------------------
    # Sub-intent classification
    # ------------------------------------------------------------------

    async def classify_sub_intent(
        self,
        query: str,
        tenant: TenantContext,
    ) -> str:
        """Classify the internal user's query into a sub-intent.

        Uses Gemini with a minimal prompt (~10 output tokens).

        Args:
            query: User's message text.
            tenant: Tenant context for Gemini billing.

        Returns:
            One of: ``"stats"``, ``"faq"``, ``"report"``.
            Defaults to ``"faq"`` if classification is unclear.
        """
        system_prompt = (
            "Tu es un classificateur. L'utilisateur est un collaborateur CRI. "
            "Réponds UNIQUEMENT par un seul mot parmi: stats, faq, report\n"
            "- stats : demande de statistiques, chiffres, tableau de bord, combien\n"
            "- report : demande de rapport, synthèse, bilan, résumé des activités\n"
            "- faq : toute autre question sur les procédures, la réglementation, etc."
        )
        try:
            raw = await self._gemini.generate_simple(
                prompt=query,
                tenant=tenant,
                system_prompt=system_prompt,
            )
            sub_intent = raw.strip().lower()
            if sub_intent not in _VALID_SUB_INTENTS:
                self._logger.info(
                    "sub_intent_unknown_fallback",
                    raw=sub_intent,
                    tenant=tenant.slug,
                )
                return "faq"
            return sub_intent
        except Exception as exc:
            self._logger.error(
                "sub_intent_classification_failed",
                error=str(exc),
                tenant=tenant.slug,
            )
            return "faq"

    # ------------------------------------------------------------------
    # Dashboard stats
    # ------------------------------------------------------------------

    async def get_dashboard_stats(
        self,
        tenant: TenantContext,
    ) -> dict:
        """Retrieve simplified dashboard statistics for the tenant.

        All queries are read-only on the tenant schema.

        Args:
            tenant: Tenant context for DB schema selection.

        Returns:
            Dict with keys: total_conversations, pending_unanswered,
            total_contacts.
        """
        async with tenant.db_session() as session:
            conv_count = await session.execute(
                select(func.count(Conversation.id)),
            )
            unanswered_count = await session.execute(
                select(func.count(UnansweredQuestion.id)).where(
                    UnansweredQuestion.status == "pending",
                ),
            )
            contact_count = await session.execute(
                select(func.count(Contact.id)),
            )

        return {
            "total_conversations": conv_count.scalar_one(),
            "pending_unanswered": unanswered_count.scalar_one(),
            "total_contacts": contact_count.scalar_one(),
        }

    # ------------------------------------------------------------------
    # FAQ search (RAG pipeline)
    # ------------------------------------------------------------------

    async def search_faq(
        self,
        tenant: TenantContext,
        query: str,
        language: str,
        conversation_history: list[dict] | None = None,
    ) -> dict:
        """Search the knowledge base using the same RAG pipeline as FAQAgent.

        The only difference from the public agent is the system prompt
        context: responses are framed for a CRI collaborator (more
        technical, no marketing tone).

        Args:
            tenant: Tenant context for Qdrant collection and Gemini billing.
            query: User's question.
            language: Detected language code.
            conversation_history: Recent messages for context.

        Returns:
            Dict with: response, confidence, chunk_ids, retrieved_chunks.
        """
        retrieval_result = await self._retrieval.retrieve(
            tenant, query, language=language,
        )

        if not retrieval_result.chunks:
            return {
                "response": PromptTemplates.get_message("no_answer", language),
                "confidence": 0.0,
                "chunk_ids": [],
                "retrieved_chunks": [],
            }

        gen_request = GenerationRequest(
            query=query,
            language=language,
            conversation_history=conversation_history or [],
            chunks=retrieval_result.chunks,
        )
        gen_response = await self._generation.generate(tenant, gen_request)

        return {
            "response": gen_response.answer,
            "confidence": gen_response.confidence,
            "chunk_ids": gen_response.chunk_ids,
            "retrieved_chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "content": c.content[:200],
                    "score": c.score,
                }
                for c in retrieval_result.chunks
            ],
        }

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    async def generate_report(
        self,
        tenant: TenantContext,
        query: str,
        language: str,
    ) -> str:
        """Generate a natural language report from tenant statistics.

        Fetches dashboard stats, then asks Gemini to produce a human-readable
        report in the requested language. Read-only — Gemini cannot modify data.

        Args:
            tenant: Tenant context.
            query: User's report request in natural language.
            language: Target language for the report.

        Returns:
            Generated report text.
        """
        stats = await self.get_dashboard_stats(tenant)

        lang_label = {"fr": "français", "ar": "arabe", "en": "anglais"}.get(
            language, "français",
        )
        system_prompt = (
            f"Tu es un assistant analytique du Centre Régional d'Investissement. "
            f"Réponds en {lang_label}. "
            f"Génère un rapport concis et professionnel basé sur les données fournies. "
            f"Ne fabrique AUCUNE donnée — utilise uniquement les chiffres fournis."
        )
        prompt = (
            f"Données du tenant '{tenant.name}':\n"
            f"- Conversations totales: {stats['total_conversations']}\n"
            f"- Questions non répondues en attente: {stats['pending_unanswered']}\n"
            f"- Contacts totaux: {stats['total_contacts']}\n\n"
            f"Demande de l'utilisateur: {query}"
        )

        return await self._gemini.generate_simple(
            prompt=prompt,
            tenant=tenant,
            system_prompt=system_prompt,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_internal_agent_service: InternalAgentService | None = None


def get_internal_agent_service() -> InternalAgentService:
    """Get or create the InternalAgentService singleton."""
    global _internal_agent_service  # noqa: PLW0603
    if _internal_agent_service is None:
        _internal_agent_service = InternalAgentService(
            retrieval=get_retrieval_service(),
            generation=get_generation_service(),
            gemini=get_gemini_service(),
            audit=get_audit_service(),
        )
    return _internal_agent_service
