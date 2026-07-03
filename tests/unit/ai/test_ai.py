"""Tests for AI API Manager."""
import inspect
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.backend.ai.interface import IAIProvider
from src.backend.ai.models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderConfig,
    TokenUsage,
)
from src.backend.ai.registry import (
    available_provider_types,
    create_provider,
    get_all_models,
    get_all_providers,
    get_provider,
    remove_provider,
)
from src.backend.ai.providers.minimax import MiniMaxProvider, MINIMAX_MODELS
from src.backend.db.init_db import create_tables, drop_tables
from src.backend.ai.ai_service import (
    create_ai_provider,
    get_all_ai_models,
    get_all_ai_providers,
)


# -- Interface Tests --

class TestIAIProviderABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            IAIProvider(ProviderConfig(
                name="test", provider_type="test", api_key="k", base_url="u"
            ))

    def test_abstract_methods(self):
        expected = {"provider_type", "list_models", "chat_completion", "chat_completion_stream"}
        abstract = {
            n for n, _ in inspect.getmembers(IAIProvider)
            if getattr(getattr(IAIProvider, n, None), "__isabstractmethod__", False)
        }
        assert abstract == expected


# -- Model Tests --

class TestModels:
    def test_chat_request_defaults(self):
        req = ChatRequest(
            model="test", messages=[ChatMessage(role="user", content="hi")]
        )
        assert req.temperature == 0.7
        assert req.max_tokens == 1024

    def test_chat_request_validation(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ChatRequest(model="test", messages=[], temperature=5.0)

    def test_model_info(self):
        m = ModelInfo(
            model_id="test-1", display_name="Test", provider="test",
            context_window=4096,
        )
        assert m.supports_streaming is True

    def test_token_usage(self):
        u = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        assert u.total_tokens == 30


# -- MiniMax Provider Tests --

class TestMiniMaxProvider:
    def test_models_list(self):
        config = ProviderConfig(
            name="mm", provider_type="minimax",
            api_key="test-key", base_url="https://api.minimax.io/v1",
        )
        provider = MiniMaxProvider(config)
        models = provider.list_models()
        assert len(models) >= 7
        ids = [m.model_id for m in models]
        assert "MiniMax-M2.7" in ids
        assert "MiniMax-M2.5" in ids
        assert "MiniMax-M1" in ids

    def test_provider_type(self):
        config = ProviderConfig(
            name="mm", provider_type="minimax",
            api_key="k", base_url="https://api.minimax.io/v1",
        )
        p = MiniMaxProvider(config)
        assert p.provider_type == "minimax"

    def test_model_prices(self):
        for m in MINIMAX_MODELS:
            if m.input_price_per_m is not None:
                assert m.input_price_per_m > 0

    def test_model_context_windows(self):
        for m in MINIMAX_MODELS:
            assert m.context_window > 0

    def test_supports_tts(self):
        config = ProviderConfig(
            name="tts-test", provider_type="minimax",
            api_key="k", base_url="https://api.minimax.io/v1",
        )
        p = MiniMaxProvider(config)
        assert p.supports_tts is True

    def test_supports_file_upload(self):
        config = ProviderConfig(
            name="fu-test", provider_type="minimax",
            api_key="k", base_url="https://api.minimax.io/v1",
        )
        p = MiniMaxProvider(config)
        assert p.supports_file_upload is True

    def test_list_voices(self):
        config = ProviderConfig(
            name="v-test", provider_type="minimax",
            api_key="k", base_url="https://api.minimax.io/v1",
        )
        p = MiniMaxProvider(config)
        voices = p.list_voices()
        assert len(voices) >= 8
        assert any(v.language == "en" for v in voices)


# -- Advanced Model Tests (ATS-101/102/106) --

class TestAdvancedModels:
    def test_tool_definition(self):
        from src.backend.ai.models import ToolDefinition, ToolFunction, ToolParameter
        tool = ToolDefinition(
            function=ToolFunction(
                name="get_price",
                description="Get stock price",
                parameters=ToolParameter(
                    properties={"symbol": {"type": "string"}},
                    required=["symbol"],
                ),
            )
        )
        assert tool.function.name == "get_price"
        assert tool.type == "function"

    def test_tool_call(self):
        from src.backend.ai.models import ToolCall
        tc = ToolCall(
            id="call_1", function_name="get_price",
            function_args='{"symbol": "AAPL"}',
        )
        assert tc.function_name == "get_price"

    def test_chat_request_with_tools(self):
        from src.backend.ai.models import ToolDefinition, ToolFunction
        req = ChatRequest(
            model="test",
            messages=[ChatMessage(role="user", content="hi")],
            tools=[ToolDefinition(function=ToolFunction(name="test_fn"))],
            tool_choice="auto",
        )
        assert len(req.tools) == 1
        assert req.tool_choice == "auto"

    def test_chat_request_json_mode(self):
        req = ChatRequest(
            model="test",
            messages=[ChatMessage(role="user", content="hi")],
            json_mode=True,
        )
        assert req.json_mode is True

    def test_chat_request_reasoning(self):
        req = ChatRequest(
            model="test",
            messages=[ChatMessage(role="user", content="hi")],
            reasoning=True,
        )
        assert req.reasoning is True

    def test_chat_response_with_tool_calls(self):
        from src.backend.ai.models import ToolCall
        resp = ChatResponse(
            model="test", provider="test", content="",
            tool_calls=[ToolCall(id="1", function_name="fn", function_args="{}")],
        )
        assert len(resp.tool_calls) == 1

    def test_chat_response_with_reasoning(self):
        resp = ChatResponse(
            model="test", provider="test", content="answer",
            reasoning_content="I thought about it",
        )
        assert resp.reasoning_content == "I thought about it"

    def test_tts_request(self):
        from src.backend.ai.models import TTSRequest
        req = TTSRequest(text="Hello world")
        assert req.model == "speech-2.8-hd"
        assert req.speed == 1.0

    def test_chat_message_with_image(self):
        msg = ChatMessage(role="user", content="Describe this", image_url="https://example.com/img.jpg")
        assert msg.image_url is not None

    def test_chat_message_with_tool_call_id(self):
        msg = ChatMessage(role="tool", content="result", tool_call_id="call_1")
        assert msg.tool_call_id == "call_1"

    def test_file_upload_response(self):
        from src.backend.ai.models import FileUploadResponse
        resp = FileUploadResponse(file_id="f1", filename="doc.pdf", size_bytes=1024)
        assert resp.purpose == "assistants"

    def test_reasoning_regex(self):
        import re
        pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
        text = "Before <think>My reasoning here\nwith newlines</think> After"
        match = pattern.search(text)
        assert match is not None
        assert "My reasoning here" in match.group(1)
        cleaned = pattern.sub("", text).strip()
        assert "<think>" not in cleaned


# -- Registry Tests --

# -- Multi-Provider Tests (ATS-118-122) --

class TestNewProviders:
    def test_all_providers_registered(self):
        types = available_provider_types()
        assert "minimax" in types
        assert "deepseek" in types
        assert "qwen" in types
        assert "zhipu" in types
        assert "moonshot" in types

    def test_deepseek_models(self):
        from src.backend.ai.providers.deepseek import DeepSeekProvider
        p = DeepSeekProvider(ProviderConfig(name="ds", provider_type="deepseek", api_key="k", base_url="https://api.deepseek.com"))
        models = p.list_models()
        assert len(models) == 2
        ids = [m.model_id for m in models]
        assert "deepseek-chat" in ids
        assert "deepseek-reasoner" in ids
        assert any(m.supports_reasoning for m in models)

    def test_qwen_models(self):
        from src.backend.ai.providers.qwen import QwenProvider
        p = QwenProvider(ProviderConfig(name="qw", provider_type="qwen", api_key="k", base_url=""))
        models = p.list_models()
        assert len(models) >= 4
        assert any(m.context_window == 1000000 for m in models)

    def test_zhipu_models_include_free(self):
        from src.backend.ai.providers.zhipu import ZhipuProvider
        p = ZhipuProvider(ProviderConfig(name="zh", provider_type="zhipu", api_key="k", base_url=""))
        models = p.list_models()
        free = [m for m in models if m.input_price_per_m == 0]
        assert len(free) >= 1  # GLM-4.7-Flash is free

    def test_moonshot_models(self):
        from src.backend.ai.providers.moonshot import MoonshotProvider
        p = MoonshotProvider(ProviderConfig(name="ms", provider_type="moonshot", api_key="k", base_url=""))
        models = p.list_models()
        assert len(models) >= 2
        assert all(m.supports_reasoning for m in models)

    def test_base_class_provider_type(self):
        from src.backend.ai.providers.deepseek import DeepSeekProvider
        p = DeepSeekProvider(ProviderConfig(name="t", provider_type="deepseek", api_key="k", base_url=""))
        assert p.provider_type == "deepseek"

    def test_create_each_provider_type(self):
        for ptype in ["deepseek", "qwen", "zhipu", "moonshot"]:
            p = create_provider(ProviderConfig(name=f"test-{ptype}", provider_type=ptype, api_key="k", base_url="x"))
            assert p.provider_type == ptype
            remove_provider(f"test-{ptype}")


# -- Research Engine Tests (ATS-123) --

class TestResearchEngine:
    def test_parse_report_sections(self):
        from src.backend.ai.research.engine import _parse_report_sections
        content = "## Executive Summary\nGood stock.\n\n## Technische Analyse\nRSI is 45.\n\n## Empfehlung\nKAUFEN"
        sections = _parse_report_sections(content)
        assert "executive summary" in sections
        assert "Good stock." in sections["executive summary"]
        assert "empfehlung" in sections
        assert "KAUFEN" in sections["empfehlung"]

    def test_research_request_model(self):
        from src.backend.ai.research.engine import ResearchRequest
        req = ResearchRequest(symbol="AAPL", question="Is it a buy?")
        assert req.symbol == "AAPL"

    def test_research_report_model(self):
        from src.backend.ai.research.engine import ResearchReport
        report = ResearchReport(symbol="AAPL", question="Test")
        assert report.tokens_used == 0
        assert report.estimated_cost_usd == 0.0


class TestRegistry:
    def test_minimax_registered(self):
        assert "minimax" in available_provider_types()

    def test_create_and_get_provider(self):
        config = ProviderConfig(
            name="test-mm", provider_type="minimax",
            api_key="key", base_url="https://api.minimax.io/v1",
        )
        p = create_provider(config)
        assert get_provider("test-mm") is p
        remove_provider("test-mm")

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            create_provider(ProviderConfig(
                name="x", provider_type="nonexistent",
                api_key="k", base_url="u",
            ))

    def test_get_all_models(self):
        config = ProviderConfig(
            name="models-test", provider_type="minimax",
            api_key="key", base_url="https://api.minimax.io/v1",
        )
        create_provider(config)
        models = get_all_models()
        assert len(models) >= 7
        remove_provider("models-test")


# -- DB Service Tests --

@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    await create_tables(engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await drop_tables(engine)
    await engine.dispose()


class TestAIService:
    async def test_create_provider_in_db(self, db_session):
        row = await create_ai_provider(
            db_session, name="test-minimax", provider_type="minimax",
            api_key="test-key-123", base_url="https://api.minimax.io/v1",
        )
        assert row.id is not None
        assert row.name == "test-minimax"
        remove_provider("test-minimax")

    async def test_list_providers(self, db_session):
        await create_ai_provider(
            db_session, name="prov1", provider_type="minimax",
            api_key="k1", base_url="https://api.minimax.io/v1",
        )
        providers = await get_all_ai_providers(db_session)
        assert len(providers) >= 1
        remove_provider("prov1")

    async def test_models_synced_to_db(self, db_session):
        await create_ai_provider(
            db_session, name="sync-test", provider_type="minimax",
            api_key="k1", base_url="https://api.minimax.io/v1",
        )
        models = await get_all_ai_models(db_session)
        assert len(models) >= 7
        remove_provider("sync-test")
