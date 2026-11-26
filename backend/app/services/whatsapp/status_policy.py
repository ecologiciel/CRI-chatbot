"""Conservative ordering for provider status notifications.

Acceptance is not delivery. Conflicting success/failure signals remain for
review rather than being silently overwritten. This policy does not establish
that a notification belongs to any particular message or institution.
"""

from dataclasses import dataclass

_PROGRESS = {"accepted": 0, "sent": 1, "delivered": 2, "read": 3}


@dataclass(frozen=True, slots=True)
class StatusDecision:
    state: str | None
    uncertain: bool


def decide_status(current: str | None, incoming: str) -> StatusDecision:
    if current is not None and not isinstance(current, str):
        return StatusDecision(None, True)
    if current not in {None, "failed", *_PROGRESS}:
        return StatusDecision(current, True)
    if incoming not in {"sent", "delivered", "read", "failed"}:
        return StatusDecision(current, True)
    if incoming == "failed":
        if current in {"delivered", "read"}:
            return StatusDecision(current, True)
        return StatusDecision("failed", False)
    if current == "failed":
        return StatusDecision(current, True)
    if current is None or _PROGRESS[incoming] > _PROGRESS[current]:
        return StatusDecision(incoming, False)
    return StatusDecision(current, False)
