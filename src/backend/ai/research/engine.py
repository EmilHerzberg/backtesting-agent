"""Deep Research Engine — generates structured stock analysis reports."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field

from src.backend.ai.models import ChatMessage, ChatRequest
from src.backend.ai.registry import get_all_providers, get_provider
from src.backend.indicators.registry import get_indicator

logger = logging.getLogger(__name__)


class ResearchReport(BaseModel):
    """Structured research report output."""
    symbol: str
    question: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider_used: str = ""
    model_used: str = ""
    # Report sections
    executive_summary: str = ""
    technical_analysis: str = ""
    ai_reasoning: str = ""
    recommendation: str = ""
    # Metadata
    indicators: dict[str, float] = Field(default_factory=dict)
    current_price: float | None = None
    tokens_used: int = 0
    estimated_cost_usd: float = 0.0


class ResearchRequest(BaseModel):
    symbol: str
    question: str = ""
    provider_name: str | None = None  # If None, picks cheapest reasoning model
    model_id: str | None = None


def _pick_cheapest_reasoning_provider() -> tuple[str, str] | None:
    """Find the cheapest provider with a reasoning-capable model."""
    best = None
    best_cost = Decimal("999999")
    for name, provider in get_all_providers().items():
        if not provider.is_active:
            continue
        for model in provider.list_models():
            if model.supports_reasoning and model.output_price_per_m is not None:
                cost = model.output_price_per_m
                if cost < best_cost:
                    best_cost = cost
                    best = (name, model.model_id)
    return best


async def generate_research_report(
    request: ResearchRequest,
    prices: list[Decimal] | None = None,
) -> ResearchReport:
    """Generate a deep research report for a stock.

    Steps:
    1. Calculate technical indicators from price data
    2. Build a comprehensive prompt with all context
    3. Send to AI for deep analysis with reasoning
    4. Parse and structure the response
    """
    report = ResearchReport(symbol=request.symbol.upper(), question=request.question)

    # Step 1: Technical Analysis (if prices available)
    indicator_data = {}
    if prices and len(prices) >= 30:
        for ind_name in ["RSI", "SMA", "EMA", "MACD"]:
            try:
                params = {"period": 14} if ind_name == "RSI" else {"period": 20} if ind_name in ("SMA", "EMA") else {}
                ind = get_indicator(ind_name, **params)
                val = ind.calculate(prices)
                sig = ind.signal(prices)
                if val is not None:
                    indicator_data[ind_name] = {"value": float(val), "signal": sig.value}
            except Exception:
                pass
        report.indicators = {k: v["value"] for k, v in indicator_data.items()}
        report.current_price = float(prices[-1])

    # Step 2: Select provider
    provider_name = request.provider_name
    model_id = request.model_id
    if not provider_name or not model_id:
        auto = _pick_cheapest_reasoning_provider()
        if auto:
            provider_name, model_id = auto
        else:
            report.executive_summary = "Kein AI Provider mit Reasoning-Modell verfuegbar. Bitte konfigurieren Sie einen Provider im Setup."
            return report

    provider = get_provider(provider_name)
    if provider is None:
        report.executive_summary = f"Provider '{provider_name}' nicht gefunden."
        return report

    report.provider_used = provider_name
    report.model_used = model_id

    # Step 3: Build comprehensive prompt
    context_parts = [f"Aktie: {request.symbol.upper()}"]
    if report.current_price:
        context_parts.append(f"Aktueller Kurs: ${report.current_price:.2f}")
    if indicator_data:
        for name, data in indicator_data.items():
            context_parts.append(f"{name}: {data['value']:.2f} (Signal: {data['signal']})")
    context = "\n".join(context_parts)

    question = request.question or f"Ist {request.symbol.upper()} aktuell ein guter Kauf?"

    system_prompt = """Du bist ein erfahrener Finanzanalyst. Erstelle einen strukturierten Research-Report.

Antworte in exakt diesem Format (mit den Ueberschriften):

## Executive Summary
[2-3 Saetze Zusammenfassung]

## Technische Analyse
[Interpretation der Indikatoren, Trend-Einschaetzung, Support/Resistance]

## AI Reasoning
[Deine detaillierte Analyse: Marktumfeld, Risiken, Chancen, Vergleich mit Sektor]

## Empfehlung
[Klare Handlungsempfehlung: KAUFEN / HALTEN / VERKAUFEN mit Begruendung]"""

    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=f"Marktdaten:\n{context}\n\nFrage: {question}"),
    ]

    # Step 4: Call AI
    try:
        response = await provider.chat_completion(ChatRequest(
            model=model_id, messages=messages,
            temperature=0.3, max_tokens=4096,
            reasoning=True,
        ))

        content = response.content
        report.ai_reasoning = response.reasoning_content or ""
        if response.usage:
            report.tokens_used = response.usage.total_tokens

        # Parse sections from response
        sections = _parse_report_sections(content)
        report.executive_summary = sections.get("executive summary", content[:500])
        report.technical_analysis = sections.get("technische analyse", "")
        if not report.ai_reasoning:
            report.ai_reasoning = sections.get("ai reasoning", "")
        report.recommendation = sections.get("empfehlung", "")

        # Estimate cost
        model_info = next((m for m in provider.list_models() if m.model_id == model_id), None)
        if model_info and response.usage and model_info.output_price_per_m:
            cost = (
                float(model_info.input_price_per_m or 0) * response.usage.prompt_tokens / 1_000_000
                + float(model_info.output_price_per_m) * response.usage.completion_tokens / 1_000_000
            )
            report.estimated_cost_usd = round(cost, 6)

    except Exception as e:
        logger.error("Research generation failed: %s", e)
        report.executive_summary = f"Fehler bei der Analyse: {e}"

    return report


def _parse_report_sections(content: str) -> dict[str, str]:
    """Parse markdown sections from AI response."""
    sections: dict[str, str] = {}
    current_key = ""
    current_lines: list[str] = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = line[3:].strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections
