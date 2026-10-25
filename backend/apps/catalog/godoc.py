"""The only module that speaks to GoDoc's RAG server.

Everything above this speaks in portal terms: a question in, a vector and the
name of the model that made it out. The question has to be embedded by the
same model that embedded the catalog's cards, and that model lives in the data
platform's document service, not here — so the portal asks it, the way the
data platform's own search does (docs/adr/018, context/integrations/godoc.md).
"""

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class GoDocUnavailable(Exception):
    """The server could not be reached, or did not answer as a server would."""


class GoDocError(Exception):
    """The server answered, but refused the request or gave no vector."""


def embed(text: str) -> tuple[str, list[float]]:
    """One text as a vector, with the id of the model that made it.

    The bare text, with no instruction prefix: the cards were embedded the same
    way, and a query embedded differently from its corpus ranks worse, not
    better (gobase/modalities/document/client.py is the reference).
    """
    try:
        response = httpx.post(
            f"{settings.GODOC_URL}/rag/embed",
            json={"texts": [text]},
            timeout=settings.GODOC_TIMEOUT_SECONDS,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        # The type, not the message: the question is chat content, and an
        # httpx message can quote the request it was making (CLAUDE.md).
        raise GoDocUnavailable(type(exc).__name__) from exc

    if response.status_code >= 500:
        raise GoDocUnavailable(f"HTTP {response.status_code}")
    if response.status_code >= 400:
        # 400 is a body it will not take and 413 more texts than it allows:
        # the request is wrong and the server is up, so not an outage.
        raise GoDocError(f"HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError:
        raise GoDocUnavailable(f"HTTP {response.status_code} and no JSON") from None

    model = payload.get("model") if isinstance(payload, dict) else None
    vectors = payload.get("vectors") if isinstance(payload, dict) else None
    if not model or not vectors or not vectors[0]:
        raise GoDocError("No vector in the answer")
    return model, vectors[0]
