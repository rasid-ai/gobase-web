# Spec: Ask (Q&A over the knowledge base)

UI-agnostic: the chat renders inside the Map workspace page (layout in
context/ui-rules.md); these requirements hold regardless. Engine choice
is an open Gate B decision; these requirements bind any engine.

---

**HLR-014** — WHEN a user submits a question, the system SHALL answer it
from the knowledge base's sources — documents, tabular data, and imagery
metadata — combining sources when the question requires it.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a question whose answer spans a document and a tabular dataset
WHEN it is asked
THEN the answer draws on both and cites both

---

**HLR-015** — WHILE an answer is being generated, the system SHALL stream
it; the user sees content before the answer is complete.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a submitted question
WHEN generation begins
THEN partial answer text renders before generation finishes

---

**HLR-016** — The system SHALL attach citations to every factual claim
about the data, each citation resolving to an asset in the catalog.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a completed answer containing factual claims
WHEN its citations are inspected
THEN each resolves to a catalog asset (UUID) with its metadata
AND no claim about the data is presented without one

---

**HLR-017** — IF the knowledge base contains nothing relevant to a
question, THEN the system SHALL say so instead of inventing an answer.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a question about data that was never ingested
WHEN it is asked
THEN the answer states that nothing relevant was found
AND contains no fabricated figures and no citations

---

**HLR-018** — The system SHALL keep each user's chat sessions, private to
that user; WHEN a user reopens a session, its full history SHALL be
present.
Priority: Must · Phase: MVP
**Done means:**
GIVEN user A has a session with messages
WHEN user B lists sessions
THEN A's session is absent
AND WHEN user A reopens the session after signing out and in
THEN every prior message is present in order

---

**HLR-019** — WHEN a question is scoped to a selected area, the system
SHALL restrict retrieval and the answer to that area.
Priority: Must · Phase: MVP
**Done means:**
GIVEN one asset inside the selected area and a comparable one outside it
WHEN an area-scoped question is asked
THEN the answer uses and cites only the asset inside the area

---

**HLR-020** — WHEN an answer includes vector features, the system SHALL
return them as a map-renderable layer tied to that answer.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a question whose answer includes vector features
WHEN the answer completes
THEN the response carries a GeoJSON layer
AND the layer can be displayed on the map and associated with the answer

---

**HLR-021** — IF answer generation fails partway, THEN the system SHALL
mark the answer as incomplete and show an error; a truncated answer is
never presented as complete.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a generation failure mid-stream
WHEN the failure occurs
THEN the user sees an error state on that message
AND the session remains usable for the next question
