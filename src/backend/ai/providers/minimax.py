"""MiniMax AI Provider."""
from __future__ import annotations

from decimal import Decimal

import httpx

from src.backend.ai.models import (
    FileUploadResponse, ModelInfo, ProviderConfig, TTSRequest, TTSVoice,
)
from src.backend.ai.providers.base import OpenAICompatibleProvider

MINIMAX_MODELS: list[ModelInfo] = [
    ModelInfo(model_id="MiniMax-M2.7", display_name="MiniMax M2.7", provider="minimax",
              description="Flagship, open weights, 197K", context_window=196608,
              input_price_per_m=Decimal("0.30"), output_price_per_m=Decimal("1.20"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True),
    ModelInfo(model_id="MiniMax-M2.7-highspeed", display_name="MiniMax M2.7 HS", provider="minimax",
              description="Speed-optimized ~100tps", context_window=196608,
              input_price_per_m=Decimal("0.30"), output_price_per_m=Decimal("1.20"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True),
    ModelInfo(model_id="MiniMax-M2.5", display_name="MiniMax M2.5", provider="minimax",
              description="Strong coding, SWE-bench 80.2%", context_window=196608,
              input_price_per_m=Decimal("0.27"), output_price_per_m=Decimal("0.95"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True),
    ModelInfo(model_id="MiniMax-M2.5-highspeed", display_name="MiniMax M2.5 HS", provider="minimax",
              description="Speed-optimized M2.5", context_window=196608,
              input_price_per_m=Decimal("0.27"), output_price_per_m=Decimal("0.95"),
              supports_streaming=True, supports_tools=True),
    ModelInfo(model_id="MiniMax-M2.1", display_name="MiniMax M2.1", provider="minimax",
              description="Coding specialist", context_window=196608,
              input_price_per_m=Decimal("0.27"), output_price_per_m=Decimal("0.95"),
              supports_streaming=True, supports_tools=True),
    ModelInfo(model_id="MiniMax-M1", display_name="MiniMax M1", provider="minimax",
              description="1M context, reasoning", context_window=1000000,
              input_price_per_m=Decimal("0.40"), output_price_per_m=Decimal("2.20"),
              supports_streaming=True, supports_reasoning=True),
    ModelInfo(model_id="MiniMax-01", display_name="MiniMax 01", provider="minimax",
              description="1M context, vision", context_window=1000000,
              input_price_per_m=Decimal("0.20"), output_price_per_m=Decimal("1.10"),
              supports_streaming=True, supports_vision=True),
    ModelInfo(model_id="MiniMax-M2-her", display_name="MiniMax M2 Her", provider="minimax",
              description="Roleplay/dialogue, 66K", context_window=66000,
              input_price_per_m=Decimal("0.30"), output_price_per_m=Decimal("1.20"),
              supports_streaming=True),
]

MINIMAX_VOICES: list[TTSVoice] = [
    TTSVoice(voice_id="male-qn-qingse", name="Qingse (Male)", gender="male", language="zh"),
    TTSVoice(voice_id="female-shaonv", name="Shaonv (Female)", gender="female", language="zh"),
    TTSVoice(voice_id="presenter_male", name="Presenter Male", gender="male", language="en"),
    TTSVoice(voice_id="presenter_female", name="Presenter Female", gender="female", language="en"),
    TTSVoice(voice_id="audiobook_male_1", name="Audiobook Male", gender="male", language="en"),
    TTSVoice(voice_id="audiobook_female_1", name="Audiobook Female", gender="female", language="en"),
    TTSVoice(voice_id="calm_female", name="Calm Female", gender="female", language="en"),
    TTSVoice(voice_id="friendly_male", name="Friendly Male", gender="male", language="en"),
]


class MiniMaxProvider(OpenAICompatibleProvider):
    PROVIDER_TYPE = "minimax"
    DEFAULT_BASE_URL = "https://api.minimax.io/v1"
    MODELS = MINIMAX_MODELS

    @property
    def supports_tts(self) -> bool:
        return True

    @property
    def supports_file_upload(self) -> bool:
        return True

    def list_voices(self) -> list[TTSVoice]:
        return list(MINIMAX_VOICES)

    async def text_to_speech(self, request: TTSRequest) -> bytes:
        url = f"{self._base_url}/audio/speech"
        async with httpx.AsyncClient() as client:
            response = await client.post(url,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={"model": request.model, "input": request.text,
                      "voice": request.voice_id, "speed": request.speed, "response_format": "mp3"},
                timeout=60.0)
            response.raise_for_status()
            return response.content

    async def upload_file(self, filename: str, content: bytes, purpose: str = "assistants") -> FileUploadResponse:
        url = f"{self._base_url}/files"
        async with httpx.AsyncClient() as client:
            response = await client.post(url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                files={"file": (filename, content)}, data={"purpose": purpose}, timeout=120.0)
            response.raise_for_status()
            data = response.json()
            return FileUploadResponse(file_id=data.get("id", ""), filename=filename,
                                      size_bytes=len(content), purpose=purpose)
