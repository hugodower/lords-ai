from __future__ import annotations

from app.agents.base import BaseAgent


class SupportAgent(BaseAgent):
    agent_type = "support"

    def get_agent_type(self) -> str:
        return "support"


support_agent = SupportAgent()
