"""Plain-language definitions of the financial jargon used in the app.

Pure data. Each entry has:
  * ``term``  — the display name
  * ``short`` — a one-line gloss (used in tooltips / chips)
  * ``long``  — a fuller plain-language explanation (used in popovers / expanders)

Keys are stable slugs referenced by the UI. Definitions are written for a smart
non-expert: no prior finance assumed, no hand-waving.
"""

from __future__ import annotations

GLOSSARY: dict[str, dict[str, str]] = {
    "fcff": {
        "term": "FCFF: Free Cash Flow to the Firm",
        "short": "Cash the business generates for ALL investors, before financing.",
        "long": (
            "The cash a company throws off from operations that is available to everyone "
            "who funded it (both lenders and shareholders) *before* any debt payments. "
            "We build it as **EBIT×(1−tax) + D&A − Capex − ΔNWC**: start with after-tax "
            "operating profit, add back depreciation (a non-cash charge), then subtract "
            "what the company must reinvest in equipment (capex) and in working capital. "
            "It's “unlevered” because it ignores how the company is financed, which is why "
            "we discount it at the WACC and subtract debt only at the very end."
        ),
    },
    "wacc": {
        "term": "WACC: Weighted-Average Cost of Capital",
        "short": "The blended return investors require; our DCF discount rate.",
        "long": (
            "The average annual return the company must earn to keep both its shareholders "
            "and its lenders happy, weighted by how much capital each provides. Equity is "
            "more expensive than debt (shareholders take more risk), and debt is made "
            "cheaper still by the tax deduction on interest. We compute it as "
            "**(E/(E+D))×cost of equity + (D/(E+D))×after-tax cost of debt**. A higher WACC "
            "means future cash is discounted harder, lowering today's value."
        ),
    },
    "capm": {
        "term": "CAPM: Capital Asset Pricing Model",
        "short": "How we estimate the cost of equity from risk.",
        "long": (
            "A standard way to estimate the return shareholders demand: "
            "**cost of equity = risk-free rate + β × equity risk premium**. You start with "
            "what a “safe” government bond pays (risk-free), then add a premium for stock-"
            "market risk, scaled by the stock's beta (how much it swings versus the market)."
        ),
    },
    "beta": {
        "term": "β: Beta",
        "short": "How much the stock moves relative to the overall market.",
        "long": (
            "A measure of a stock's sensitivity to market moves. Beta = 1 means it tends to "
            "move with the market; >1 means it amplifies market swings (riskier, so a higher "
            "required return); <1 means it's steadier. It feeds directly into CAPM."
        ),
    },
    "erp": {
        "term": "ERP: Equity Risk Premium",
        "short": "Extra return investors demand for holding stocks over safe bonds.",
        "long": (
            "The additional annual return, on top of the risk-free rate, that investors "
            "expect for taking on the risk of the stock market as a whole. Historically "
            "around 4–6%. In CAPM it is multiplied by the stock's beta."
        ),
    },
    "nopat": {
        "term": "NOPAT: Net Operating Profit After Tax",
        "short": "Operating profit (EBIT) after taxes, ignoring debt.",
        "long": (
            "EBIT×(1−tax rate). It's the profit the core business would earn after tax if it "
            "had no debt at all, the starting point for unlevered free cash flow."
        ),
    },
    "terminal_value": {
        "term": "Terminal Value",
        "short": "The value of ALL cash flows beyond the explicit forecast.",
        "long": (
            "We can't forecast every year forever, so after the explicit forecast (say 5 "
            "years) we capture everything afterwards in a single “terminal value”. We use "
            "the **Gordon growth** method: assume the final-year cash flow grows at a small, "
            "constant rate forever. It is usually the largest single piece of a DCF, so its "
            "assumptions matter a lot."
        ),
    },
    "gordon_growth": {
        "term": "Gordon Growth (Perpetuity Growth)",
        "short": "Values a cash flow that grows at a constant rate forever.",
        "long": (
            "A formula for the value of a stream of cash flows growing at a constant rate "
            "g forever, discounted at rate r: **TV = CF×(1+g)/(r−g)**. It only makes sense "
            "when r > g; otherwise the value would be infinite. We apply it to the final "
            "forecast-year FCFF to get the terminal value."
        ),
    },
    "discount_factor": {
        "term": "Discount Factor",
        "short": "Converts a future dollar into today's dollars.",
        "long": (
            "Money in the future is worth less than money today. The discount factor for "
            "year t is **1/(1+WACC)^t**: multiply a future cash flow by it to get its "
            "present value. Later years are discounted more heavily."
        ),
    },
    "ev": {
        "term": "EV: Enterprise Value",
        "short": "The value of the whole business, debt + equity.",
        "long": (
            "What the entire operating business is worth to all investors, independent of "
            "how it's financed. In our DCF it's the sum of the present values of all future "
            "FCFF (forecast + terminal value). To get the value of just the shares, you "
            "subtract net debt from EV."
        ),
    },
    "net_debt": {
        "term": "Net Debt",
        "short": "Total debt minus cash the company could use to repay it.",
        "long": (
            "Debt net of the cash a company is sitting on: **total debt − cash & short-term "
            "investments** (optionally also long-term investments). We subtract it from "
            "enterprise value to bridge to equity value, because the cash effectively "
            "offsets the debt. Definitions vary on which cash counts; this app states "
            "exactly which one it uses everywhere it appears."
        ),
    },
    "moic": {
        "term": "MOIC: Multiple on Invested Capital",
        "short": "How many times the sponsor's money grew (e.g. 2.5×).",
        "long": (
            "In an LBO, the total cash returned to the equity investor divided by the cash "
            "they put in. A MOIC of 2.5× means they got back 2.5 dollars for every dollar "
            "invested. It ignores *how long* that took; that's what IRR adds."
        ),
    },
    "irr": {
        "term": "IRR: Internal Rate of Return",
        "short": "The annualized % return on the investment.",
        "long": (
            "The compound annual growth rate that turns the money invested into the money "
            "returned. With a single cash outflow at entry and a single inflow at exit over "
            "H years, **IRR = MOIC^(1/H) − 1**. A 2.5× MOIC over 5 years is about a 20% IRR. "
            "It's the headline number private-equity investors optimize."
        ),
    },
    "ev_ebitda": {
        "term": "EV/EBITDA: Enterprise Multiple",
        "short": "Business value as a multiple of its operating cash earnings.",
        "long": (
            "Enterprise value divided by EBITDA. A quick way to price a business: “it's "
            "worth 10× its EBITDA.” In an LBO, the **entry multiple** sets the purchase "
            "price and the **exit multiple** sets the sale price; buying low and selling "
            "high (multiple expansion) boosts returns."
        ),
    },
    "cash_sweep": {
        "term": "Cash Sweep",
        "short": "Using all spare cash to pay down debt each year.",
        "long": (
            "An LBO repayment rule where every dollar of free cash flow left after interest, "
            "taxes and reinvestment is used to pay down debt (a “100% sweep”). Paying debt "
            "down faster reduces interest and increases the equity value at exit, a key "
            "way LBO returns are generated, called deleveraging."
        ),
    },
    "leverage": {
        "term": "Leverage (Entry Leverage)",
        "short": "How much debt is used to buy the company, vs EBITDA.",
        "long": (
            "The amount of debt used in the buyout, usually expressed as a multiple of "
            "EBITDA (e.g. “5× leverage” = debt equal to five years of EBITDA). More leverage "
            "means less equity is needed up front, which can magnify returns, but also "
            "magnifies risk and interest costs."
        ),
    },
    "sources_uses": {
        "term": "Sources & Uses",
        "short": "Where the buyout money comes from and what it pays for.",
        "long": (
            "A simple table that must balance. **Uses**: what you're paying for (the "
            "purchase enterprise value plus transaction fees). **Sources**: how you're "
            "funding it (debt raised plus the sponsor's equity cheque). Sources = Uses by "
            "construction; the sponsor equity is whatever's left after the debt."
        ),
    },
}


def get(key: str) -> dict[str, str]:
    """Return a glossary entry, or a safe placeholder if the key is unknown."""
    return GLOSSARY.get(
        key, {"term": key, "short": "", "long": "(definition unavailable)"}
    )
