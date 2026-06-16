"""AI investment-thesis generation via the Google Gemini API (free-tier Flash model).

This is a thin integration layer — it talks to an external service (Gemini), so it lives
*outside* the pure `engine/` package (which has no network and no third-party SDK imports).
The prompt construction (`build_prompt`) is pure and unit-tested; the network call
(`generate_ai_thesis`) is isolated behind an injectable model factory so tests never need
the SDK installed or a real API key.

The thesis is GROUNDED in the valuation numbers passed in via `ThesisContext` — the prompt
embeds this company's actual DCF value/share, gap vs market, WACC, growth/margin
assumptions, trading multiples vs peers, and Monte Carlo VaR/ES, and instructs the model to
reason ONLY from those numbers (never inventing financials), so the output is specific to
the company rather than generic boilerplate. The AI Insights note (`build_prompt`) asks for
six sections — Investment Thesis, Bull Case, Bear Case, Key Risks, Valuation Commentary,
Catalysts — while the one-page PDF (`build_report_prompt`) stays a concise four-section note.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# Current free-tier Gemini Flash model.
DEFAULT_MODEL = "gemini-2.5-flash"


class AIError(Exception):
    """Base class for AI-generation errors."""


class AIKeyError(AIError):
    """No Gemini API key was provided."""


class AIRateLimitError(AIError):
    """Gemini quota / rate limit hit (HTTP 429 / ResourceExhausted)."""


@dataclass(frozen=True)
class ThesisContext:
    """Everything the model is grounded in. Rates are decimals (0.08 == 8%).

    Monetary fields are in ``currency``. Optional fields are ``None`` when the underlying
    data wasn't available (e.g. no DCF because there's no market cap); the prompt builder
    simply omits missing lines rather than fabricating them.
    """

    company_name: str
    symbol: str
    currency: str = ""
    sector: Optional[str] = None
    industry: Optional[str] = None

    # DCF outputs
    value_per_share: Optional[float] = None
    market_price: Optional[float] = None
    gap_vs_market: Optional[float] = None      # value/share ÷ price − 1 (decimal)
    enterprise_value: Optional[float] = None
    equity_value: Optional[float] = None
    wacc: Optional[float] = None
    terminal_growth: Optional[float] = None
    revenue_growth: Optional[float] = None      # DCF assumption
    ebit_margin: Optional[float] = None         # DCF assumption

    # Trading multiples: label -> value (e.g. {"Trailing P/E": 28.4, "EV/EBITDA": 19.1}).
    multiples: dict[str, float] = field(default_factory=dict)

    # Relative valuation vs peers (from the Peers tab; omitted when no peer set is available).
    target_pe: Optional[float] = None           # this company's trailing P/E, peer-set basis
    median_peer_pe: Optional[float] = None       # peer-group median trailing P/E
    peer_count: Optional[int] = None             # number of peers behind the median

    # Monte Carlo market-price risk (from the Risk tab; 1-year horizon, 95% confidence).
    annualized_vol: Optional[float] = None       # annualized return volatility σ (decimal)
    var_pct: Optional[float] = None              # 1-yr 95% Value-at-Risk, loss magnitude (decimal)
    es_pct: Optional[float] = None               # 1-yr 95% Expected Shortfall, loss magnitude (decimal)

    # Recent news (optional, fail-soft).
    headlines: list[str] = field(default_factory=list)
    news_included: bool = False


# Factory type: (api_key, model_name) -> object exposing .generate_content(prompt) -> resp.
ModelFactory = Callable[[str, str], object]


def _fmt_compact(value: float) -> str:
    a = abs(value)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{value / div:,.1f}{suffix}"
    return f"{value:,.0f}"


def _facts_block(ctx: ThesisContext) -> str:
    """Build the grounded "=== VALUATION DATA ===" fact lines shared by every prompt.

    Pure and deterministic: each line is emitted only when its underlying figure exists, so
    a missing input is omitted rather than fabricated.
    """
    cur = (ctx.currency or "").strip()
    cur_sp = f" {cur}" if cur and cur != "—" else ""

    facts: list[str] = [f"Company: {ctx.company_name} ({ctx.symbol})"]
    if ctx.sector and ctx.sector != "—":
        facts.append(f"Sector / industry: {ctx.sector} / {ctx.industry or '—'}")

    if ctx.value_per_share is not None:
        facts.append(f"DCF intrinsic value per share: {ctx.value_per_share:,.2f}{cur_sp}")
    if ctx.market_price is not None:
        facts.append(f"Current market price: {ctx.market_price:,.2f}{cur_sp}")
    if ctx.gap_vs_market is not None:
        direction = "undervalued" if ctx.gap_vs_market > 0 else "overvalued"
        facts.append(
            f"DCF gap vs market: {ctx.gap_vs_market:+.1%} "
            f"(the DCF implies the stock is {direction} versus its current price)"
        )
    if ctx.enterprise_value is not None:
        facts.append(f"DCF enterprise value: {_fmt_compact(ctx.enterprise_value)}{cur_sp}")
    if ctx.equity_value is not None:
        facts.append(f"DCF equity value: {_fmt_compact(ctx.equity_value)}{cur_sp}")
    if ctx.wacc is not None:
        facts.append(f"WACC (discount rate): {ctx.wacc:.2%}")
    if ctx.terminal_growth is not None:
        facts.append(f"Terminal growth assumption: {ctx.terminal_growth:.2%}")
    if ctx.revenue_growth is not None:
        facts.append(f"Forecast revenue growth assumption: {ctx.revenue_growth:.2%}")
    if ctx.ebit_margin is not None:
        facts.append(f"Forecast EBIT margin assumption: {ctx.ebit_margin:.2%}")

    for label, value in ctx.multiples.items():
        facts.append(f"{label}: {value:,.1f}x")

    # Relative valuation vs peers — only when a real peer set was available.
    if ctx.target_pe is not None and ctx.median_peer_pe is not None:
        n = ctx.peer_count or 0
        rel = "above" if ctx.target_pe > ctx.median_peer_pe else "below"
        facts.append(
            f"Trailing P/E vs peers: {ctx.target_pe:,.1f}x for {ctx.symbol} vs a peer median "
            f"of {ctx.median_peer_pe:,.1f}x ({n} peers) — trading {rel} the peer group"
        )
    elif ctx.median_peer_pe is not None:
        facts.append(
            f"Peer median trailing P/E: {ctx.median_peer_pe:,.1f}x "
            f"({ctx.peer_count or 0} peers)"
        )

    # Monte Carlo price-risk (market risk, distinct from the DCF fundamental value).
    if ctx.annualized_vol is not None:
        facts.append(f"Annualized share-price volatility (σ): {ctx.annualized_vol:.1%}")
    if ctx.var_pct is not None:
        facts.append(
            f"1-year 95% Value-at-Risk (VaR): −{ctx.var_pct:.1%} "
            "(a 5% chance of at least this much price loss over one year)"
        )
    if ctx.es_pct is not None:
        facts.append(
            f"1-year 95% Expected Shortfall (ES/CVaR): −{ctx.es_pct:.1%} "
            "(the average loss conditional on landing in that worst-5% tail)"
        )

    if ctx.news_included and ctx.headlines:
        facts.append("Recent news headlines:")
        facts.extend(f"  - {h}" for h in ctx.headlines)
    else:
        facts.append("Recent news: not available (generate the thesis from the numbers).")

    return "\n".join(facts)


def build_prompt(ctx: ThesisContext) -> str:
    """Build the grounded Gemini prompt for the AI Insights research note. Pure/deterministic.

    Embeds THIS company's actual computed numbers (DCF value and gap vs market, WACC,
    growth/margin assumptions, trailing multiples vs peers, Monte Carlo VaR/ES) and asks for
    a six-section research note, each section a short paragraph grounded in those figures.
    Instructs the model to reason only from the data given and never invent financials.
    """
    facts_block = _facts_block(ctx)
    sector_clue = ""
    if ctx.sector and ctx.sector != "—":
        sector_clue = f", a company in the {ctx.sector} sector,"

    return (
        "You are a buy-side equity research analyst writing a deep, balanced investment "
        f"research note on {ctx.company_name} ({ctx.symbol}){sector_clue} for an analyst "
        "audience. Everything you write must be specific to THIS company and THESE numbers.\n\n"
        "=== VALUATION DATA ===\n"
        f"{facts_block}\n"
        "=== END DATA ===\n\n"
        "GROUNDING RULES (follow strictly):\n"
        "- Reason ONLY from the figures in the VALUATION DATA block above. Cite the actual "
        "numbers — the DCF value per share and its % gap vs the market price, the WACC, the "
        "terminal-growth / revenue-growth / EBIT-margin assumptions, the trailing multiples "
        "and how they compare to the peer median, and the Monte Carlo VaR/ES where given.\n"
        "- Do NOT invent or assume any financial figures, growth rates, margins, product "
        "lines, management actions, or news events that are not provided. If a number needed "
        "for a point is not in the data, omit that point rather than guessing or estimating.\n"
        "- Treat the DCF value as model output that depends on the stated assumptions, not as "
        "a fact; be explicit that the gap vs market is only as good as those assumptions.\n"
        "- No generic boilerplate that could apply to any company; no buy/sell recommendation "
        "and no price target of your own.\n\n"
        "Write in GitHub-flavored Markdown with EXACTLY these six sections, in this order, "
        "each as a level-2 (##) heading. Write each as ONE substantive paragraph of 2-4 "
        "sentences of analyst prose (NOT bullet lists, NOT filler) — quality and grounding "
        "matter far more than length:\n\n"
        "## Investment Thesis\n"
        "The core view: what the DCF gap vs market and the multiples/peer/risk picture imply "
        "about how this stock is currently being priced.\n\n"
        "## Bull Case\n"
        "What has to go right for the upside to be realized, tied to the DCF gap and the "
        "growth/margin assumptions and any favorable multiple-vs-peer comparison.\n\n"
        "## Bear Case\n"
        "What could go wrong — e.g. rich multiples vs peers, an unfavorable DCF gap, or "
        "assumptions that look aggressive given the WACC and terminal growth.\n\n"
        "## Key Risks\n"
        "The concrete downside, quantified with the Monte Carlo VaR/ES where provided, plus "
        "what specifically would invalidate the thesis.\n\n"
        "## Valuation Commentary\n"
        "Interpret the DCF value vs the market price in light of the WACC, terminal growth, "
        "and the trailing multiples relative to the peer median — note whether the gap is "
        "driven mainly by the assumptions or by the relative multiples.\n\n"
        "## Catalysts\n"
        "Plausible developments that could narrow the gap between price and intrinsic value; "
        "if recent headlines are provided you may reference them, otherwise keep these tied "
        "to the valuation drivers above rather than inventing specific events.\n\n"
        "Be specific and cite the figures throughout. Do not add any sections beyond these "
        "six. End with a one-line disclaimer: this is AI-generated, educational, and not "
        "investment advice."
    )


def build_report_prompt(ctx: ThesisContext) -> str:
    """Build the prompt for the one-page PDF report's written analysis. Pure/deterministic.

    Unlike :func:`build_prompt` (the three-section AI Insights tab thesis), this asks for a
    SHORT four-section analysis — Investment Thesis, Bull Case, Bear Case, Key Risks — at a
    few sentences each, so the whole report fits on a single page.
    """
    facts_block = _facts_block(ctx)

    return (
        "You are an equity research analyst writing the written analysis for a CONCISE, "
        f"one-page investment report on {ctx.company_name} ({ctx.symbol}). Base your analysis "
        "ONLY on the figures below — a discounted-cash-flow (DCF) valuation, its gap versus "
        "the current market price, and trading multiples. Reference the ACTUAL numbers (the "
        "DCF value per share, the % gap vs market, the multiples, the WACC) in your "
        "reasoning; do not produce generic boilerplate.\n\n"
        "=== VALUATION DATA ===\n"
        f"{facts_block}\n"
        "=== END DATA ===\n\n"
        "Write in GitHub-flavored Markdown with EXACTLY these four sections, in this order, "
        "each as a level-2 heading. Write 2-3 short sentences of prose per section (NOT bullet "
        "lists). Keep the WHOLE response under ~180 words so it fits on one page:\n\n"
        "## Investment Thesis\n"
        "The overall view in 2-3 sentences, grounded in the DCF gap and multiples.\n\n"
        "## Bull Case\n"
        "Why it could outperform.\n\n"
        "## Bear Case\n"
        "Why it could underperform.\n\n"
        "## Key Risks\n"
        "The main risks and what would invalidate the thesis.\n\n"
        "Be specific and cite the figures. Do not add sections beyond these four, and do not "
        "give a buy/sell recommendation or a price target."
    )


def _default_model_factory(api_key: str, model: str) -> object:
    """Build a real Gemini model. Imported lazily so the SDK is only needed at call time."""
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model)


def _looks_like_rate_limit(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "resourceexhausted" in name
        or "ratelimit" in name
        or "429" in msg
        or "quota" in msg
        or "rate limit" in msg
        or "exhaust" in msg
    )


def generate_ai_thesis(
    ctx: ThesisContext,
    api_key: str | None,
    model: str = DEFAULT_MODEL,
    *,
    model_factory: Optional[ModelFactory] = None,
    prompt: Optional[str] = None,
) -> str:
    """Generate a grounded Bull/Bear/Risk thesis via Gemini and return Markdown text.

    Raises :class:`AIKeyError` if no key, :class:`AIRateLimitError` on a 429/quota error,
    and :class:`AIError` for any other failure (including an empty response). The
    ``model_factory`` hook lets tests inject a fake model so no real key/SDK is needed.
    Pass ``prompt`` to override the default three-section prompt (e.g. the concise
    report prompt); otherwise :func:`build_prompt` is used.
    """
    if not api_key:
        raise AIKeyError("No Gemini API key provided.")

    prompt = prompt or build_prompt(ctx)
    factory = model_factory or _default_model_factory
    try:
        gen_model = factory(api_key, model)
        response = gen_model.generate_content(prompt)
        text = (getattr(response, "text", "") or "").strip()
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001 — normalize any SDK/transport error
        if _looks_like_rate_limit(exc):
            raise AIRateLimitError(str(exc)) from exc
        raise AIError(str(exc)) from exc

    if not text:
        raise AIError("Gemini returned an empty response.")
    return text


def generate_report_thesis(
    ctx: ThesisContext,
    api_key: str | None,
    model: str = DEFAULT_MODEL,
    *,
    model_factory: Optional[ModelFactory] = None,
) -> str:
    """Generate the CONCISE four-section written analysis for the one-page PDF report.

    Same grounding and error semantics as :func:`generate_ai_thesis`, but uses
    :func:`build_report_prompt` (Investment Thesis / Bull / Bear / Key Risks, a few
    sentences each) so the report stays on a single page.
    """
    return generate_ai_thesis(
        ctx, api_key, model,
        model_factory=model_factory, prompt=build_report_prompt(ctx),
    )
