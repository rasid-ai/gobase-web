# UI Registry

Which components exist and what they match. One component, one line —
history belongs in the diary, reasoning in an ADR (guarded by /imprint).

| Component | Matches |
|---|---|
| `ui/Button` | Flat, hairline, zero shadow, radius `--radius`. Variants: primary (emerald fill, near-black text), outline, ghost, link. Sizes sm/md/lg. `asChild` for link buttons. |
| `ui/Input` | h-10, `bg-input`, hairline border, `--ring` focus ring; `aria-invalid` turns the border and ring destructive. |
| `ui/Label` | Radix label, 14px medium, paired with an `Input` by `htmlFor`. |
| `ui/Alert` | Inline form-level error. Destructive hairline border on a 10% destructive tint. No icon, no shadow. |
| `PortalWordmark` | GEO + emerald PORTAL, 14px bold, tracking 0.1em. The header identity mark on every page. |
| `LandingPage` | Unauthenticated root. Header, hero + decorative map graphic, three capability cards, footer. Mono micro-labels. No API calls. |
| `SignInPage` | Centered 380px column, mono eyebrow, hairline card, RHF + Zod, inline `Alert` on failure. |
| `AppShell` | Authenticated frame: header, Atlas/Assets/Data Governance nav, mono identity chip, theme toggle, sign out. Every link owns its whole subtree for the active highlight. |
| `ui/Badge` | Status pill: token tinted 15% behind the token as text, radius-full. A dot precedes the label — disc for live states, ring for inert ones, so colour never carries the meaning alone. Tones: success/running/failed/queued/neutral. |
| `ui/Dialog` | Radix dialog. Hairline border on `bg-popover`, no shadow, overlay is `bg-background/80` with a 2px blur. Title, description, right-aligned footer. |
| `ui/Skeleton` | Pulsing `bg-muted-foreground/10` block for a data view that has not answered. |
| `RunsPage` | Data Governance: page header with relative last-read, Refresh, and Admin-only Run pipeline. Status filter chips, then rows in a hairline panel sharing one grid so run and step badges align; a row expands in place. Load more keeps the pages it has. Explicit empty, filtered-empty, loading, and pipeline-unreachable states. |
| `RunLogs` | Event log behind a disclosure inside an opened run, fetched only when asked for. Mono rows: time, level, step key (column always reserved so messages align), message. Minimum-level chips default to info and report how many lines are hidden; error rows expand to a stack. |
| `ui/Toast` | Transient failure notice, bottom-centre, `aria-live="polite"`. Hairline destructive border on a 10% tint like `Alert`, plus a Close control; self-dismisses after 6s. `Alert` stays the inline, in-place version. |
| `AssetDetailPanel` | One asset's metadata: mono data type, then Draw and Clear as outline buttons on one row, then a hairline definition list of whatever keys the catalog holds. Draw becomes Redraw once the asset is on the map, and a spinner while it loads. |
| `DrawArea` | The polygon tool, live only in draw-area mode; renders nothing itself. terra-draw draws with the `--map-selection` token (converted to hex by `mapTokens.hex`, since the tool takes nothing else) at 0.15 fill and a 2px outline. A finished polygon is handed up and cleared from the tool; the page then outlines it as its own source — `--map-selection`, 0.08 fill, 2px line, drawn above the data layers — so the area survives leaving the mode. A refused click (over 100 corners, or edges crossing) raises a `ui/Toast` saying which. |
| `Clear area` | Outline-style mono button beside the mode switch, shown only while an area is drawn. Same hairline border and `bg-background/95` as the switch it sits next to. |
| `LayersPanel` | The layers drawn on the map, docked bottom-left. Hairline panel, mono header with a count and Clear all; one row per layer with a visibility checkbox, truncatable name, count of features in the current view or drawn area (`+` when there are more than the budget read, `—` when it could not be read; the tooltip says which scope) and remove. The truncation note on an asset row says "zoom in for the rest" for a view and "draw a smaller area for the rest" for a drawn area, because zooming does nothing to an area. Renders nothing when empty. |
| `PlaceSearch` | Go to a place or a coordinate, docked under the mode switch. One box for both — two numbers are a coordinate, anything else is searched for. Mono micro-label, `Go` outline button, inline `Alert` on a bad value with `aria-invalid` on the field; place candidates in a `ui/Combobox` popup beneath. |
| `AssetsPage` | The catalog: filter rail left, card grid right. Header with the range on screen out of the total and a native sort select; numbered pages under the grid, and the grid dims rather than empties while the next page is read. Cards are hairline on `bg-card` — mono data type and format across a divided top, then name, mono id, topic - size, and a divided foot with the mono ingestion date and a Locate on map link. Explicit loading, empty, filtered-empty and error states. |
| `AssetFilters` | The Assets rail: search field that filters names and offers places at once, a removable area chip under it, mono group labels, checkbox rows per data type with mono counts, radio rows for the ingestion window, and a Clear all filters ghost button that appears only once a filter is set. Data types are rendered from the API, never from a list held here. |
| `ui/Pagination` | Numbered page control for an offset-paged list. Previous and Next as outline buttons either side of square page numbers — the current one filled, the rest ghost — with `…` where numbers were left out. Renders nothing for a single page. |
| `ui/Combobox` | A text box that offers options beneath it, hand-rolled on the ARIA 1.2 pattern: focus stays in the input and `aria-activedescendant` moves. Hairline `bg-popover` panel, no shadow, `z-20`; mono section label, two-line rows — name in body text, coordinate in mono — and a neutral `muted-foreground/10` highlight. Messages sit outside the listbox, so none can be arrowed onto. |
| `PlaceOptions` | What a place search shows: the `PLACES` label and its rows, or one line for searching, nothing found, failed, and unavailable. |
