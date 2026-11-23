"""알림 확장 지점 (v1은 구현하지 않음).

이후 메일·Slack·SMS 알림을 붙일 때 이 인터페이스를 구현하고 service 호출부에서 이벤트를 넘긴다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

EventKind = Literal["created", "revealed", "consumed", "destroyed_by_customer", "expired", "revoked"]


@dataclass(frozen=True)
class SecretEvent:
    kind: EventKind
    secret_id: uuid.UUID
    customer: str
    title: str
    owner: str


class Notifier(Protocol):
    def on_event(self, event: SecretEvent) -> None: ...


class NullNotifier:
    def on_event(self, event: SecretEvent) -> None:
        return None
