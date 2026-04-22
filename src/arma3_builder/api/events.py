"""Server-sent-events helpers for streaming pipeline progress to the UI."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class ProgressEvent:
    event: str
    data: dict

    def format(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False)
        return f"event: {self.event}\ndata: {payload}\n\n"


@dataclass
class EventBus:
    """Tiny in-process event bus.

    One bus per generation request; the pipeline publishes progress on it and
    the SSE response handler drains it. When the pipeline is done, `finish()`
    closes the stream.
    """

    queue: asyncio.Queue[ProgressEvent | None] = field(default_factory=asyncio.Queue)

    async def publish(self, event: str, **data) -> None:
        await self.queue.put(ProgressEvent(event=event, data=data))

    async def finish(self) -> None:
        await self.queue.put(None)

    async def stream(self) -> AsyncIterator[str]:
        while True:
            evt = await self.queue.get()
            if evt is None:
                return
            yield evt.format()
