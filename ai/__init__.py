"""
ai/__init__.py – CivicAI AI Package
Exposes the main orchestrator so callers can do:
    from ai import AIEngine
"""
from ai.ai_engine import AIEngine   # noqa: F401

__all__ = ["AIEngine"]
