# Valuation Explainer

An interactive Streamlit app that teaches **DCF** and **LBO** valuation to non-experts.
Enter a public-company ticker and the app explains what the company does, shows the real
financial data behind it, and (in later stages) walks you through valuing it — with every
piece of jargon highlighted and explained in plain language.

Financial data comes from the [Financial Modeling Prep (FMP)](https://financialmodelingprep.com) API.

> Educational use only — not investment advice.

## Architecture

All valuation logic lives in `engine/`, a pure package with **no Streamlit and no network
dependencies**, so the frontend can be swapped later. Data fetching lives in `data/`. The
Streamlit UI (`app.py`) only wires them together.

```
engine/    pure valuation logic (DCF, LBO, WACC) + data models   ← unit-tested, no I/O
data/      Financial Modeling Prep client + JSON→model mapping    ← network I/O only
content/   plain-language glossary (added in Stage 3)
app.py     Streamlit UI (the only place Streamlit is imported)
tests/     pytest suite with hand-computed golden numbers (Stage 2)
```

## Build status

- **Stage 1 — Data layer ✅** (this build): enter a ticker → company profile + key
  financials (revenue, EBIT, EBITDA, D&A, capex, Δ working capital, net debt, shares).
- Stage 2 — Valuation engine (DCF + LBO) — _next_
- Stage 3 — Educational layer (glossary, walkthroughs, live sliders)
- Stage 4 — Polish & deploy to Streamlit Community Cloud

## Setup & run (Stage 1)

```bash
cd ~/projects/valuation-explainer
pip install -r requirements.txt

# Provide your FMP API key (choose ONE):
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then edit it
# …or:  export FMP_API_KEY=your_key
# …or:  cp .env.example .env  and edit it

streamlit run app.py
```

Then enter a ticker (e.g. `AAPL`) in the sidebar and click **Load company**.

The API key is read from `st.secrets` → `FMP_API_KEY` env var → `.env`, and is never
committed (`.env` and `.streamlit/secrets.toml` are gitignored).
