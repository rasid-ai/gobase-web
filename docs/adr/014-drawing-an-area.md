# ADR-014: Drawing an area filters the map and scopes its layers

**Status:** Accepted · 2026-09-24

Suspends ADR-012's central behaviour, "drawn layers follow the map", for as
long as an area is drawn. ADR-012 is not edited and holds whenever no area
is set.

## Context

Draw-area was one of the three modes the map was specified with, and it
never did anything. `0aaa6c8` added it as a shell — a label, `dragPan` off,
a click guard — and `ca56708` took it out, because its purpose was to scope
a question and the ask path did not exist. The spec still described it, as
a rectangle.

Two things changed. ADR-013 made reading part of a file cheap, by pruning
row groups through the covering bbox column, so a layer can be read for an
arbitrary area without a full scan. And an area is useful before there is
any question to ask of it: to find what data exists in a place, and to look
at only that part of a layer.

## Decision

**Draw-area returns as a third mode. The user draws a polygon; while it is
set, the panel lists the assets overlapping it and every drawn layer is
read for it instead of for the view.**

- **A real polygon, not the rectangle the spec described.** A rectangle over
  Beirut is mostly sea. The polygon's envelope does the pruning, so a
  polygon costs no more to read than its bounding box.
- **The polygon replaces the view, and layers stop following the map.**
  Panning while an area is set changes nothing about what is drawn. The
  area is what the user chose to look at; re-reading on every pan would
  answer a question they did not ask. `PAGE_BUDGET` still caps each read.
- **Filter, never clip.** A feature intersecting the polygon comes back
  whole and is drawn past the outline. The map shows what the file holds,
  never a geometry the portal made.
- **Exact in area mode only.** A drawn area is tested with `ST_Intersects`
  against the polygon. A window keeps ADR-012's `ST_Intersects_Extent`,
  where over-inclusion lands off screen and is free. With an outline on
  screen it is not free: over a Beirut polygon the box test returns 30,586
  buildings where 25,858 are inside — 15% drawn outside the line. Behind
  the envelope prune the exact test costs 56 ms; unpruned it is 371 ms.
- **One endpoint for both geometries.** `GET /api/map/assets` takes a point
  or an area, never both. ADR-010 says that URL cannot carry a second
  meaning; this is not one. "What data is about this place" is one
  question, asked with two geometries, with one answer shape.
- **A point and an area are one selection.** Choosing either clears the
  other. Changing mode does not, so you can navigate around a drawn area.
- **Not in the URL.** By ADR-011's own rule a parameter exists only when
  state crosses a page boundary, and a drawn area never leaves `/map`. So
  `?bbox=` keeps its single meaning — the searched place — and nothing in
  ADR-011 changes. A drawn area cannot be sent as a link.
- **WKT in `?area=`**, over GeoJSON: about half the characters, and both
  PostGIS and DuckDB read it with `ST_GeomFromText`. It stays a GET, so the
  generated client and its query keys work unchanged.
- **Validated before either engine sees it.** `AreaField` refuses anything
  that is not one closed ring of 3 to 100 corners in range, flat, or
  crossing itself. The last is the important one: **PostGIS and DuckDB both
  answer a self-intersecting polygon silently** — no error, a wrong count.
  The draw tool refuses the same shapes at the click, and the server checks
  again. The validator was compared against PostGIS's `ST_IsValid` on the
  shapes that matter (bowtie, spikes in both directions, a ring touching
  itself, a flat ring, concave and star shapes) and agreed on every one.
- **terra-draw** for the drawing, with its MapLibre adapter; both MIT. It
  manages panning itself while a corner is dragged, so the old shell's
  `dragPan={mode !== 'area'}` does not come back — a large polygon needs
  panning mid-draw. `doubleClickZoom` is turned off while drawing, since
  closing a polygon is a click on its first corner.

## Why the corner cap is 100

The area travels in a GET query string, so its length is bounded by the
longest request line the production path accepts. That limit was first
assumed to be gunicorn's `limit_request_line` of 4094 bytes. **It is not.**
The Dockerfile runs `UvicornWorker`, which parses HTTP itself, so
gunicorn's limit never applies: a 9.2 KB request line was sent through the
production gunicorn command and reached Django.

The limit that binds is the host nginx's request-line buffer,
`large_client_header_buffers`, 8 KB by default and not changed by the vhost
in infra/README.md. Past it nginx answers 414 before the backend sees the
request.

A corner costs about 23 bytes URL-encoded at six decimals, so the real
ceiling is roughly 340 corners. 100 is about 2.4 KB — under a third of it,
with room for the rest of the URL — and it bounds the quadratic crossing
check. Hand-drawn polygons rarely pass 30 clicks. If the cap is ever
raised, it is nginx's buffer that has to move, not gunicorn's.

## Rejected

**The rectangle the spec described.** It reuses `?bbox=`, `BboxField` and the
existing bbox path with almost no backend change. Rejected because the
place a user means is rarely a rectangle, and the pruning that makes a
polygon affordable is the same pruning a rectangle uses.

**Clipping features to the outline.** Reads as the literal "only what is
inside". Rejected because the map would then show geometry that exists in
no file, and clipping a million buildings is real work on every read.

**Area and view together** — reading the intersection of the polygon and the
screen, so a read is never more than a screenful. Rejected because panning
away would empty the layer, which contradicts the area being what the user
chose.

**Putting the polygon in the URL.** Shareable, and the first thing that will
be missed in a demo. Rejected under ADR-011's rule, and because a polygon
in a query string that also carries `?bbox=` would give two areas with two
meanings in one link.

**Hand-rolling the polygon tool.** About 120 lines and no dependency, but no
corner dragging and no mid-point insertion, and those are what make a
polygon correctable rather than something you redraw from scratch.

## Consequences accepted

- **While an area is set, the map does not follow you.** That is the point,
  and it is also a surprise the first time: a user who pans away from their
  area sees the same layer they had, not what is under the new view.
- **`@types/geojson` is now a direct dependency.** terra-draw's type files
  import from `geojson`, which pulled those types into the program and
  turned react-map-gl's `data` prop from loosely to strictly typed. Two
  existing `<Source>` sites stopped compiling. Pinning `@types/geojson`
  directly makes the strict typing deliberate rather than a side effect of
  which library happens to be imported, and the two casts now say what they
  assert and why.
- **A drawn area is lost on reload**, like any component state.

## Revisit when

A drawn area needs to reach another page or survive a reload — then it
needs a URL parameter, and ADR-011's parameter set is what decides its name.
Or the ask path lands (GP-6, GP-7) — then the polygon travels with the
question, and anything answering from a *window* rather than an area has to
remember that a window is matched only by bounding box.
