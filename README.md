#Valuation Explainer

An interactive Streamlit web app that **teaches DCF and LBO valuation to non-experts**.
Enter a public-company ticker and the app:

- explains what the company does and shows its **real** financials,
- walks you through valuing it two ways — a **DCF** (discounted cash flow) and an **LBO**
  (leveraged buyout) — showing every intermediate number,
- highlights financial jargon (FCFF, WACC, terminal value, MOIC, IRR, …) with click-to-expand
  plain-language definitions,
- lets you move sliders (WACC, growth, multiples, leverage, hold period) and watch the
  valuation and charts update live.

> Educational use only — not investment advice.** All outputs depend on the assumptions
> you choose and may rely on delayed or incomplete data.

## Stack

- **Python 3.12**, **Streamlit** (UI), **pandas** (tables), **plotly** (charts)
- Financial data from the [Financial Modeling Prep (FMP)](https://financialmodelingprep.com) API
- The **valuation engine is a pure, unit-tested Python package** with no Streamlit/network
  dependencies — so the frontend could be swapped without touching the finance.

## Architecture

```
engine/      Pure valuation logic — DCF, LBO, WACC/CAPM, models, history-seeded defaults.
             No I/O, no Streamlit. Covered by golden-number tests.
data/        Financial Modeling Prep client + JSON→model mapping. Network I/O only.
content/     Plain-language glossary (pure data).
ui.py        Presentation helpers: theme CSS, glossary popovers, plotly charts.
app.py       Streamlit UI — the only place Streamlit is imported. No finance math.
tests/       pytest suite with hand-computed expected values in the comments.
```

Net debt is computed consistently everywhere as **total debt − cash & short-term
investments** (the same figure the DCF equity bridge uses). A sidebar toggle can also
subtract **long-term investments**, which is material for cash-rich firms like Apple.

## Run locally

Requires Python 3.10+.

```bash
git clone <your-repo-url> valuation-explainer
cd valuation-explainer

python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

Provide your FMP API key using **any one** of these (checked in this order):

```bash
# 1) Streamlit secrets (recommended — also how Streamlit Cloud works)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
#   then edit .streamlit/secrets.toml and paste your key

# 2) Environment variable
export FMP_API_KEY=your_key_here

# 3) .env file
cp .env.example .env
#   then edit .env
```

Get a free key at <https://financialmodelingprep.com/developer/docs>. Then:

```bash
streamlit run app.py
```

Open the local URL it prints (usually <http://localhost:8501>), enter a ticker (e.g.
`AAPL`) and click **Load company**.

## Run the tests

The finance is verified by golden-number tests with hand-computed expectations:

```bash
pip install pytest
pytest -q
```

## Deploy to Streamlit Community Cloud

Streamlit Community Cloud deploys straight from a **public GitHub repo** and is free.

### 1. Push this project to GitHub

Make sure your API key is **not** committed — `.env` and `.streamlit/secrets.toml` are in
`.gitignore`. Verify with `git status` before pushing.

```bash
cd valuation-explainer
git add .
git commit -m "Valuation Explainer: DCF & LBO teaching app"
# create an EMPTY repo on github.com first (no README), then:
git branch -M main
git remote add origin https://github.com/<your-username>/valuation-explainer.git
git push -u origin main
```

### 2. Create the app on Streamlit Cloud

1. Go to <https://share.streamlit.io> and sign in with GitHub (authorize access to the repo).
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `<your-username>/valuation-explainer`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **Advanced settings** → **Secrets** and paste:
   ```toml
   FMP_API_KEY = "your_real_key_here"
   ```
   (This is the Cloud equivalent of your local `.streamlit/secrets.toml`. The app reads
   `st.secrets["FMP_API_KEY"]`.)
5. Click **Deploy**. First build installs `requirements.txt`; after a minute you'll get a
   public URL like `https://<your-app>.streamlit.app`.

### 3. Updating the live app

Just push to `main` — Streamlit Cloud redeploys automatically:

```bash
git add -A && git commit -m "tweak" && git push
```

To change the key later: app menu (⋮) → **Settings** → **Secrets**.

## Project notes

- The valuation engine is intentionally simple and transparent for teaching: end-of-year
  discounting, constant DCF driver ratios, opening-balance interest in the LBO, 100% cash
  sweep, and `IRR = MOIC^(1/H) − 1`. Every assumption is documented in the engine modules.
- Default assumptions are seeded from each company's own history and are fully overridable.
