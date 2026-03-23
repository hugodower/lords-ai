from __future__ import annotations

from app.agents.base import BaseAgent


class SDRAgent(BaseAgent):
    agent_type = "sdr"

    def get_agent_type(self) -> str:
        return "sdr"


sdr_agent = SDRAgent()
