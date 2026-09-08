# Ask — Q&A over the knowledge base

The chat renders inside the Map workspace page; layout is in
context/ui-rules.md. The engine — LLM provider and agent design — is
undecided and gets its own ADR before this is built.

Not built.

## Answering

A question is answered from the knowledge base's sources — documents,
tabular data and imagery metadata — combining them when the question
needs it. Answers stream, so the user sees content before generation
finishes.

Every factual claim about the data carries a citation resolving to a
catalog asset UUID with its metadata. When the knowledge base holds
nothing relevant, the answer says so rather than inventing one, with no
fabricated figures and no citations.

If generation fails partway the answer is marked incomplete and shows an
error — a truncated answer is never presented as complete — and the
session stays usable for the next question.

## Sessions

Chat sessions are private to the user who owns them. Reopening one brings
back its full history, in order.

## Area scope and map output

A question scoped to a selected area restricts both retrieval and the
answer to that area. An answer containing vector features returns them as
a map-renderable GeoJSON layer tied to that answer.
