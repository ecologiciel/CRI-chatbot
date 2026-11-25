"""Prompt templates for RAG generation — system prompts, context formatting, messages.

All prompts are trilingual (FR/AR/EN) per CLAUDE.md §6.3 and §14.
System prompts enforce an institutional tone.
XML tags separate system instructions, RAG chunks, and user messages
for guardrail sandboxing per CLAUDE.md §5.2.
"""

from __future__ import annotations

from app.schemas.rag import ConversationTurn, RetrievedChunk


class PromptTemplates:
    """Centralized prompt templates for RAG generation.

    All templates enforce:
    - Institutional tone (formal, respectful, vouvoiement)
    - XML-tagged context separation (guardrail sandboxing)
    - No PII in prompts (anonymization is caller's responsibility)
    """

    # ------------------------------------------------------------------
    # System prompts per language
    # ------------------------------------------------------------------

    SYSTEM_PROMPTS: dict[str, str] = {
        "fr": (
            "Tu es un assistant documentaire institutionnel.\n"
            "Ton rôle est d'aider les usagers en utilisant les documents de l'institution.\n\n"
            "RÈGLES STRICTES :\n"
            "1. Réponds UNIQUEMENT à partir des informations fournies dans le contexte ci-dessous.\n"
            "2. Si l'information n'est pas dans le contexte, dis-le clairement et propose "
            "de contacter l'institution par ses canaux officiels.\n"
            "3. Utilise un ton formel, respectueux et institutionnel. Vouvoiement obligatoire.\n"
            "4. Ne donne JAMAIS de conseils juridiques ou fiscaux personnalisés.\n"
            "5. Si on te demande des informations personnelles (CIN, dossier), renvoie "
            "vers les canaux officiels de l'institution.\n"
            "6. Réponds en français."
        ),
        "ar": (
            "أنت مساعد وثائقي مؤسساتي. دورك مساعدة المستعملين اعتماداً على وثائق المؤسسة.\n\n"
            "قواعد صارمة:\n"
            "1. أجب فقط بناءً على المعلومات المقدمة في السياق أدناه.\n"
            "2. إذا لم تكن المعلومة متوفرة، قل ذلك بوضوح واقترح الاتصال بالمؤسسة عبر قنواتها الرسمية.\n"
            "3. استخدم أسلوباً رسمياً ومحترماً.\n"
            "4. لا تقدم أبداً استشارات قانونية أو ضريبية شخصية.\n"
            "5. إذا طُلب منك معلومات شخصية (رقم البطاقة، ملف)، أحل على القنوات الرسمية للمؤسسة.\n"
            "6. أجب بالعربية الفصحى."
        ),
        "en": (
            "You are an institutional document assistant. Help users using the institution's documents.\n\n"
            "STRICT RULES:\n"
            "1. Answer ONLY based on the context provided below.\n"
            "2. If the information is not in the context, clearly state so and suggest "
            "contacting the institution through its official channels.\n"
            "3. Use a formal, respectful, and institutional tone.\n"
            "4. NEVER provide personalized legal or tax advice.\n"
            "5. If asked for personal information (ID, case file), redirect to the "
            "institution's official channels.\n"
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
                "question. Veuillez contacter l'institution par ses canaux officiels."
            ),
            "ar": (
                "لا أملك معلومات كافية للإجابة على هذا السؤال. أدعوكم للاتصال "
                "بالمؤسسة عبر قنواتها الرسمية."
            ),
            "en": (
                "I don't have sufficient information to answer this question. "
                "Please contact the institution through its official channels."
            ),
        },
        "disclaimer": {
            "fr": (
                "⚠️ Cette réponse est basée sur des informations partielles. "
                "Je vous recommande de vérifier auprès de l'institution pour confirmation."
            ),
            "ar": ("⚠️ هذه الإجابة مبنية على معلومات جزئية. " "ننصحكم بالتحقق لدى المؤسسة."),
            "en": (
                "⚠️ This answer is based on partial information. "
                "I recommend verifying with the institution for confirmation."
            ),
        },
        "out_of_scope": {
            "fr": (
                "Cette question ne relève pas de mon domaine de compétence. "
                "Je peux répondre aux questions couvertes par les documents disponibles."
            ),
            "ar": ("هذا السؤال خارج نطاق اختصاصي. يمكنني الإجابة استناداً إلى الوثائق المتاحة."),
            "en": (
                "This question is outside my area of expertise. "
                "I can answer questions covered by the available documents."
            ),
        },
        "greeting": {
            "fr": (
                "Bonjour ! Je suis l'assistant documentaire. "
                "Comment puis-je vous aider aujourd'hui ?"
            ),
            "ar": "مرحباً! أنا المساعد الوثائقي. كيف يمكنني مساعدتكم؟",
            "en": "Hello! I'm the document assistant. How can I help you today?",
        },
        "feedback_request": {
            "fr": "Cette réponse vous a-t-elle été utile ?",
            "ar": "هل كانت هذه الإجابة مفيدة لكم؟",
            "en": "Was this answer helpful?",
        },
        "feedback_ack_positive": {
            "fr": "Merci pour votre retour positif !",
            "ar": "شكراً لتقييمكم الإيجابي!",
            "en": "Thank you for your positive feedback!",
        },
        "feedback_ack_negative": {
            "fr": "Merci pour votre retour. Nous allons améliorer nos réponses.",
            "ar": "شكراً لملاحظاتكم. سنعمل على تحسين إجاباتنا.",
            "en": "Thank you for your feedback. We will improve our responses.",
        },
        "feedback_ack_question": {
            "fr": "Je vous mets en relation avec un conseiller. Veuillez patienter.",
            "ar": "سأقوم بتحويلكم إلى مستشار. يرجى الانتظار.",
            "en": "I'm connecting you with an advisor. Please wait.",
        },
        "rate_limit_user": {
            "fr": ("Veuillez patienter quelques instants avant " "d'envoyer un nouveau message."),
            "ar": "يرجى الانتظار لحظات قبل إرسال رسالة جديدة.",
            "en": "Please wait a moment before sending another message.",
        },
        "quota_exhausted": {
            "fr": (
                "Le service de messagerie a atteint sa limite. "
                "Veuillez contacter l'institution par ses canaux officiels."
            ),
            "ar": "وصلت خدمة الرسائل إلى حدها الأقصى. يرجى الاتصال بالمؤسسة عبر قنواتها الرسمية.",
            "en": (
                "The messaging service has reached its limit. "
                "Please contact the institution through its official channels."
            ),
        },
        "error_generic": {
            "fr": "Une erreur est survenue. Veuillez réessayer dans quelques instants.",
            "ar": "حدث خطأ. يرجى المحاولة مرة أخرى بعد قليل.",
            "en": "An error occurred. Please try again in a moment.",
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
            chunk_parts.append(f"[Source: {title} | score: {chunk.score:.2f}]\n{chunk.content}")
        chunks_text = (
            "\n\n---\n\n".join(chunk_parts) if chunk_parts else "Aucun contexte disponible."
        )

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

    @classmethod
    def format_sources_message(cls, sources: list[dict], language: str = "fr") -> str:
        """Render citations without calling an LLM; WhatsApp receives max three entries."""
        if not sources:
            return {
                "fr": "Je ne dispose pas de source vérifiable pour la dernière réponse. Veuillez contacter l'institution.",
                "ar": "لا تتوفر لدي مراجع قابلة للتحقق للإجابة الأخيرة. يرجى الاتصال بالمؤسسة.",
                "en": "No verifiable source is available for the last answer. Please contact the institution.",
            }.get(language, "Je ne dispose pas de source vérifiable pour la dernière réponse.")

        lines = {
            "fr": ["Sources de la dernière réponse :"],
            "ar": ["مصادر الإجابة الأخيرة:"],
            "en": ["Sources for the last answer:"],
        }.get(language, ["Sources :"])
        for index, source in enumerate(sources[:3], start=1):
            details = [source.get("title") or "Document"]
            if source.get("version"):
                details.append(f"v{source['version']}")
            if source.get("published_at"):
                details.append(str(source["published_at"]))
            if source.get("authority"):
                details.append(str(source["authority"]))
            reference = source.get("url") or source.get("reference")
            line = f"{index}. " + " — ".join(details)
            if reference:
                line += f"\n{reference}"
            lines.append(line)
        return "\n\n".join(lines)
