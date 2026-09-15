from dataclasses import dataclass


@dataclass(frozen=True)
class Agent:
    agent_id: str
    role: str


def build_agent_registry(count: int):
    if count < 1:
        raise ValueError("agent count must be positive")
    return [
        Agent(agent_id=f"agent-{index:03d}", role=f"agent-{index:03d}")
        for index in range(1, count + 1)
    ]
