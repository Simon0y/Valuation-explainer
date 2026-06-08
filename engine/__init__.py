"""Pure valuation logic.

This package contains NO network calls and NO Streamlit imports. Everything here is
deterministic and unit-testable in isolation, so the Streamlit frontend can be replaced
without touching any of the finance.

Stage 1 ships only the data models (`models`). The DCF / LBO / WACC engines are added
in Stage 2.
"""
