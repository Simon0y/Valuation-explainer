"""Data layer — Financial Modeling Prep access.

Contains all network I/O. Has NO Streamlit imports and NO finance math. Its only
dependency on the engine is `engine.models` (the return types). This keeps fetching
testable and lets the engine stay pure.
"""
