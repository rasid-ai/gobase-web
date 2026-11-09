"""Server-sent events: reading the agent's stream, and writing the SPA's.

The format is the browser's EventSource format: lines of `field: value`, and
a blank line to end each event. Only `event` and `data` mean anything here;
`id`, `retry` and comment lines (starting with `:`, used as keep-alives) are
read past.

Lines may end in `\\n` or `\\r\\n`. A lone `\\r` as a line ending, which the
format also allows, is not read: no server this backend talks to sends it.
"""

import json
from collections.abc import AsyncIterable, AsyncIterator


async def parse(chunks: AsyncIterable[str]) -> AsyncIterator[tuple[str, str]]:
    """Each complete event in a stream of text, as `(event name, data)`.

    An event with no `event` line is a `message`, as in a browser. An event
    with no `data` is not one at all. A last event that the stream ended
    before finishing (no blank line after it) is dropped: it may be cut short.
    """
    buffer = ""
    name: str | None = None
    data: list[str] = []

    async for chunk in chunks:
        buffer += chunk
        *lines, buffer = buffer.split("\n")
        for line in lines:
            line = line.removesuffix("\r")
            if line == "":
                if data:
                    yield name or "message", "\n".join(data)
                name, data = None, []
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                name = value
            elif field == "data":
                data.append(value)


def frame(event: dict) -> bytes:
    """One event for the SPA.

    The whole event goes in `data`, its `event` field included, so the client
    reads one JSON object per event and needs nothing from the `event` line —
    which is still written, for anyone reading the stream by eye. `json.dumps`
    never writes a raw newline, so the data is always one line.
    """
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event['event']}\ndata: {payload}\n\n".encode()
