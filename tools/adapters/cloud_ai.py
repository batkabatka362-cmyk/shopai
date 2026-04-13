"""Cloud AI adapter for ShopAI — supports OpenAI and Anthropic with fallback."""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class CloudAIAdapter(BaseToolAdapter):
    tool_name = "cloud_ai"
    tool_category = "ai"
    version = "1.0.0"

    OPENAI_BASE = "https://api.openai.com/v1"
    ANTHROPIC_BASE = "https://api.anthropic.com/v1"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._openai_api_key: str = ""
        self._anthropic_api_key: str = ""
        self._primary_provider: str = "openai"  # "openai" or "anthropic"
        self._default_model: str = "gpt-4o"
        self._anthropic_model: str = "claude-sonnet-4-20250514"

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._openai_api_key = credentials.get("openai_api_key", "")
        self._anthropic_api_key = credentials.get("anthropic_api_key", "")
        self._primary_provider = credentials.get("primary_provider", "openai")
        self._default_model = credentials.get("openai_model", self._default_model)
        self._anthropic_model = credentials.get("anthropic_model", self._anthropic_model)
        # Fallback logic
        if self._primary_provider == "openai" and not self._openai_api_key and self._anthropic_api_key:
            self._primary_provider = "anthropic"
        elif self._primary_provider == "anthropic" and not self._anthropic_api_key and self._openai_api_key:
            self._primary_provider = "openai"

    def capabilities(self) -> list[str]:
        return [
            "chat_completion",
            "structured_output",
            "analyze_data",
            "generate_content",
            "summarize",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "chat_completion": self._chat_completion,
            "structured_output": self._structured_output,
            "analyze_data": self._analyze_data,
            "generate_content": self._generate_content,
            "summarize": self._summarize,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, data={}, error=f"Unknown action: {action}")
        start = time.monotonic()
        try:
            result = handler(params)
            elapsed = (time.monotonic() - start) * 1000
            cost = result.pop("_cost_usd", 0.0)
            return ToolResult(
                success=True,
                data=result,
                error=None,
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=cost,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        healthy = bool(self._openai_api_key or self._anthropic_api_key)
        latency = (time.monotonic() - start) * 1000 + 100.0
        errors = []
        if not self._openai_api_key:
            errors.append("OpenAI API key missing")
        if not self._anthropic_api_key:
            errors.append("Anthropic API key missing")
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error="; ".join(errors) if not healthy else None,
        )

    def get_rate_config(self) -> RateConfig:
        if self._primary_provider == "anthropic":
            return RateConfig(requests_per_second=5.0, burst=20, daily_quota=None)
        return RateConfig(requests_per_second=10.0, burst=60, daily_quota=None)

    # ── provider request builders ─────────────────────────────

    def _build_openai_request(self, messages: list, **kwargs) -> dict:
        model = kwargs.pop("model", self._default_model)
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        if kwargs.get("response_format"):
            payload["response_format"] = kwargs["response_format"]
        return {
            "provider": "openai",
            "endpoint": f"{self.OPENAI_BASE}/chat/completions",
            "method": "POST",
            "payload": payload,
        }

    def _build_anthropic_request(self, messages: list, **kwargs) -> dict:
        model = kwargs.pop("model", self._anthropic_model)
        system_msg = ""
        user_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg["content"]
            else:
                user_messages.append(msg)
        payload: dict = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", 2048),
            "messages": user_messages,
        }
        if system_msg:
            payload["system"] = system_msg
        return {
            "provider": "anthropic",
            "endpoint": f"{self.ANTHROPIC_BASE}/messages",
            "method": "POST",
            "payload": payload,
        }

    def _build_request(self, messages: list, **kwargs) -> dict:
        provider = kwargs.pop("provider", self._primary_provider)
        if provider == "anthropic":
            return self._build_anthropic_request(messages, **kwargs)
        return self._build_openai_request(messages, **kwargs)

    # ── cost estimation ───────────────────────────────────────

    @staticmethod
    def _estimate_cost(provider: str, input_tokens: int, output_tokens: int) -> float:
        rates = {
            "openai": (0.005 / 1000, 0.015 / 1000),
            "anthropic": (0.003 / 1000, 0.015 / 1000),
        }
        in_rate, out_rate = rates.get(provider, (0.005 / 1000, 0.015 / 1000))
        return input_tokens * in_rate + output_tokens * out_rate

    # ── handlers ──────────────────────────────────────────────

    def _chat_completion(self, params: dict) -> dict:
        if "messages" not in params:
            raise ValueError("messages is required")
        messages = params["messages"]
        request = self._build_request(
            messages,
            provider=params.get("provider", self._primary_provider),
            model=params.get("model"),
            temperature=params.get("temperature", 0.7),
            max_tokens=params.get("max_tokens", 2048),
        )
        est_input = sum(len(m.get("content", "")) // 4 for m in messages)
        request["request_id"] = str(uuid.uuid4())
        request["response"] = {"content": "", "finish_reason": None}
        request["_cost_usd"] = self._estimate_cost(request["provider"], est_input, 500)
        return request

    def _structured_output(self, params: dict) -> dict:
        if "messages" not in params or "schema" not in params:
            raise ValueError("messages and schema are required")
        messages = params["messages"]
        schema = params["schema"]
        request = self._build_request(
            messages,
            provider=params.get("provider", self._primary_provider),
            model=params.get("model"),
            temperature=params.get("temperature", 0.3),
            max_tokens=params.get("max_tokens", 2048),
            response_format={"type": "json_schema", "json_schema": schema},
        )
        est_input = sum(len(m.get("content", "")) // 4 for m in messages)
        request["request_id"] = str(uuid.uuid4())
        request["schema"] = schema
        request["response"] = {"parsed": {}, "finish_reason": None}
        request["_cost_usd"] = self._estimate_cost(request["provider"], est_input, 800)
        return request

    def _analyze_data(self, params: dict) -> dict:
        if "data" not in params:
            raise ValueError("data is required")
        analysis_type = params.get("analysis_type", "general")
        system_prompt = (
            f"You are a data analyst. Perform a {analysis_type} analysis on the provided data. "
            "Return structured insights with key findings, trends, and actionable recommendations."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Analyze this data:\n{params['data']}"},
        ]
        request = self._build_request(
            messages,
            provider=params.get("provider", self._primary_provider),
            temperature=0.3,
            max_tokens=params.get("max_tokens", 4096),
        )
        request["request_id"] = str(uuid.uuid4())
        request["analysis_type"] = analysis_type
        request["response"] = {"analysis": "", "insights": []}
        request["_cost_usd"] = self._estimate_cost(request["provider"], 2000, 1000)
        return request

    def _generate_content(self, params: dict) -> dict:
        if "content_type" not in params or "topic" not in params:
            raise ValueError("content_type and topic are required")
        content_type = params["content_type"]
        valid_types = ["product_description", "blog_post", "ad_copy", "email", "social_post", "seo_meta"]
        if content_type not in valid_types:
            raise ValueError(f"content_type must be one of: {', '.join(valid_types)}")
        system_prompt = (
            f"You are a professional copywriter. Generate a {content_type} "
            f"about: {params['topic']}. "
            f"Tone: {params.get('tone', 'professional')}. "
            f"Target audience: {params.get('audience', 'general')}."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": params.get("additional_context", f"Write a {content_type} about {params['topic']}")},
        ]
        request = self._build_request(
            messages,
            provider=params.get("provider", self._primary_provider),
            temperature=params.get("temperature", 0.8),
            max_tokens=params.get("max_tokens", 2048),
        )
        request["request_id"] = str(uuid.uuid4())
        request["content_type"] = content_type
        request["response"] = {"content": "", "finish_reason": None}
        request["_cost_usd"] = self._estimate_cost(request["provider"], 500, 1000)
        return request

    def _summarize(self, params: dict) -> dict:
        if "text" not in params:
            raise ValueError("text is required")
        max_length = params.get("max_length", "medium")
        length_tokens = {"short": 256, "medium": 512, "long": 1024}
        system_prompt = (
            f"Summarize the following text concisely. Target length: {max_length}. "
            "Preserve key information and actionable insights."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": params["text"]},
        ]
        request = self._build_request(
            messages,
            provider=params.get("provider", self._primary_provider),
            temperature=0.3,
            max_tokens=length_tokens.get(max_length, 512),
        )
        est_input = len(params["text"]) // 4
        request["request_id"] = str(uuid.uuid4())
        request["response"] = {"summary": "", "finish_reason": None}
        request["_cost_usd"] = self._estimate_cost(request["provider"], est_input, length_tokens.get(max_length, 512))
        return request
