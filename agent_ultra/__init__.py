"""Agent-Ultra: head agent + 1000-copy system skeleton.

Local scaffold only. No model calls, no containers, no live browser here:
those paths are honest stubs marked UNTESTED (see ARCHITECTURE.md).
What IS real in this package: copy workspaces + browser-profile dirs,
the copy -> head report protocol (JSONL), mechanical Arena-style
elimination ranking, and the Agent OS dispatcher bridge (761 tools).
"""

from .head import HeadAgent
from .copy_agent import CopyAgent
from .spawner import Spawner
from .chat_store import ChatStore
from . import tools_extra
from . import tool_pipeline

__all__ = ["HeadAgent", "CopyAgent", "Spawner", "ChatStore",
           "tools_extra", "tool_pipeline"]
