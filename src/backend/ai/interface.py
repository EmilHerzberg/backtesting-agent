"""Abstract interface for AI providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.backend.ai.models import (
    ChatRequest,
    ChatResponse,
    FileUploadResponse,
    ModelInfo,
    ProviderConfig,
    TTSRequest,
    TTSVoice,
)


class IAIProvider(ABC):
    """Abstract base class for AI model providers."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Provider type identifier (e.g., 'minimax', 'openai')."""

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def is_active(self) -> bool:
        return self._config.is_active

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """Return all models available from this provider."""

    @abstractmethod
    async def chat_completion(self, request: ChatRequest) -> ChatResponse:
        """Send a chat completion request and return the full response."""

    @abstractmethod
    async def chat_completion_stream(
        self, request: ChatRequest
    ) -> AsyncIterator[str]:
        """Send a streaming chat completion request. Yields content chunks."""

    # Optional capabilities — providers override if supported

    async def text_to_speech(self, request: TTSRequest) -> bytes:
        """Convert text to speech audio (MP3). Override if supported."""
        raise NotImplementedError(f"{self.provider_type} does not support TTS")

    def list_voices(self) -> list[TTSVoice]:
        """List available TTS voices. Override if supported."""
        return []

    async def upload_file(
        self, filename: str, content: bytes, purpose: str = "assistants"
    ) -> FileUploadResponse:
        """Upload a file. Override if supported."""
        raise NotImplementedError(f"{self.provider_type} does not support file upload")

    @property
    def supports_tts(self) -> bool:
        return False

    @property
    def supports_file_upload(self) -> bool:
        return False
