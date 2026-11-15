# ADR-029: The portal reads a raster's pixels, for figures and for a clip

**Status:** Accepted · 2026-11-10
**Builds on:** docs/adr/024 (the agent reads through this API), docs/adr/022
(desktop clients read rasters from the lake), docs/adr/014 (drawn areas)

## Context

ADR-024 decided that the Ask agent's `raster_clip` tool gets two things from
this backend: statistics of a raster over an area, with each class's share
for a classified raster, and a clip download. It said the backend would need
`rasterio`, and left the details open.

Until now nothing in the portal read a raster. ADR-022 hands a desktop
client short-lived credentials and lets it read the COG (a GeoTIFF laid out
so a reader can fetch part of it) itself. That fits ArcGIS Pro. It does not
fit the agent, which holds no lake credentials and must get small answers
(ADR-024), or the browser, which never talks to the lake.

The local catalog has two kinds of raster, read on 2026-11-10:

- Seven Esri land-cover rasters: one `uint8` band, EPSG:32637, 10 m pixels,
  16,698 x 18,673, nodata 0, six overviews. The class legend is JSON text in
  the file's `classes` tag: `{"1": "water", "7": "built_area", …}`.
- Four city satellite images: three `uint8` bands, EPSG:4326, about 0.5 m
  pixels, up to 10,252 x 17,156 (560 MB).

## Decision

### `rasterio` joins the backend

Pinned at 1.5.1, the version the data platform runs. Its wheel bundles GDAL
3.12 and PROJ, so the image needs no system package; it adds about 115 MB
installed. `apps/map/raster.py` is the only module that imports it, on first
use, as `chunks.py` does with `lancedb`.

- **It reads with the `LAKE_S3_*` settings**, the read-only ones DuckDB uses.
  They are passed through `rasterio.Env`, which is scoped to one read and one
  thread; no key is written into the process's environment. rasterio takes
  keys only through its own S3 session, which loads `boto3` (already here
  for ADR-022).
- **Four inherited variables are dropped before the first read:**
  `PROJ_DATA`, `PROJ_LIB`, `GDAL_DATA`, `GDAL_DRIVER_PATH`. Conda exports
  them shell-wide, and an old `PROJ_DATA` fails every CRS lookup. The data
  platform drops the same four. No other module here uses GDAL.
- **Failures** follow the lake's rule: unreachable or refused is 503, any
  other failed read is 502. A lake that answers with an error of its own
  (5xx, "reduce your request rate", an expired token, a clock too far off)
  is 503: it may work on the next try, and "could not be read" reads as
  permanent. Only rasterio's, GDAL's and the S3 session's
  errors count as a failed read; anything else is a bug in the reader and
  answers 500, so it is seen and not hidden as "the raster could not be
  read".
- **No path reaches a log.** GDAL's messages quote the object's URL, so a
  failure is logged and passed on by its exception type only. rasterio
  also logs every GDAL error itself, on its `rasterio` loggers, with that
  URL. Those loggers are switched off when rasterio is first imported.
- **A dead lake is given up on without a retry.** Five seconds to connect,
  eight seconds of near silence on a request that connected, thirty for
  any one request, no retry. A lake that drops packets fails a read after
  15 seconds (measured: GDAL makes three connection attempts). GDAL waits
  thirty seconds before a retry, so one retry made the same read take 85
  seconds. "Consequences" has each case.
- **GDAL's own memory is bounded.** Its block cache is set to 32 MB (the
  default is 5% of the machine's memory), and it remembers nothing about a
  lake object after the file is closed (`CPL_VSIL_CURL_NON_CACHED`). A
  replaced object or revoked credentials are then never answered from
  memory. Measured on the real rasters: no slower.

### `GET /api/map/assets/{asset_id}/raster-stats`

For an active raster asset it answers
`{asset_id, pixels, approximate, bands, classes, other_classes}`.

- **The place** is a `bbox` or a drawn `area`, never both, SRID 4326. With
  neither, the whole raster is measured.
- **Only the window over the place is read.** The place is cut to the
  raster's footprint in lon/lat, then moved into the raster's CRS, with
  each edge cut into short pieces first, because a straight edge in
  lon/lat is a curve in a projected CRS.
- **The cut comes first because a projection has limits.** A place far
  wider than the raster, such as a zoomed-out map view, has corners
  outside the area the raster's projection is defined for. For UTM zone
  37N that is anything reaching past about 51°W or 129°E. Moved corner by
  corner, such a place came back as an error (a 502) or as infinity (a
  false "no pixels"). What is left after the cut lies on the raster.
- **A raster across the antimeridian has two footprints,** one on each
  side of 180°, and the place is cut against both. A raster whose extent
  has no lon/lat box at all (the whole world in Mollweide), or that is
  stored with longitudes from 0 to 360, takes no place, where the first
  version gave a wrong count without a word. That is a 422 with a sentence
  that says so, not the lake's 502: the lake and the file are fine, and
  the 502's body said "The data lake returned an error". Not a 400 either:
  the caller's place is good. Without a place such a raster is still
  measured whole. A world-wide lon/lat grid that reaches less than a pixel
  past 180° (pixels centred on the round degrees) is cut back to the line
  and takes a place like any other.
- **A pixel counts when its centre is inside the place.** A bbox is its
  rectangle, and an area is its polygon, so a triangle counts about half
  the pixels of its box. A place smaller than a pixel counts the pixels it
  touches; a place with no size (a bbox whose corners are equal) counts the
  one pixel it is in, and on a pixel edge the pixel that starts there.
  `pixels` is that count.
- **`bands`** gives `index`, `min`, `max`, `mean` and `valid_percent` for
  each band, over the pixels that hold data: not nodata, not masked out,
  and not NaN or infinity. `valid_percent` is their share of `pixels`.
  An alpha band (transparency) is not listed; it only decides which
  pixels hold data.
- **Figures keep nine significant digits**, not a fixed number of decimal
  places. A mean of 3e-9 or a share of one pixel in ten million is small,
  not zero.
- **`classes`** is for a classified raster: one whole-number band with a
  legend in the file's `classes` tag. Each row is `value`, `name`, `pixels`
  and `share`, largest first. `share` is a part of the pixels that hold
  data, from 0 to 1. A value the legend does not name is still reported,
  with a null name. For any other raster `classes` is null.
- **`classes` holds at most 256 rows.** Every value beyond them is summed
  into `other_classes` (`values`, `pixels`, `share`), so nothing is dropped
  without a word and the shares still add up to 1. It is null when
  `classes` holds them all.
- **A budget, `RASTER_STATS_MAX_PIXELS` (default 4,000,000).** A window
  above it is read at reduced size, with nearest-neighbour resampling so a
  class stays a class, and the answer says `approximate: true`. `pixels`
  then counts the reduced grid. On a COG the reduced read comes from an
  overview: the whole land-cover raster answers in about 0.2 s. The
  reduced grid is never above the budget, a thin strip included.
- **The window is read a chunk of rows at a time,** every band of a chunk
  in one read, and the figures are added up as it goes. A chunk is whole
  rows of the raster's blocks, about 4 MB of blocks before compression,
  and never more than 16 MB of pixels held. So what a read holds does not
  grow with the band count, and the time limit below is looked at every
  few megabytes. The first version read a band at a time: "Consequences"
  has what that cost.
- 422 for a raster no place can be put on (above).
- **A place that misses the raster is a 200** with `pixels: 0` and no
  figures. "Nothing here" is an answer, not an error.
- 404 for anything but an active raster; 400 for a bad place; 502 and 503
  as above.

### `GET /api/map/assets/{asset_id}/clip.tif`

The raster's pixels over a place, as a GeoTIFF to download.

- **A place is required:** `bbox` or `area`.
- **The clip is the box, never a polygon mask.** A drawn area is clipped to
  its envelope. This is the data platform's rule
  (`gobase/cli/export_raster.py`), kept so a clip from the portal and one
  from the platform are the same file.
- **Nothing is resampled.** The window is on the raster's own grid, in its
  own CRS, rounded outwards so it covers the place.
- **It carries what makes the raster readable:** nodata, a mask stored
  with the raster, the colour table, band descriptions, scales, offsets
  and units. Tiled and DEFLATE-compressed.
- **Tags are carried by name, from a list.** The list is what the data
  platform writes (`classes`, `collection`, `description`, `source`,
  `year`), `AREA_OR_POINT`, and the descriptive TIFF fields. A band
  carries only GDAL's `STATISTICS_` tags. The first version left out tags
  whose value looked like a path, and a path has more shapes than a
  pattern can name.
- **A listed tag's value is checked too, by what the tag is.** The legend
  is written again from its entries: a whole-number value and a name that
  is text without the shape of a path. Nothing else in that tag is
  carried. A tag that holds a sentence
  (`description` and the two TIFF text fields) is left out when it has the
  shape of a path. Every other listed tag is a short value, and is left
  out if it holds a slash or a backslash at all. On 2026-11-10 no tag of
  the catalog's rasters holds one, so nothing real is lost.
- **A cap in bytes, `RASTER_CLIP_MAX_BYTES` (default 64 MB).** It counts
  the window's pixels before compression: width x height x bands x bytes
  per value. A larger window is a 400 that gives its pixel count, its
  size and the size allowed. The check is made before any pixel is read.
  A place that misses the raster is a 400 too: there is no file to give.
- **Why bytes.** The first cap was 16,000,000 pixels, width x height. Four
  `float32` bands at that cap are 256 MB of pixels, and the clip held
  three copies of itself at its peak: a review measured about 1.2 GB for
  one request.
- **`Content-Disposition: attachment`**, named `<the asset's name>_clip.tif`.
- **Cached as the document PDF is** (docs/adr/027): an ETag and
  `Cache-Control: private, no-cache`. The ETag is worked out from the
  asset id, the box and a format version (`CLIP_FORMAT`), with no read:
  assets are content-addressed, as for the features page (docs/adr/015).
  A match is a 304 after the catalog lookup and before the lake.
- **A HEAD request builds no clip.** It reads the raster's header, and
  answers with the status and headers a GET would. Its `Content-Length`
  is 0: the file's length is not known without making it.
- **A clip the portal could not write is a 503 of its own,** "The portal
  could not write the clip. Try again later." The temporary folder was
  full or could not be written. Not a 502, which blames the lake, and not
  a 500: the request is good, and other clips finishing clears it.
- 404 for anything but an active raster; 502 and 503 as above. A JWT or an
  API key may read both endpoints (docs/adr/021). 422 for a raster no
  place can be put on, as for `raster-stats`.
- **`If-None-Match` is compared weakly,** as RFC 9110 asks: `"x"` and
  `W/"x"` name the same copy.

## Checked on real data, 2026-11-10

- Land cover 2023 over a bbox on Tripoli: 428,788 pixels, built-up 60.19%,
  in 0.07–0.4 s. An independent recount (every pixel centre of the clip
  moved back to lon/lat and tested against the bbox) gave the same pixel
  count, the same seven class counts and the same mean.
- A 2.7 MB clip of a satellite image (934 x 1,131, three bands) in 0.17 s.
- A satellite clip over the whole city was refused: 132,129,013 pixels.
- After the review: the 2023 land cover with a world-wide bbox, with
  `(-52, 0, 80, 60)` and with `(30, 0, 131, 40)` answers the whole raster
  (3,997,574 pixels, approximate) in 0.11 s. Before the cut to the
  footprint the first answered `pixels: 0` and the other two 502.

## Rejected

- **DuckDB's spatial extension for rasters.** It reads the lake already, but
  it has no windowed raster read.
- **A tile server (TiTiler).** Tiles are pictures for a map, not pixel
  values, and it is a second service to deploy. It stays the plan for
  drawing rasters on the web map (docs/adr/003).
- **A polygon-masked clip.** Pixels outside the polygon would become
  nodata, which needs a nodata value the raster may not have, and the file
  would differ from the data platform's clip of the same place.
- **Handing the agent lake credentials, as ADR-022 does for desktops.**
  ADR-024 already decided the agent holds none.
- **Refusing a large place for statistics.** "What covers Lebanon?" is a
  fair question, and an overview answers it well enough when the answer
  says it is approximate.
- **Reading the legend from the catalog.** `geo_raster_layers.tags` holds
  the same text, but the file is open anyway, and the file is what the
  figures come from.

## Consequences

- **The backend image grows by about 115 MB**, and a worker that has read a
  raster holds GDAL in memory.
- **A read holds a worker** for its length. Both endpoints are synchronous
  views. Measured on 2026-11-10, for both endpoints: a lake that drops
  every packet holds one for 15 seconds; one that connects and then says
  nothing, 24 seconds; one that sends headers and then stalls, or drips a
  byte a second, 8 seconds. Each answers 503.
- **Why those figures.** GDAL makes up to three requests to open a raster,
  and no option turns that off, so each is bounded alone: 5 seconds to
  connect, and 8 seconds of fewer than 1,024 bytes a second
  (`GDAL_HTTP_LOW_SPEED_TIME` and `_LIMIT`). Before the low-speed rule a
  silent lake cost three whole 30-second requests: 90 seconds.
- **A slow lake is bounded by `RASTER_READ_TIMEOUT_SECONDS` (default 60).**
  A read still going then stops before its next chunk of rows, or strip of
  a clip, and answers 503. It can run over by the step it is in, which is
  a few megabytes. A clip at the cap pulls 45 to 70 MB from the lake, by
  the window, so 60 seconds asks for 6 to 9 Mbit/s; on a slower link the
  largest reads fail and smaller ones work, and the setting is there to
  raise. Zero means no limit of this kind.
  context/integrations/raster.md has the measurements.
- **Why chunks.** The limit was first looked at once a band. One band of a
  long, thin place over the satellite image was sixty requests, each well
  inside GDAL's own limits, and the image stores its three bands together,
  so every block was fetched three times: 166 MB. Through a link throttled
  to 400 KB/s that read ran 114 seconds, and 303 seconds at 150 KB/s. Read
  in chunks, all bands at once, the same place pulls 39 MB; the two runs
  are now 52 seconds (an answer) and 60 to 69 seconds (a 503: the limit,
  plus the chunk it was on).
- **The agent stops waiting first.** `gobase-agent` gives a call 15
  seconds. A read that takes longer goes on here until it ends or reaches
  a bound above, with its worker held, while the agent has already told
  the model the portal is unavailable. A second question starts a second
  read beside it. Nothing stops a read whose caller has left.
- **A stall after the headers is told by the wait, not the message.** GDAL
  reports it as an unreadable file. A step that failed after waiting as
  long as a stalled request does is a 503. A slow step that then fails for
  a real fault in the file is a 503 too.
- **What one clip holds in memory.** The clip is written a strip of rows
  at a time to a temporary file on local disk, then read back once as the
  response. At the cap that is the 64 MB of the response, GDAL's 32 MB
  cache and one 8 MB strip. Measured on three byte bands of noise at the
  cap: 106 MB above the process's baseline, in 1.5 s. The first version
  built the clip in GDAL's memory and peaked at about 234 MB for 48 MB of
  pixels.
- **What one statistics read holds.** The place's mask (a byte a pixel,
  at most the budget), one chunk of at most 16 MB, and GDAL's cache.
  Measured at the 4,000,000-pixel budget: 19 to 25 MB above baseline for
  one byte band or three, 58 MB for one `float64` band, 71 MB for four.
  Read a band at a time and whole, one band was 53 MB and 102 MB.
- **A reduced read in chunks can differ by a few pixels from one read
  whole** (three of four million, seen with an odd chunk size, from an
  overview). It is marked `approximate` either way.
- **A raster with no overview is thinned by the reader, not by GDAL.** GDAL
  unpacks a row of blocks again for every row it keeps when the row does
  not fit its 32 MB cache: 37 to 45 seconds for a reduced read that takes
  2 seconds when the reader takes full-size slices and keeps the same
  pixels itself. The catalog's rasters all have overviews, so this is for
  a plain GeoTIFF that arrives one day.
- **There is no limit on how many reads run at once.** Any signed-in user
  or API key can start several. Each is bounded as above.
- **`approximate` figures differ a little from exact ones.** The agent's
  tool tells the model, and the model is told to say so.
- **The two limits are not tied.** A place can have exact figures and a
  clip that is refused: four `float32` bands of 4,000,000 pixels are
  64 MB, right at the cap, and eight-byte values are over it. The agent's
  tool therefore says nothing about a download (gobase-agent docs/adr/011);
  the Ask panel offers none yet either.
- **The portal still writes nothing to the lake.** GDAL only reads it; the
  clip is written to a temporary folder on the backend's own disk, and
  removed before the response is sent.
- **A south-up raster can be a few pixels off.** One whose rows run from
  south to north counted 3,051 pixels in a triangle where an independent
  count gave 3,045. North-up and rotated rasters match exactly. The
  catalog holds no south-up raster.
- **`requirements.txt`'s note on `boto3` changed:** it is no longer loaded
  by `sts.py` alone.

## Revisit when

- The web map draws rasters: tiles then, not this.
- Clips need to be larger than the cap: the file is already on disk, so
  stream it from there and stop reading it back whole.
- Reads pile up: add a limit on how many run at once.
- A classified raster arrives with its legend somewhere other than the
  `classes` tag.
- Reads become slow enough to starve workers: move them off the request, or
  to a small service of their own.
