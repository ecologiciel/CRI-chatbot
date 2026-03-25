---
name: gemini-integration
description: |
  Use this skill when writing any code that calls Google Gemini APIs for the CRI chatbot platform.
  Triggers: any mention of 'Gemini', 'LLM', 'AI generation', 'text generation', 'multimodal',
  'image analysis', 'audio transcription', 'language detection', 'intent classification',
  'structured output', 'token count', 'embeddings', 'text-embedding-004', 'Gemini Flash',
  'AI service', 'prompt engineering', or any work in services/ai/ directory.
  CRITICAL: Always use 'gemini-2.5-flash' — Gemini 2.0 Flash is deprecated (removal June 1, 2026).
  Do NOT use for non-Gemini LLM integrations.
---

# Google Gemini 2.5 Flash Integration — CRI Chatbot Platform

## CRITICAL REMINDERS

1. **ALWAYS use `gemini-2.5-flash`** — Gemini 2.0 Flash is deprecated (removed June 1, 2026)
2. **NEVER send PII to Gemini** — all inputs must be anonymized (CIN, phone, names, amounts)
3. **All Gemini calls are async** — use `generate_content_async()`
4. **Gemini API key is a secret** — loaded via pydantic-settings, never hardcoded
5. **Data use policy**: Google Gemini API does NOT use paid API data for training (verify in ToS)
6. **No GPU on-premise** — architecture uses Gemini cloud API only (clarification R5)

## 1. Client Setup (`services/ai/gemini.py`)

```python
import google.generativeai as genai
from app.core.config import Settings

class GeminiService:
    """Async Gemini client with retry logic and cost tracking."""

    def __init__(self, settings: Settings):
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash")
        self.embedding_model = "models/text-embedding-004"

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        system_instruction: str | None = None,
        response_mime_type: str | None = None,
    ) -> GeminiResponse:
        """Generate text with Gemini 2.5 Flash.

        Args:
            prompt: User prompt (already anonymized)
            temperature: 0.0-1.0 (lower = more factual)
            max_tokens: Max output tokens
            system_instruction: System-level instructions
            response_mime_type: "application/json" for structured output

        Returns:
            GeminiResponse with text, usage, and latency
        """
        config = genai.GenerationConfig(
            temperature=temperature,
            top_p=0.9,
            max_output_tokens=max_tokens,
        )
        if response_mime_type:
            config.response_mime_type = response_mime_type

        model = self.model
        if system_instruction:
            model = genai.GenerativeModel(
                "gemini-2.5-flash",
                system_instruction=system_instruction,
            )

        start = time.monotonic()
        response = await model.generate_content_async(
            prompt,
            generation_config=config,
            safety_settings=self._safety_settings(),
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        return GeminiResponse(
            text=response.text,
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count,
            latency_ms=latency_ms,
            finish_reason=response.candidates[0].finish_reason.name,
        )

    def _safety_settings(self) -> list[dict]:
        """Permissive safety for institutional content. CRI content is safe."""
        return [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
        ]
```

## 2. Use Cases in CRI Platform

### 2.1 RAG Response Generation (Primary Use Case)

```python
# Temperature: 0.3 (factual, grounded in context)
# Max tokens: 1024
# System instruction: CRI assistant role + language + guardrails
response = await gemini.generate(
    prompt=rag_prompt,  # Built by rag-pipeline skill
    temperature=0.3,
    max_tokens=1024,
    system_instruction=CRI_SYSTEM_PROMPT,
)
```

### 2.2 Intent Classification (~50 tokens/call)

```python
async def classify_intent(
    message: str,
    language: str,
) -> Intent:
    """Classify user message intent. Fast and cheap (~50 tokens).

    Possible intents:
    - faq: General question about CRI procedures/services
    - incentives: Question about investment incentives/aids
    - tracking: Dossier tracking/status query
    - internal: Internal CRI query (from whitelisted numbers)
    - escalation: Explicit request for human agent
    - greeting: Hello/bonjour/مرحبا
    - out_of_scope: Not CRI-related
    - stop: Opt-out request
    """
    response = await gemini.generate(
        prompt=f"""Classifie l'intention de ce message WhatsApp envoyé au CRI.
Réponds UNIQUEMENT avec un mot parmi : faq, incentives, tracking, internal, escalation, greeting, out_of_scope, stop

Message ({language}): {message[:200]}""",
        temperature=0.0,
        max_tokens=10,
    )
    intent_str = response.text.strip().lower()
    return Intent(intent_str) if intent_str in Intent.__members__ else Intent.faq
```

### 2.3 Language Detection

```python
async def detect_language_gemini(text: str) -> str:
    """Detect language when heuristics are ambiguous."""
    response = await gemini.generate(
        prompt=f"What language is this text? Reply ONLY 'fr', 'ar', or 'en': {text[:150]}",
        temperature=0.0,
        max_tokens=5,
    )
    lang = response.text.strip().lower()
    return lang if lang in ("fr", "ar", "en") else "fr"
```

### 2.4 Structured Metadata Extraction

```python
async def extract_metadata(text: str) -> dict:
    """Extract structured metadata from KB chunk via Gemini."""
    response = await gemini.generate(
        prompt=METADATA_EXTRACTION_PROMPT.format(text=text),
        temperature=0.1,
        max_tokens=500,
        response_mime_type="application/json",  # Force JSON output
    )
    return json.loads(response.text)
```

### 2.5 Proposed Answer for Unanswered Questions

```python
async def generate_proposed_answer(question: str) -> str:
    """Generate a proposed answer for the supervised learning queue."""
    response = await gemini.generate(
        prompt=f"""En tant qu'expert des services CRI au Maroc, propose une réponse
à cette question d'investisseur. Si tu n'es pas sûr, écris "INCERTAIN".
Sois précis, factuel et concis.

Question: {question}""",
        temperature=0.5,
        max_tokens=500,
    )
    return response.text
```

### 2.6 Multimodal — Image Analysis

```python
async def analyze_image(
    image_bytes: bytes,
    mime_type: str,
    user_question: str,
    language: str,
) -> str:
    """Analyze an image sent via WhatsApp using Gemini's multimodal capability.

    Use cases: reading a document photo, analyzing a business plan image, etc.
    """
    image_part = {
        "inline_data": {
            "mime_type": mime_type,  # image/jpeg, image/png
            "data": base64.b64encode(image_bytes).decode(),
        }
    }

    response = await gemini.model.generate_content_async(
        [
            f"Tu es l'assistant du CRI. L'utilisateur a envoyé cette image avec la question: {user_question}. Réponds en {language}.",
            image_part,
        ],
        generation_config=genai.GenerationConfig(
            temperature=0.3,
            max_output_tokens=1024,
        ),
    )
    return response.text
```

### 2.7 Multimodal — Audio Transcription + Response

```python
async def process_audio(
    audio_bytes: bytes,
    mime_type: str,
    language: str,
) -> tuple[str, str]:
    """Transcribe WhatsApp voice message and generate response.

    Returns: (transcription, response)
    """
    audio_part = {
        "inline_data": {
            "mime_type": mime_type,  # audio/ogg for WhatsApp voice
            "data": base64.b64encode(audio_bytes).decode(),
        }
    }

    # Step 1: Transcribe
    transcription_response = await gemini.model.generate_content_async(
        ["Transcris ce message audio. Réponds UNIQUEMENT avec la transcription.", audio_part],
        generation_config=genai.GenerationConfig(temperature=0.0, max_output_tokens=500),
    )
    transcription = transcription_response.text

    # Step 2: Process as text query through the RAG pipeline
    # (handled by the orchestrator, not here)
    return transcription, transcription
```

## 3. Embeddings (`services/ai/embeddings.py`)

### 3.1 Google text-embedding-004

```python
async def embed_texts(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Generate embeddings using Google text-embedding-004.

    Dimensions: 768
    Max input: 2,048 tokens per text
    Batch size: up to 100 texts

    task_type options:
    - RETRIEVAL_DOCUMENT: for indexing documents/chunks
    - RETRIEVAL_QUERY: for embedding user queries
    - SEMANTIC_SIMILARITY: for comparing texts
    - CLASSIFICATION: for classification tasks
    """
    result = await genai.embed_content_async(
        model="models/text-embedding-004",
        content=texts,
        task_type=task_type,
    )
    return [e["values"] for e in result["embedding"]]
```

### 3.2 Alternative: multilingual-e5-large (Local)

```python
from sentence_transformers import SentenceTransformer

class LocalEmbeddingService:
    """Local embedding model for offline/air-gapped scenarios."""

    def __init__(self):
        self.model = SentenceTransformer("intfloat/multilingual-e5-large")

    def embed(
        self, texts: list[str], is_query: bool = False
    ) -> list[list[float]]:
        """Embed texts. 1024 dimensions.

        IMPORTANT: Prefix queries with "query: " and documents with "passage: "
        """
        prefix = "query: " if is_query else "passage: "
        prefixed = [f"{prefix}{t}" for t in texts]
        return self.model.encode(prefixed, normalize_embeddings=True).tolist()
```

## 4. Cost Tracking & Monitoring

### 4.1 Per-Tenant Cost Estimation

```python
# Gemini 2.5 Flash pricing (as of 2025, verify for updates)
GEMINI_PRICING = {
    "gemini-2.5-flash": {
        "input_per_1k": 0.00015,   # $0.15 per 1M input tokens
        "output_per_1k": 0.0006,   # $0.60 per 1M output tokens
    },
    "text-embedding-004": {
        "per_1k": 0.000025,        # $0.025 per 1M characters
    },
}

async def track_gemini_usage(
    tenant: TenantContext,
    input_tokens: int,
    output_tokens: int,
    model: str = "gemini-2.5-flash",
) -> None:
    """Track token usage and estimated cost per tenant in Redis."""
    today = datetime.now().strftime("%Y-%m-%d")
    pricing = GEMINI_PRICING[model]
    cost = (
        (input_tokens / 1000) * pricing["input_per_1k"]
        + (output_tokens / 1000) * pricing["output_per_1k"]
    )

    # Increment daily counters
    pipe = redis.pipeline()
    pipe.incr(f"{tenant.redis_prefix}:gemini:tokens:input:{today}", input_tokens)
    pipe.incr(f"{tenant.redis_prefix}:gemini:tokens:output:{today}", output_tokens)
    pipe.incrbyfloat(f"{tenant.redis_prefix}:gemini:cost:{today}", cost)
    # Set TTL (7 days for daily counters)
    for key in [
        f"{tenant.redis_prefix}:gemini:tokens:input:{today}",
        f"{tenant.redis_prefix}:gemini:tokens:output:{today}",
        f"{tenant.redis_prefix}:gemini:cost:{today}",
    ]:
        pipe.expire(key, 604800)
    await pipe.execute()
```

### 4.2 Prometheus Metrics

```python
from prometheus_client import Counter, Histogram

gemini_requests_total = Counter(
    "gemini_requests_total",
    "Total Gemini API calls",
    ["tenant", "model", "use_case"],
)

gemini_latency_seconds = Histogram(
    "gemini_latency_seconds",
    "Gemini API latency in seconds",
    ["tenant", "model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

gemini_tokens_total = Counter(
    "gemini_tokens_total",
    "Total tokens consumed",
    ["tenant", "model", "direction"],  # direction: input/output
)

gemini_errors_total = Counter(
    "gemini_errors_total",
    "Gemini API errors",
    ["tenant", "model", "error_type"],
)
```

## 5. Error Handling & Retry Logic

```python
import tenacity
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable

class GeminiError(CRIBaseException):
    """Base Gemini error."""

class GeminiRateLimitError(GeminiError):
    """Gemini API rate limit exceeded."""

class GeminiContentFilterError(GeminiError):
    """Content blocked by Gemini safety filters."""

class GeminiTimeoutError(GeminiError):
    """Gemini API request timed out."""

@tenacity.retry(
    retry=tenacity.retry_if_exception_type(
        (ResourceExhausted, ServiceUnavailable, asyncio.TimeoutError)
    ),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, structlog.stdlib.INFO),
)
async def generate_with_retry(
    model: genai.GenerativeModel,
    prompt: str,
    config: genai.GenerationConfig,
) -> genai.types.GenerateContentResponse:
    """Generate with automatic retry on transient errors."""
    return await model.generate_content_async(prompt, generation_config=config)
```

## 6. LLM Trace Logging (PostgreSQL)

```python
async def log_llm_trace(
    tenant: TenantContext,
    use_case: str,
    prompt: str,
    response: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    intent: str | None = None,
    chunk_ids: list[str] | None = None,
    confidence_score: float | None = None,
) -> None:
    """Log every LLM call for debugging, audit, and optimization.

    Retention: 90 days (configurable).
    """
    async with tenant.db_session() as session:
        session.add(LLMTrace(
            use_case=use_case,  # "rag_generation", "intent_classification", etc.
            prompt=prompt[:10000],  # Truncate very long prompts
            response=response[:5000],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            model="gemini-2.5-flash",
            intent=intent,
            chunk_ids=chunk_ids,
            confidence_score=confidence_score,
        ))
        await session.commit()
```

## 7. Pydantic Schemas

```python
# app/schemas/ai.py

from pydantic import BaseModel, Field
from typing import Literal

class GeminiResponse(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    finish_reason: str  # "STOP", "MAX_TOKENS", "SAFETY", etc.

class Intent(str, Enum):
    faq = "faq"
    incentives = "incentives"
    tracking = "tracking"
    internal = "internal"
    escalation = "escalation"
    greeting = "greeting"
    out_of_scope = "out_of_scope"
    stop = "stop"

class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(..., max_length=100)
    task_type: Literal[
        "RETRIEVAL_DOCUMENT",
        "RETRIEVAL_QUERY",
        "SEMANTIC_SIMILARITY",
        "CLASSIFICATION",
    ] = "RETRIEVAL_DOCUMENT"
```

## 8. Prompt Templates Reference

| Use Case | Temperature | Max Tokens | System Instruction |
|---|---|---|---|
| RAG generation | 0.3 | 1024 | CRI assistant role + language + guardrails |
| Intent classification | 0.0 | 10 | None (inline instruction) |
| Language detection | 0.0 | 5 | None (inline instruction) |
| Metadata extraction | 0.1 | 500 | None (JSON output forced) |
| Proposed answer | 0.5 | 500 | CRI expert role |
| Re-ranking | 0.0 | 200 | None (JSON output forced) |
| Image analysis | 0.3 | 1024 | CRI assistant + multimodal context |
| Audio transcription | 0.0 | 500 | Transcription-only instruction |

## 9. Quick Reference — File Locations

| Component | Path |
|---|---|
| Gemini service | `backend/app/services/ai/gemini.py` |
| Embedding service | `backend/app/services/ai/embeddings.py` |
| Language detection | `backend/app/services/ai/language.py` |
| Intent classification | `backend/app/services/ai/intent.py` |
| LLM trace model | `backend/app/models/trace.py` |
| AI schemas | `backend/app/schemas/ai.py` |
| Config (API key) | `backend/app/core/config.py` → `Settings.gemini_api_key` |
| Prometheus metrics | `backend/app/core/metrics.py` |
