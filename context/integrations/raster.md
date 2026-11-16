# Rasters — COGs in the lake, read through rasterio

The catalog's rasters are COGs (Cloud-Optimized GeoTIFFs: rasters laid out so
a reader can fetch just the part it needs) in `s3://geobase-silver/raster/`,
written by the data platform. The portal reads a window of one to answer two
endpoints: `raster-stats` (figures over a place) and `clip.tif` (the pixels
over a place). It never writes one. Decided in docs/adr/029.

Read on 2026-11-10 against rasterio 1.5.1 (GDAL 3.12.4) and the local MinIO.

Desktop clients are a separate path: they read whole COGs themselves, with
credentials from `apps/map/sts.py` (docs/adr/022,
context/integrations/lake-sts.md).

## What talks to it

`backend/apps/map/raster.py`, and nothing else. It is the only module that
imports `rasterio`, and it imports it on first use: the wheel is large and
nothing at start-up needs it. `apps/map/raster_views.py` holds the two
endpoints; everything above the module speaks in figures and bytes.

`kb.raster_source(asset_id)` gives the lake URI and the asset's derived name
for an active raster. The URI never leaves the server.

## Configuration

No setting of its own for reaching the lake: it uses the `LAKE_S3_*`
settings DuckDB uses (context/integrations/lake.md).

| setting | becomes |
|---|---|
| `LAKE_S3_ENDPOINT` set | `AWS_S3_ENDPOINT`, plus the two below |
| `LAKE_S3_URL_STYLE=path` | `AWS_VIRTUAL_HOSTING=FALSE` (else `TRUE`) |
| `LAKE_S3_USE_SSL=false` | `AWS_HTTPS=NO` (else `YES`) |
| both keys set | a rasterio `AWSSession` with them, and `LAKE_S3_REGION` |
| no keys, but an endpoint or a region | an `AWSSession` on the ambient AWS credentials, as DuckDB's credential chain |
| nothing set | no session: a local path, which is what the tests read |

Three settings bound what is read:

| setting | default | what it is |
|---|---|---|
| `RASTER_STATS_MAX_PIXELS` | 4,000,000 | The most pixels read for `raster-stats`. Above it the place is read at reduced size and the answer says `approximate`. |
| `RASTER_CLIP_MAX_BYTES` | 67,108,864 (64 MB) | The largest `clip.tif`, as bytes of pixels before compression: width x height x bands x bytes per value. Above it the endpoint answers 400. |
| `RASTER_READ_TIMEOUT_SECONDS` | 300 (docs/adr/030) | The longest one read may take, from opening the raster to its last pixel. Checked between chunks of rows of a statistics read and between strips of a clip. A read that reaches it answers 503. Zero means no limit of this kind; GDAL still bounds each request. See "How long a read can take". |

Every read also sets these GDAL options:

| option | value | why |
|---|---|---|
| `GDAL_DISABLE_READDIR_ON_OPEN` | `EMPTY_DIR` | GDAL would otherwise list the object's folder on each open. |
| `GDAL_HTTP_CONNECTTIMEOUT` | 5 | Seconds to connect. |
| `GDAL_HTTP_LOW_SPEED_TIME` | 8 | A request that gets fewer bytes a second than the limit below, for this many seconds, is given up on. This is what ends a lake that connects and then stalls. |
| `GDAL_HTTP_LOW_SPEED_LIMIT` | 1024 | Bytes a second. |
| `GDAL_HTTP_TIMEOUT` | 120 (30 until docs/adr/030) | Seconds for any one request, however well it is going. |
| `GDAL_HTTP_MAX_RETRY` | 0 | GDAL waits 30 seconds before a retry. See "Nine things". |
| `GDAL_CACHEMAX` | 32 MB | GDAL's block cache. Its default is 5% of the machine's memory. |
| `CPL_VSIL_CURL_NON_CACHED` | `/vsis3/` | GDAL keeps nothing about a lake object after the file is closed. |
| `GDAL_TIFF_INTERNAL_MASK` | `YES` | A clip keeps a raster's mask inside the file, not in a side file. |

## Nine things that cost time to find

**A place wider than the raster cannot be moved corner by corner.** A
projected CRS is defined near its own area only. UTM zone 37N, which the
land-cover rasters use, cannot take a point past about 51°W or 129°E: PROJ
answers "Point outside of projection domain", or infinity. So a zoomed-out
map view over a land-cover raster was a 502, or a false "no pixels". The
place is now cut to the raster's footprint in lon/lat first
(`_footprints`, `_cut`), and only what is left is moved. Found in review on
2026-11-10; the first version was only tried with small places.

A raster that crosses the antimeridian (180°) has a footprint whose west
edge is at a larger longitude than its east edge. It is two boxes, one on
each side of the line, and the place is cut against both. Before that such
a raster had no footprint, and a world-wide box over one answered 208 of
its 60,000 pixels and called the figure exact.

**One retry costs 85 seconds on a lake that drops packets.** GDAL waits 30
seconds before a retry (`GDAL_HTTP_RETRY_DELAY`), and makes several
connection attempts per read. Measured against an address that answers
nothing (`10.255.255.1:9000`): 85 seconds with one retry, 15 seconds with
none. A refused port or a host that does not resolve fails in under a
second either way.

**A lake that connects and then says nothing cost 90 seconds.** GDAL makes
up to three requests to open one raster: two for its header, and one that
asks whether the path is a folder. No option turns the extra two off. Each
waited the whole `GDAL_HTTP_TIMEOUT`, so three times 30 seconds. The fix is
the low-speed rule above, which gives a silent request up after 8 seconds.
And a lake that sends a response's headers and then stalls is not reported
as a timeout at all: GDAL keeps the few bytes it got and says "Cannot read
TIFF header". Its own timeout message shows only in GDAL's debug log. So
the reader times each step itself: a step that failed after waiting as long
as a stalled request does was stalled, and is a 503, not a 502 (`_Clock`,
`_classify`).

**A band is not one request, and bands stored together are fetched once
for each band read.** The first reader read a place one band at a time and
looked at the clock between bands. A long, thin place over the satellite
image (205 x 17,100 pixels, under the budget) was sixty requests a band,
each one well inside GDAL's limits, and its blocks hold all three bands
together, so each block was fetched three times: 166 MB in all, since the
32 MB cache could not hold them between bands. Through a link throttled to
400 KB/s that read ran 114 seconds against a 60-second limit, and 303
seconds at 150 KB/s. A block is also fetched whole however little of it the
place covers, so what a read pulls depends on the blocks it touches, not on
its own pixels. The reader now goes a chunk of rows at a time, every band
of the chunk in one read, and looks at the clock between chunks (`_stats`,
`_chunk_rows`). The same place pulls 39 MB; the two runs became 52 seconds
(an answer) and 60 to 69 seconds (a 503). Found in review on 2026-11-10.

**GDAL unpacks a row of blocks again for every row it keeps, when the row
does not fit its cache.** Asked for a window at reduced size from a raster
with no overview, GDAL reads the full-size blocks and keeps one pixel in so
many, one row of the reduced grid at a time. Each such row needs every
block it crosses. With the cache held to 32 MB, a row of blocks wider than
that (four `float64` bands in 512-pixel blocks across 2,000 pixels are
33 MB) is unpacked again for every kept row: a reduced read of a 4,000,000
pixel raster took 37 to 45 seconds from local disk, where the same raster
at full size took 2. Over a lake each of those is a fetch. So for a raster
with no overview coarse enough, the reader reads full-size slices of rows
itself and keeps the pixels GDAL would have kept (`_thinned`): 2 seconds.
A raster with overviews, which every COG in the catalog has, is still
read by GDAL from the overview.

**rasterio logs the object's URL by itself.** Its GDAL error handler logs on
`rasterio._env` at WARNING: `CPLE_AppDefined in HTTP response code on
http://<endpoint>/<bucket>/<key>: 403`. With no logging configured that
line reaches the root logger. `raster.py` switches the `rasterio` loggers
off when it first imports rasterio (`_silence`): a level no record
reaches, and no passing on to the root. No key or secret was ever in such
a line, only the path.

**rasterio refuses keys as plain options.** `rasterio.Env(AWS_ACCESS_KEY_ID=…)`
raises. Keys go in through `rasterio.session.AWSSession`, which loads
`boto3`. The endpoint, path style and scheme are plain options and go in
beside it. `Env` is scoped to its `with` block and its thread, so nothing
reaches the process's environment.

**An inherited `PROJ_DATA` breaks every CRS lookup.** Conda exports
`PROJ_DATA`, `PROJ_LIB`, `GDAL_DATA` and `GDAL_DRIVER_PATH` shell-wide. They
point at another PROJ, and the wheel's own PROJ then fails with "proj.db
contains DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 6 is
expected". On this laptop every place failed that way until `raster.py`
dropped the four variables before importing rasterio, as the data platform
does (`gobase_orchestration/lib/transforms.py`). The Docker image has none of
them.

**A place's edge on a pixel edge lands a hair to one side.** 35.3 degrees on
a 0.01-degree grid is column 29.999…, not 30. Rounding the window outwards
then took in a whole extra column. `_span` allows a millionth of a pixel.
A place with no size (a point: a bbox whose corners are equal) that sits
exactly on a pixel edge then covered no pixel at all, and was "no pixels"
though it lay on the raster. It now covers the pixel that starts there.

## Reading

`raster.read_stats(uri, max_pixels=, bbox=, area=, max_seconds=)`:

1. The place becomes a ring of lon/lat points: the bbox's rectangle, or the
   area's polygon. The ring is cut to the raster's footprint in lon/lat
   (two boxes, and so up to two pieces, for a raster across the
   antimeridian). Each edge is then cut into 16 pieces, and the ring is
   moved into the raster's CRS. With no place, the whole raster is the
   window.
2. The window is the ring's box in pixels, rounded outwards and cut to the
   raster. No overlap is `pixels: 0`, not a failure. A place with no size
   covers the one pixel it is in.
3. A window above `max_pixels` is read at reduced size, with
   nearest-neighbour resampling. GDAL takes that from a COG's overview
   (`out_shape`). A raster with no overview coarse enough is read at full
   size, a slice of rows at a time, and the reader keeps the pixel under
   the centre of each cell of the reduced grid, which is the pixel GDAL
   keeps (`_thinned`). The reduced size is never above the budget
   (`_reduced`).
4. The ring is burned onto the grid that was read: a pixel is inside when
   its centre is. If no centre is inside, the pixels it touches are.
5. The window is read a chunk of rows at a time, every band of the chunk
   in one read, masked by nodata, the raster's mask or its alpha band. NaN
   and infinity are dropped too. The figures are added up as it goes: min,
   max, mean, and the share of the place that holds data, each to nine
   significant digits. An alpha band is not reported as a band. A chunk is
   whole rows of the raster's blocks, about 4 MB of blocks before
   compression and never more than 16 MB of pixels held, and it ends where
   a row of blocks ends, so no block is fetched for two chunks. The sum of
   a band of whole numbers is kept as a whole number, so the mean does not
   depend on the chunks. A reduced read goes the same way. From an overview,
   each chunk asks for its share of the window at its share of the reduced
   size, which is the same reduced grid, and a chunk is sized by the
   overview's blocks. With no overview a chunk is the few rows of the
   reduced grid that one row of full-size blocks stands for, and the clock
   is looked at before each full-size slice.
6. One whole-number band with a `classes` tag (JSON text,
   `{"7": "built_area"}`) is a classified raster: each value's count and
   share of the valid pixels, largest first, at most 256. The rest are
   summed in `other_classes`.

`raster.clip(uri, bbox=, max_bytes=, max_seconds=)` checks the window's size
first (width x height x bands x bytes per value), then moves it a strip of
rows at a time into a tiled, DEFLATE GeoTIFF in a temporary folder on local
disk, in the raster's own CRS and grid, and hands back the file's bytes. It
copies the colour table, band descriptions, scales, offsets, units, a mask
stored with the raster, and the tags on a list (`_DATASET_TAGS`: what the
data platform writes, `AREA_OR_POINT`, the descriptive TIFF fields).
`NoOverlap` and `ClipTooLarge` become 400s in the view.

A tag on the list is still checked by its value, three ways:

- **The legend (`classes`)** is written again from its entries, not passed
  on as the text it came in (`_carried_legend`). An entry is kept when its
  key is a whole number and its name is text without the shape of a path.
  Anything else in the tag is left out: a key that is no class, a nested
  value, a path as a name. A legend with no entry left is not carried.
- **A sentence** (`description`, `TIFFTAG_IMAGEDESCRIPTION`,
  `TIFFTAG_COPYRIGHT`, and a band's description) may hold a slash ("Land
  Use/Land Cover"), so it is left out only when it has the shape of a
  path: any backslash or `://`, or a word with a slash that also has two
  slashes or more, a leading `/`, `.` or `~`, a `:` or `=`, or a file
  extension at its end. A slash standing alone between two words ("Bare /
  sparse vegetation") names nothing.
- **Every other tag** (`source`, `collection`, `year`, …) is a short value
  and is left out if it holds a slash or a backslash at all. Read on
  2026-11-10, no tag of the catalog's rasters holds one (`source` is
  "Microsoft Planetary Computer STAC").

`raster.clip_size(uri, bbox=, max_bytes=)` does the first step only: it
reads the raster's header, works out the window, and raises `NoOverlap` or
`ClipTooLarge` as `clip` would. A HEAD request uses it, so it builds no
clip.

## How long a read can take

GDAL bounds each request it makes. The reader bounds the read as a whole,
between steps: a step is the open, one chunk of rows of a statistics read,
or one strip of a clip, and nothing can stop GDAL inside one.

Measured on 2026-11-10 against a local socket that misbehaves on purpose,
for `raster-stats` and for `clip.tif` alike:

| The lake | Before | Now | Answer |
|---|---|---|---|
| drops every packet (`10.255.255.1:9000`) | 15 s | 15 s (three connects of 5 s) | 503 |
| connects, then says nothing | 90 s | 24 s (three requests of 8 s) | 503 |
| sends headers, then stalls | 30 s, a 502 | 8 s | 503 |
| drips one byte a second | 30 s, a 502 | 8 s | 503 |
| refuses the port, or does not resolve | under 1 s | under 1 s | 503 |

A lake that is slow but alive is bounded by `RASTER_READ_TIMEOUT_SECONDS`:
a read still going after 300 seconds (60 until docs/adr/030) stops before its next chunk or strip
and answers 503. It can run over by the step it is in. A step pulls a few
megabytes: a chunk of a statistics read is 1 to 3 MB on the catalog's
rasters, a strip of a clip up to 8 MB. At 150 KB/s that is up to 19
seconds over; at 6 Mbit/s, 4 seconds.

Measured on 2026-11-10 through a proxy that throttles the local MinIO, with
the 60-second limit, on the satellite image:

| Read | Link | Before | Now |
|---|---|---|---|
| a long, thin place (205 x 17,100 pixels) | 400 KB/s | 503 after 114 s | 200 in 52 s |
| the same | 150 KB/s | 503 after 303 s | 503 after 60 to 69 s (two runs) |
| a place at the budget (1,990 x 1,990) | 400 KB/s | not measured | 200 in 30 s |
| the same | 150 KB/s | not measured | 503 after 61 s |
| the whole raster, from an overview | 150 KB/s | not measured | ends at 67 s: a 503 in one run, an answer in another |
| `clip.tif` at the cap | 270 KB/s | not changed | 503 after 73 s |

"Before" looked at the clock once a band. The proxy throttles each
connection and GDAL opens two, so the link is about twice the figure.

What the limits ask of the link between the portal and the lake, from the
catalog's rasters (bytes pulled, counted by that proxy):

| Read | Pulls | In requests of about |
|---|---|---|
| `clip.tif` at the cap (satellite image, 60 MB of pixels) | 45 to 70 MB, by the window | up to 8 MB |
| `raster-stats`, a long, thin three-band place under the budget | 39 MB (166 MB before) | 1.2 MB |
| `raster-stats`, a three-band place at the budget | 12 MB | 2.5 MB |
| `raster-stats`, a whole three-band raster (from an overview) | 10 MB | 3 MB |
| anything on a land-cover raster | about 1 MB or less | 0.3 MB |

So a clip at the cap needs 1.2 to 1.9 Mbit/s to finish in 300 seconds, and the
largest single request needs about 2 Mbit/s to finish in 30. On a slower
link the largest reads answer 503 and smaller ones still work; raise
`RASTER_READ_TIMEOUT_SECONDS` there. A raster with more or wider bands
pulls more: these figures are for bands of bytes. A place pulls the blocks
it touches, whole, so a long, thin place pulls far more than its pixels.

**The agent stops waiting before the portal does.** `gobase-agent`, the one
caller of `raster-stats`, gives a call 15 seconds (`BACKEND_TIMEOUT_SECONDS`
there). A read that takes longer goes on here until it ends or reaches a
bound above: the worker stays held, and the agent has already told the
model "the portal is unavailable". A second question then starts a second
read beside the first. Nothing here stops a read when its caller has left.

## What a read holds in memory

Measured on 2026-11-10, peak memory above the process's baseline:

| read | holds |
|---|---|
| `clip.tif` at the cap, three byte bands of noise | 106 MB: the 64 MB response, GDAL's 32 MB cache, one 8 MB strip |
| `raster-stats` at the budget, one byte band, or three | 19 to 25 MB (53 MB before the read went in chunks) |
| `raster-stats` at the budget, one `float64` band | 58 MB (102 MB before) |
| `raster-stats` at the budget, four `float64` bands | 71 MB |

A statistics read holds the place's mask (one byte a pixel), one chunk of
at most 16 MB, and GDAL's cache.

Nothing limits how many reads run at once.

## Failures

- `RasterUnavailable` → **503**. The lake could not be reached, refused
  the credentials, stalled, or the read ran past
  `RASTER_READ_TIMEOUT_SECONDS`.
- `RasterReadError` → **502**. The lake answered and the object is missing
  or is not a readable raster.
- `RasterNotPlaceable` → **422**, with its own message ("This raster cannot
  be measured or clipped over a place: its extent has no longitude and
  latitude box. Without a place, the whole raster is measured."). The
  raster has no CRS, or its extent has no lon/lat box (see "Known limits").
  Not a 502: the lake and the file are fine, and the body used to say "The
  data lake returned an error". Not a 400: the caller's place is good.
- `ClipNotWritten` → **503**, with its own message ("The portal could not
  write the clip. Try again later."). The clip could not be written to the
  temporary folder on this server: a full disk, usually. Not a 502: the
  lake and the raster are fine. Not a 500: the request is good, and other
  clips finishing clears it. Logged as an error, by exception type.

Only a failed read is one of the first two: rasterio's errors, GDAL's, and the
S3 session's (`_read_failures`). Any other exception is a bug in the reader
and answers 500.

GDAL reports both as one error type, so `_UNAVAILABLE_MARKERS` in
`raster.py` holds the substrings that mean "unreachable", as `lake.py` does
for DuckDB. Checked against the local MinIO on 2026-11-10: a dead port
("Could not connect to server"), a host that does not resolve, a wrong
secret (`SignatureDoesNotMatch`) and an unknown key id are 503; a key the
bucket does not hold is 502. The list is a heuristic and will need extending
when GDAL rewords something.

A lake that answers with an error of its own is 503 too. GDAL passes on the
lake's sentence, not its error code, so the list holds the sentences.
Checked on 2026-11-10 against a local socket answering each one: 503
`ServiceUnavailable` ("Service is unable to handle request"), 503
`SlowDown` ("Please reduce your request rate"), 500 `InternalError` ("We
encountered an internal error"), a 502, 504 or 429 from a proxy in front of
the lake ("Invalid AWS response"), 400 `ExpiredToken` ("The provided token
has expired") and 400 `RequestTimeTooSkewed` ("The difference between the
request time and…"). They were 502 "could not be read", which reads as
permanent. A lake that words one of these another way is still a 502.

One failure the message cannot tell: a lake that stalls after its headers
(see "Nine things"). The step's own wait decides it. The cost is that a
slow step that then fails for a real reason in the file, after eight
seconds or more, is also a 503.

The message is never logged or passed on, only the exception's type: a GDAL
message quotes the object's path. rasterio's own loggers are switched off
for the same reason (see "Nine things").

## Known limits

- **A south-up raster can be a few pixels off.** One whose rows run south
  to north counted 3,051 pixels in a triangle where an independent count
  gave 3,045. North-up and rotated rasters match exactly. The catalog
  holds none.
- **In the main thread, `rasterio.Env` sets GDAL options for the whole
  process** while its block runs; in a worker thread they are that
  thread's. `os.environ` never holds them. Requests run in worker threads.
- **The clip's mask is a per-dataset mask.** A raster with one mask per
  band gets the dataset's.
- **A raster whose extent has no lon/lat box takes no place.** The whole
  world in Mollweide or Robinson: the corners of its rectangle lie outside
  the projected globe. `raster-stats` with a place, and `clip.tif`, answer
  422 for it, and say why. Before, they answered a count about 1% wrong.
  Without a place `raster-stats` still reads it. The catalog holds none.
- **The same for a raster stored with longitudes from 0 to 360,** as
  climate grids often are. Its western half lies past 180°, where a place
  given in -180..180 would miss it: a place there answered "no pixels".
  It is a 422 for any place now. Handling it means moving the place by
  360°, which is not built.
- **A world-wide lon/lat grid may reach past 180° by less than a pixel.**
  One whose pixels are centred on the round degrees runs from -180.5 to
  180.5, and one can be a rounding error wider than the world. Its box is
  cut back to ±180 and it takes a place like any other. A pixel or more
  past the line is the 0-to-360 case above.
- **A reduced read in chunks can differ by a few pixels from one read
  whole.** Each chunk asks for its share of the window, and where a
  sampled pixel falls exactly between two source pixels the rounding can
  go the other way: three pixels of four million on the satellite image,
  with an odd chunk size. The answer is marked `approximate` either way.
  With the chunk sizes the reader picks, 89 test places gave the same
  figures chunked and whole.
- **`If-None-Match` is compared weakly on `clip.tif` only.** `"x"` and
  `W/"x"` are the same copy there. The features page and the PDF still
  want the ETag exactly as it was sent, which is what browsers send.
- **Long edges are cut into 16 pieces only.** A place with an edge that
  spans much of the world, over a raster in a polar or world-wide
  projection, can be off by a fraction of a percent of its pixels (104 of
  65,536 on a world-wide Web Mercator raster). Places near the size of the
  raster match exactly.
- **A killed process leaves its clip behind.** The temporary folder
  (`/tmp/clip-…`, at most about the cap each) is removed on every return
  and every exception. A process killed outright between the write and the
  read (SIGKILL, power loss) cannot remove it, and nothing sweeps it.
- **A HEAD on `clip.tif` has no usable length.** It builds no clip, so
  `Content-Length` is 0, written by Django for the empty body.

## Checking it locally

```bash
cd backend && .venv/bin/python manage.py shell -c "
from apps.catalog import kb
from apps.map import raster
uri = kb.raster_source('<a raster asset_id>')['source_uri']
print(raster.read_stats(uri, max_pixels=4_000_000, bbox=(35.80, 34.40, 35.87, 34.46)))"
```

MinIO must be running (`docker start minio`).
