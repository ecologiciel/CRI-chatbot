"""Prompt templates for RAG generation — system prompts, context formatting, messages.

All prompts are trilingual (FR/AR/EN) per CLAUDE.md §6.3 and §14.
System prompts enforce institutional tone for CRI communications.
XML tags separate system instructions, RAG chunks, and user messages
for guardrail sandboxing per CLAUDE.md §5.2.
"""

from __future__ import annotations

from app.schemas.rag import ConversationTurn, RetrievedChunk


class PromptTemplates:
    """Centralized prompt templates for RAG generation.

    All templates enforce:
    - Institutional CRI tone (formal, respectful, vouvoiement)
    - XML-tagged context separation (guardrail sandboxing)
    - No PII in prompts (anonymization is caller's responsibility)
    """

    # ------------------------------------------------------------------
    # System prompts per language
    # ------------------------------------------------------------------

    SYSTEM_PROMPTS: dict[str, str] = {
        "fr": (
            "Tu es l'assistant virtuel du Centre Régional d'Investissement (CRI).\n"
            "Ton rôle est d'aider les investisseurs et porteurs de projets avec des "
            "informations précises sur :\n"
            "- Les procédures administratives (création d'entreprise, autorisations, etc.)\n"
            "- Les délais et documents requis\n"
            "- Les services du CRI et ses guichets\n"
            "- Les incitations et aides à l'investissement\n\n"
            "RÈGLES STRICTES :\n"
            "1. Réponds UNIQUEMENT à partir des informations fournies dans le contexte ci-dessous.\n"
            "2. Si l'information n'est pas dans le contexte, dis-le clairement et propose "
            "de contacter le CRI.\n"
            "3. Utilise un ton formel, respectueux et institutionnel. Vouvoiement obligatoire.\n"
            "4. Ne donne JAMAIS de conseils juridiques ou fiscaux personnalisés.\n"
            "5. Si on te demande des informations personnelles (CIN, dossier), renvoie "
            "vers le module de suivi sécurisé.\n"
            "6. Réponds en français."
        ),
        "ar": (
            "أنت المساعد الافتراضي للمركز الجهوي للاستثمار (CRI).\n"
            "دورك هو مساعدة المستثمرين وحاملي المشاريع بمعلومات دقيقة حول:\n"
            "- الإجراءات الإدارية (إنشاء شركة، التراخيص، إلخ)\n"
            "- الآجال والوثائق المطلوبة\n"
            "- خدمات المركز الجهوي للاستثمار\n"
            "- الحوافز والمساعدات الاستثمارية\n\n"
            "قواعد صارمة:\n"
            "1. أجب فقط بناءً على المعلومات المقدمة في السياق أدناه.\n"
            "2. إذا لم تكن المعلومة متوفرة، قل ذلك بوضوح واقترح الاتصال بالمركز.\n"
            "3. استخدم أسلوباً رسمياً ومحترماً.\n"
            "4. لا تقدم أبداً استشارات قانونية أو ضريبية شخصية.\n"
            "5. إذا طُلب منك معلومات شخصية (رقم البطاقة، ملف)، أحل على وحدة التتبع الآمنة.\n"
            "6. أجب بالعربية الفصحى."
        ),
        "en": (
            "You are the virtual assistant of the Regional Investment Center (CRI).\n"
            "Your role is to help investors and project holders with accurate information about:\n"
            "- Administrative procedures (company creation, permits, etc.)\n"
            "- Deadlines and required documents\n"
            "- CRI services and counters\n"
            "- Investment incentives and support\n\n"
            "STRICT RULES:\n"
            "1. Answer ONLY based on the context provided below.\n"
            "2. If the information is not in the context, clearly state so and suggest "
            "contacting the CRI.\n"
            "3. Use a formal, respectful, and institutional tone.\n"
            "4. NEVER provide personalized legal or tax advice.\n"
            "5. If asked for personal information (ID, case file), redirect to the "
            "secure tracking module.\n"
            "6. Answer in English."
        ),
    }

    # ------------------------------------------------------------------
    # Context template with XML tags for guardrail sandboxing
    # ------------------------------------------------------------------

    CONTEXT_TEMPLATE = (
        "<context>\n{chunks_text}\n</context>\n\n"
        "<history>\n{history_text}\n</history>\n\n"
        "<question>\n{query}\n</question>"
    )

    # ------------------------------------------------------------------
    # Multilingual system messages
    # ------------------------------------------------------------------

    MESSAGES: dict[str, dict[str, str]] = {
        "no_answer": {
            "fr": (
                "Je ne dispose pas d'informations suffisantes pour répondre à cette "
                "question. Je vous invite à contacter directement le CRI au "
                "05 37 77 64 00 ou à vous rendre à nos guichets."
            ),
            "ar": (
                "لا أملك معلومات كافية للإجابة على هذا السؤال. أدعوكم للاتصال "
                "مباشرة بالمركز الجهوي للاستثمار."
            ),
            "en": (
                "I don't have sufficient information to answer this question. "
                "Please contact the CRI directly at 05 37 77 64 00 or visit our counters."
            ),
        },
        "disclaimer": {
            "fr": (
                "⚠️ Cette réponse est basée sur des informations partielles. "
                "Je vous recommande de vérifier auprès du CRI pour confirmation."
            ),
            "ar": (
                "⚠️ هذه الإجابة مبنية على معلومات جزئية. "
                "ننصحكم بالتحقق لدى المركز الجهوي للاستثمار."
            ),
            "en": (
                "⚠️ This answer is based on partial information. "
                "I recommend verifying with the CRI for confirmation."
            ),
        },
        "out_of_scope": {
            "fr": (
                "Cette question ne relève pas de mon domaine de compétence. "
                "Je suis spécialisé dans les procédures d'investissement et "
                "les services du CRI."
            ),
            "ar": (
                "هذا السؤال خارج نطاق اختصاصي. "
                "أنا متخصص في إجراءات الاستثمار وخدمات المركز."
            ),
            "en": (
                "This question is outside my area of expertise. "
                "I specialize in investment procedures and CRI services."
            ),
        },
        "greeting": {
            "fr": (
                "Bonjour ! Je suis l'assistant virtuel du CRI. "
                "Comment puis-je vous aider aujourd'hui ?"
            ),
            "ar": (
                "مرحباً! أنا المساعد الافتراضي للمركز الجهوي للاستثمار. "
                "كيف يمكنني مساعدتكم؟"
            ),
            "en": (
                "Hello! I'm the CRI virtual assistant. "
                "How can I help you today?"
            ),
        },
        "feedback_request": {
            "fr": "Cette réponse vous a-t-elle été utile ?",
            "ar": "هل كانت هذه الإجابة مفيدة لكم؟",
            "en": "Was this answer helpful?",
        },
    }

    # ------------------------------------------------------------------
    # Role labels for history formatting
    # ------------------------------------------------------------------

    _ROLE_LABELS: dict[str, dict[str, str]] = {
        "user": {"fr": "Utilisateur", "ar": "المستخدم", "en": "User"},
        "assistant": {"fr": "Assistant", "ar": "المساعد", "en": "Assistant"},
    }

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def get_system_prompt(cls, language: str) -> str:
        """Return system prompt for the given language, defaulting to French."""
        return cls.SYSTEM_PROMPTS.get(language, cls.SYSTEM_PROMPTS["fr"])

    @classmethod
    def get_message(cls, key: str, language: str) -> str:
        """Return a system message by key and language, defaulting to French."""
        messages = cls.MESSAGES.get(key, {})
        return messages.get(language, messages.get("fr", ""))

    @classmethod
    def build_context(
        cls,
        chunks: list[RetrievedChunk],
        history: list[ConversationTurn],
        query: str,
        language: str = "fr",
    ) -> str:
        """Build the user-facing prompt with XML-tagged sections.

        Args:
            chunks: Retrieved and anonymized chunks.
            history: Truncated conversation history.
            query: Current user question.
            language: For role labels in history.

        Returns:
            Formatted prompt string for ``GeminiRequest.contents``.
        """
        # Format chunks with source titles and scores
        chunk_parts: list[str] = []
        for chunk in chunks:
            title = chunk.metadata.get("title", "Document")
            chunk_parts.append(
                f"[Source: {title} | score: {chunk.score:.2f}]\n{chunk.content}"
            )
        chunks_text = "\n\n---\n\n".join(chunk_parts) if chunk_parts else "Aucun contexte disponible."

        # Format conversation history with localized role labels
        if history:
            history_lines: list[str] = []
            for turn in history:
                label = cls._ROLE_LABELS.get(turn.role, {}).get(language, turn.role)
                history_lines.append(f"{label}: {turn.content}")
            history_text = "\n".join(history_lines)
        else:
            history_text = "Aucun historique."

        return cls.CONTEXT_TEMPLATE.format(
            chunks_text=chunks_text,
            history_text=history_text,
            query=query,
        )
