"""
Multi-agent system for CodeCopilot.

Components:
    router.py   — fast keyword-based persona classifier (no API call)
    worker.py   — WorkerAgent: isolated agent that cannot spawn sub-agents
    __init__.py — exports

The orchestrator pattern is implemented in tools/spawn_agent.py,
which creates WorkerAgent instances on-demand.
"""

from .worker import WorkerAgent
from .router import route_persona

__all__ = ["WorkerAgent", "route_persona"]
