"""LifeOS Windows Agent V1.

Only safe observation, notification, dry-run, and release capabilities live here.
"""

from .agent import LifeOSWindowsAgent
from .config import AgentConfig

__all__ = ["AgentConfig", "LifeOSWindowsAgent"]
__version__ = "0.1.0"
