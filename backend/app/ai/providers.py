"""Proveedores de modelo con una interfaz común.

- OpenAIProvider: llama a la API oficial (Responses API) desde el servidor.
- MockProvider: modo de pruebas determinístico que recorre el mismo circuito de herramientas sin consumir la API.
  Se identifica siempre como modo de pruebas en la interfaz.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import get_settings

logger = logging.getLogger("signature.ai")


@dataclass
class FunctionCall:
    call_id: str
    name: str
    arguments: str


@dataclass
class ProviderResult:
    output_items: list[dict[str, Any]]
    text: str
    function_calls: list[FunctionCall]
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class TurnContext:
    """Información de estado que el orquestador comparte con los proveedores."""

    intake: dict[str, Any]
    status: str
    offered_slots: list[str] = field(default_factory=list)
    request_code: str | None = None


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def respond(
        self, instructions: str, items: list[dict[str, Any]], tools: list[dict[str, Any]], ctx: TurnContext
    ) -> ProviderResult: ...

    def complete(
        self, instructions: str, prompt: str, max_output_tokens: int = 700, schema: dict[str, Any] | None = None
    ) -> tuple[str, int, int]: ...


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        from openai import OpenAI

        settings = get_settings()
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds, max_retries=2)

    def _create(self, **kwargs) -> Any:
        from openai import APIError

        try:
            return self.client.responses.create(
                model=self.settings.openai_model,
                reasoning={"effort": self.settings.openai_reasoning_effort},
                store=False,
                **kwargs,
            )
        except APIError as exc:  # No se registra el contenido de la solicitud ni la clave.
            logger.warning("Error de OpenAI: %s", type(exc).__name__)
            raise ProviderError("El servicio de IA no está disponible en este momento.") from exc

    def respond(self, instructions, items, tools, ctx) -> ProviderResult:
        response = self._create(
            instructions=instructions,
            input=items,
            tools=tools,
            parallel_tool_calls=False,
            include=["reasoning.encrypted_content"],
            max_output_tokens=self.settings.ai_max_output_tokens + 1200,
            prompt_cache_key="sar-assistant-v1",
        )
        output_items = [item.model_dump(exclude_none=True, by_alias=True) for item in response.output]
        calls = [
            FunctionCall(call_id=item.call_id, name=item.name, arguments=item.arguments)
            for item in response.output
            if item.type == "function_call"
        ]
        usage = response.usage
        return ProviderResult(
            output_items=output_items,
            text=response.output_text or "",
            function_calls=calls,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
        )

    def complete(
        self, instructions: str, prompt: str, max_output_tokens: int = 700, schema: dict[str, Any] | None = None
    ) -> tuple[str, int, int]:
        extra = {}
        if schema:
            extra["text"] = {"format": {"type": "json_schema", "name": "resultado", "schema": schema, "strict": True}}
        response = self._create(
            instructions=instructions, input=prompt, max_output_tokens=max_output_tokens + 1200, **extra
        )
        usage = response.usage
        return (
            (response.output_text or "").strip(),
            usage.input_tokens if usage else 0,
            usage.output_tokens if usage else 0,
        )


def get_provider() -> Provider:
    settings = get_settings()
    if settings.ai_enabled:
        return OpenAIProvider()
    from app.ai.mock import MockProvider

    return MockProvider()


def function_call_item(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function_call",
        "call_id": f"mock_{uuid.uuid4().hex[:12]}",
        "name": name,
        "arguments": json.dumps(arguments, ensure_ascii=False),
    }
