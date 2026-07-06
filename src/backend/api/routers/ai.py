"""AI API Manager endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.ai.models import (
    ChatMessage, ChatRequest, ChatResponse,
    ToolDefinition, ToolFunction, ToolParameter,
    TTSRequest,
)
from src.backend.ai.registry import (
    available_provider_types,
    get_all_models,
    get_all_providers,
    get_provider,
)
from src.backend.ai.leakage import provider_leakage
from src.backend.api.dependencies import get_current_user_id
from src.backend.db.engine import get_session
from src.backend.ai.ai_service import (
    create_ai_provider,
    delete_ai_provider,
    get_all_ai_models,
    get_all_ai_providers,
    toggle_ai_provider,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])


# -- Schemas --

class ProviderCreateRequest(BaseModel):
    name: str
    provider_type: str
    api_key: str
    base_url: str = ""


class ProviderResponse(BaseModel):
    id: int
    name: str
    provider_type: str
    base_url: str
    is_active: bool
    api_key_masked: str
    leakage: str = "unvalidated"   # Phase 2 (F-11): provider-summary leakage state (mechanism_only|risk|unvalidated)

    @classmethod
    def from_db(cls, row) -> ProviderResponse:
        from src.backend.ai.keycrypto import mask_key
        masked = mask_key(row.api_key)   # decrypt-then-mask (never returns the full key)
        return cls(
            id=row.id,
            name=row.name,
            provider_type=row.provider_type,
            base_url=row.base_url,
            is_active=row.is_active,
            api_key_masked=masked,
            leakage=provider_leakage(row.provider_type),
        )


class ModelResponse(BaseModel):
    model_id: str
    display_name: str
    provider: str
    description: str
    context_window: int
    input_price: float | None
    output_price: float | None
    supports_streaming: bool
    supports_tools: bool
    supports_vision: bool
    supports_reasoning: bool = False   # Phase 2: mark reasoning models in the picker (F-9/F-12)
    leakage: str = "unvalidated"       # Phase 2 (F-11): per-model leakage state (mechanism_only|risk|unvalidated)


class ChatRequestPayload(BaseModel):
    provider: str
    model: str
    messages: list[dict]  # [{role, content, image_url?, tool_call_id?, tool_calls?}]
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 0.95
    stream: bool = False
    tools: list[dict] | None = None  # [{type, function: {name, description, parameters}}]
    tool_choice: str | None = None  # auto, required, none
    json_mode: bool = False
    reasoning: bool = False


class ToolCallPayload(BaseModel):
    id: str
    type: str
    function_name: str
    function_args: str


class ChatResponsePayload(BaseModel):
    model: str
    provider: str
    content: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    tool_calls: list[ToolCallPayload] | None = None
    reasoning_content: str | None = None


class TTSRequestPayload(BaseModel):
    provider: str
    text: str
    voice_id: str = "male-qn-qingse"
    model: str = "speech-2.8-hd"
    speed: float = 1.0


class VoiceResponse(BaseModel):
    voice_id: str
    name: str
    gender: str
    language: str


# -- Provider Endpoints --

@router.get("/provider-types")
async def list_provider_types(
    _user_id: int = Depends(get_current_user_id),
):
    return {"types": available_provider_types()}


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    rows = await get_all_ai_providers(session, user_id=user_id)
    return [ProviderResponse.from_db(r) for r in rows]


@router.post("/providers", response_model=ProviderResponse, status_code=201)
async def add_provider(
    req: ProviderCreateRequest,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await create_ai_provider(
            session,
            name=req.name,
            provider_type=req.provider_type,
            api_key=req.api_key,
            base_url=req.base_url or _default_url(req.provider_type),
            user_id=user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ProviderResponse.from_db(row)


@router.post("/providers/{provider_id}/toggle", response_model=ProviderResponse)
async def toggle_provider(
    provider_id: int,
    active: bool = True,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    row = await toggle_ai_provider(session, provider_id, active, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return ProviderResponse.from_db(row)


@router.delete("/providers/{provider_id}")
async def remove_provider_endpoint(
    provider_id: int,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    ok = await delete_ai_provider(session, provider_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"message": "Deleted"}


# -- Model Endpoints --

@router.get("/models", response_model=list[ModelResponse])
async def list_models(
    _user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    models = get_all_models()
    return [
        ModelResponse(
            model_id=m.model_id,
            display_name=m.display_name,
            provider=m.provider,
            description=m.description,
            context_window=m.context_window,
            # M45: Decimal("0") is falsy, so `if m.input_price_per_m` mapped a genuinely FREE model
            # (priced 0/0) to null → "free" was served as "unknown" and the free-model UI/auto-pick path
            # was unreachable. Distinguish None (unknown) from 0 (free) explicitly.
            input_price=float(m.input_price_per_m) if m.input_price_per_m is not None else None,
            output_price=float(m.output_price_per_m) if m.output_price_per_m is not None else None,
            supports_streaming=m.supports_streaming,
            supports_tools=m.supports_tools,
            supports_vision=m.supports_vision,
            supports_reasoning=m.supports_reasoning,
            leakage=getattr(m, "leakage", "unvalidated"),
        )
        for m in models
    ]


# -- Chat Endpoints --

@router.post("/chat", response_model=ChatResponsePayload)
async def chat_completion(
    req: ChatRequestPayload,
    _user_id: int = Depends(get_current_user_id),
):
    provider = get_provider(req.provider)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{req.provider}' not found")

    chat_req = _build_chat_request(req)

    try:
        response = await provider.chat_completion(chat_req)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider error: {e}")

    tc_payload = None
    if response.tool_calls:
        tc_payload = [
            ToolCallPayload(id=tc.id, type=tc.type,
                            function_name=tc.function_name,
                            function_args=tc.function_args)
            for tc in response.tool_calls
        ]

    return ChatResponsePayload(
        model=response.model,
        provider=response.provider,
        content=response.content,
        finish_reason=response.finish_reason,
        prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
        completion_tokens=response.usage.completion_tokens if response.usage else 0,
        total_tokens=response.usage.total_tokens if response.usage else 0,
        tool_calls=tc_payload,
        reasoning_content=response.reasoning_content,
    )


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequestPayload,
    _user_id: int = Depends(get_current_user_id),
):
    provider = get_provider(req.provider)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{req.provider}' not found")

    chat_req = _build_chat_request(req)
    chat_req.stream = True

    async def event_generator():
        try:
            async for chunk in provider.chat_completion_stream(chat_req):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {e}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# -- TTS Endpoints (ATS-103) --

@router.get("/voices", response_model=list[VoiceResponse])
async def list_voices(
    provider_name: str,
    _user_id: int = Depends(get_current_user_id),
):
    provider = get_provider(provider_name)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    voices = provider.list_voices()
    return [
        VoiceResponse(voice_id=v.voice_id, name=v.name, gender=v.gender, language=v.language)
        for v in voices
    ]


@router.post("/tts")
async def text_to_speech(
    req: TTSRequestPayload,
    _user_id: int = Depends(get_current_user_id),
):
    provider = get_provider(req.provider)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not provider.supports_tts:
        raise HTTPException(status_code=400, detail="Provider does not support TTS")

    try:
        audio_bytes = await provider.text_to_speech(
            TTSRequest(text=req.text, voice_id=req.voice_id,
                       model=req.model, speed=req.speed)
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS error: {e}")

    from fastapi.responses import Response
    return Response(content=audio_bytes, media_type="audio/mpeg",
                    headers={"Content-Disposition": "attachment; filename=speech.mp3"})


# -- File Upload (ATS-105) --

@router.post("/files/upload")
async def upload_file(
    provider_name: str,
    _user_id: int = Depends(get_current_user_id),
):
    # File upload via multipart — simplified for now
    provider = get_provider(provider_name)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not provider.supports_file_upload:
        raise HTTPException(status_code=400, detail="Provider does not support file upload")
    raise HTTPException(status_code=501, detail="File upload endpoint requires multipart form — use direct provider API for now")


# -- Helpers --

def _build_chat_request(req: ChatRequestPayload) -> ChatRequest:
    messages = []
    for m in req.messages:
        messages.append(ChatMessage(
            role=m.get("role", "user"),
            content=m.get("content"),
            image_url=m.get("image_url"),
            tool_call_id=m.get("tool_call_id"),
            file_id=m.get("file_id"),
        ))

    tools = None
    if req.tools:
        tools = [
            ToolDefinition(
                type=t.get("type", "function"),
                function=ToolFunction(
                    name=t["function"]["name"],
                    description=t["function"].get("description", ""),
                    parameters=ToolParameter(**t["function"].get("parameters", {})),
                ),
            )
            for t in req.tools
        ]

    return ChatRequest(
        model=req.model, messages=messages,
        temperature=req.temperature, max_tokens=req.max_tokens,
        top_p=req.top_p, tools=tools, tool_choice=req.tool_choice,
        json_mode=req.json_mode, reasoning=req.reasoning,
    )


def _default_url(provider_type: str) -> str:
    defaults = {
        "minimax": "https://api.minimax.io/v1",
        "deepseek": "https://api.deepseek.com",
        "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "moonshot": "https://api.moonshot.cn/v1",
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com",
    }
    return defaults.get(provider_type, "")
