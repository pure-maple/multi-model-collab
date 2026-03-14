"""A2A (Agent-to-Agent) protocol implementation for vyane.

Enables true multi-agent collaboration with iterative feedback loops,
going beyond single-prompt dispatch to real agent-to-agent negotiation.
"""

from vyane.a2a.engine import CollaborationEngine, EngineConfig
from vyane.a2a.http_server import A2AServer
from vyane.a2a.patterns import (
    BUILTIN_PATTERNS,
    CollaborationPattern,
    get_pattern,
    list_patterns,
)
from vyane.a2a.types import (
    AgentCard,
    Artifact,
    CollaborationTask,
    ConvergenceDecision,
    ConvergenceSignal,
    Message,
    Part,
    TaskState,
    Turn,
)

__all__ = [
    "A2AServer",
    "AgentCard",
    "Artifact",
    "BUILTIN_PATTERNS",
    "CollaborationEngine",
    "CollaborationPattern",
    "CollaborationTask",
    "ConvergenceDecision",
    "ConvergenceSignal",
    "EngineConfig",
    "Message",
    "Part",
    "TaskState",
    "Turn",
    "get_pattern",
    "list_patterns",
]
