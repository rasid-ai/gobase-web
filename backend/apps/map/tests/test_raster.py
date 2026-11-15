"""The raster reader: figures over a place, and a clip of it (docs/adr/029).

Read for real, from GeoTIFFs written into a temporary directory. What the
endpoints do around the reader is in `test_raster_api.py`.
"""

import json
import logging
import os
import socket
import threading
import time

import numpy
import pytest

from apps.map import raster

from .rasters import (
    mercator_box_in_degrees,
    write_across_180,
    write_classified,
    write_floats,
    write_imagery,
    write_many_classes,
    write_masked,
    write_tall,
    write_tiny_floats,
    write_utm,
    write_whole_world_mollweide,
    write_with_alpha,
)

BUDGET = 1_000_000


@pytest.fixture(autouse=True)
def no_object_store(settings):
    """A local path needs no store: whatever the developer's .env holds is blanked."""
    settings.LAKE_S3_ENDPOINT = ""
    settings.LAKE_S3_REGION = ""
    settings.LAKE_S3_ACCESS_KEY = ""
    settings.LAKE_S3_SECRET_KEY = ""


@pytest.fixture
def classified(tmp_path):
    return write_classified(tmp_path / "landcover.tif")


@pytest.fixture
def imagery(tmp_path):
    return write_imagery(tmp_path / "city.tif")


def opened(data: bytes):
    """A clip's bytes as an open dataset."""
    from rasterio.io import MemoryFile

    return MemoryFile(data).open()


# --- figures -----------------------------------------------------------------


def test_the_whole_raster_is_counted_without_a_place(classified):
    stats = raster.read_stats(classified, max_pixels=BUDGET)

    assert stats["pixels"] == 10_000
    assert stats["approximate"] is False
    assert stats["bands"] == [{"index": 1, "min": 1, "max": 7, "mean": 4.0, "valid_percent": 90.0}]
    # Shares are of the pixels that hold data: the nodata rows are in neither.
    assert stats["classes"] == [
        {"value": 1, "name": "water", "pixels": 4500, "share": 0.5},
        {"value": 7, "name": "built_area", "pixels": 4500, "share": 0.5},
    ]


def test_a_bbox_counts_only_the_pixels_inside_it(classified):
    """Columns 0-24 of the bottom half: every pixel there is class 7."""
    stats = raster.read_stats(classified, max_pixels=BUDGET, bbox=(35.0, 33.0, 35.25, 33.5))

    assert stats["pixels"] == 25 * 50
    assert stats["bands"][0]["valid_percent"] == 100.0
    assert stats["classes"] == [{"value": 7, "name": "built_area", "pixels": 1250, "share": 1.0}]


def test_an_area_counts_its_shape_not_its_box(classified):
    """A triangle holds about half the pixels of its envelope."""
    box = (35.0, 33.0, 35.5, 33.5)
    triangle = "POLYGON((35.0 33.0, 35.5 33.0, 35.0 33.5, 35.0 33.0))"

    boxed = raster.read_stats(classified, max_pixels=BUDGET, bbox=box)
    shaped = raster.read_stats(classified, max_pixels=BUDGET, bbox=box, area=triangle)

    assert boxed["pixels"] == 2500
    assert 1200 <= shaped["pixels"] <= 1300


def test_nodata_pixels_are_in_the_place_but_not_in_the_figures(classified):
    """The top ten rows hold no data: half of this box."""
    stats = raster.read_stats(classified, max_pixels=BUDGET, bbox=(35.0, 33.8, 35.2, 34.0))

    assert stats["pixels"] == 400
    assert stats["bands"][0]["valid_percent"] == 50.0
    assert stats["classes"] == [{"value": 7, "name": "built_area", "pixels": 200, "share": 1.0}]


def test_a_place_with_no_data_at_all_has_null_figures(classified):
    stats = raster.read_stats(classified, max_pixels=BUDGET, bbox=(35.0, 33.95, 35.2, 34.0))

    assert stats["pixels"] == 100
    assert stats["bands"] == [
        {"index": 1, "min": None, "max": None, "mean": None, "valid_percent": 0.0}
    ]
    assert stats["classes"] == []


def test_a_place_above_the_budget_is_read_smaller_and_says_so(classified):
    stats = raster.read_stats(classified, max_pixels=100)

    assert stats["approximate"] is True
    assert 0 < stats["pixels"] <= 100
    # Nearest-neighbour: a class stays a class, never a blend of two.
    assert {row["value"] for row in stats["classes"]} == {1, 7}
    assert sum(row["share"] for row in stats["classes"]) == pytest.approx(1.0)
    assert stats["classes"][0]["share"] == pytest.approx(0.5, abs=0.1)


def test_a_place_at_the_budget_is_exact(classified):
    stats = raster.read_stats(classified, max_pixels=10_000)

    assert stats["approximate"] is False
    assert stats["pixels"] == 10_000


def test_a_place_that_misses_the_raster_is_empty_not_an_error(classified, imagery):
    paris = (2.2, 48.8, 2.4, 48.9)

    assert raster.read_stats(classified, max_pixels=BUDGET, bbox=paris) == {
        "pixels": 0,
        "approximate": False,
        "bands": [],
        "classes": [],
        "other_classes": None,
    }
    # A raster with no legend has no classes to be empty.
    assert raster.read_stats(imagery, max_pixels=BUDGET, bbox=paris)["classes"] is None


def test_a_place_partly_outside_is_cut_to_the_raster(classified):
    """The box reaches a degree west of the raster: only its 10 columns inside count."""
    stats = raster.read_stats(classified, max_pixels=BUDGET, bbox=(34.0, 33.0, 35.1, 33.1))

    assert stats["pixels"] == 100


def test_a_place_smaller_than_a_pixel_counts_the_pixel_it_touches(classified):
    """No pixel centre is inside this box, so the centre rule alone would count none."""
    stats = raster.read_stats(classified, max_pixels=BUDGET, bbox=(35.101, 33.101, 35.102, 33.102))

    assert stats["pixels"] == 1
    assert stats["classes"] == [{"value": 7, "name": "built_area", "pixels": 1, "share": 1.0}]


def test_a_place_is_moved_into_the_rasters_own_crs(imagery):
    """Ten by ten pixels of a Web Mercator raster, asked for in degrees."""
    bbox = mercator_box_in_degrees(3_901_000, 3_998_000, 3_902_000, 3_999_000)

    stats = raster.read_stats(imagery, max_pixels=BUDGET, bbox=bbox)

    assert stats["pixels"] == 100
    assert stats["classes"] is None
    assert [(band["index"], band["min"], band["max"], band["mean"]) for band in stats["bands"]] == [
        (1, 10, 10, 10.0),
        (2, 20, 20, 20.0),
        (3, 30, 30, 30.0),
    ]


def test_nan_is_not_data(tmp_path):
    """One column in ten is NaN; the rest hold their row number, 0 to 9."""
    stats = raster.read_stats(write_floats(tmp_path / "f.tif"), max_pixels=BUDGET)

    assert stats["pixels"] == 100
    assert stats["bands"] == [
        {"index": 1, "min": 0.0, "max": 9.0, "mean": 4.5, "valid_percent": 90.0}
    ]
    assert stats["classes"] is None


def test_a_legend_on_a_float_raster_does_not_make_it_classified(tmp_path):
    path = write_floats(tmp_path / "f.tif", legend='{"1": "water"}')

    assert raster.read_stats(path, max_pixels=BUDGET)["classes"] is None


def test_a_value_the_legend_does_not_name_is_reported_with_no_name(tmp_path):
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    path = str(tmp_path / "odd.tif")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=1,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(35.0, 34.0, 0.5, 0.5),
    ) as target:
        target.write(numpy.array([[1, 9]], dtype="uint8"), 1)
        target.update_tags(classes='{"1": "water"}')

    assert raster.read_stats(path, max_pixels=BUDGET)["classes"] == [
        {"value": 1, "name": "water", "pixels": 1, "share": 0.5},
        {"value": 9, "name": None, "pixels": 1, "share": 0.5},
    ]


@pytest.mark.parametrize("legend", ["not json", "[1, 2]", "{}"])
def test_a_legend_that_is_not_one_is_no_classes(tmp_path, legend):
    rasterio = raster._rasterio()

    path = write_classified(tmp_path / "landcover.tif")
    with rasterio.open(path, "r+") as target:
        target.update_tags(classes=legend)

    assert raster.read_stats(path, max_pixels=BUDGET)["classes"] is None


# --- the clip ----------------------------------------------------------------


def test_a_clip_is_the_window_over_the_box_on_the_rasters_own_grid(classified):
    """Columns 20-59, rows 60-79: both classes, in the source's CRS and pixel size."""
    data = raster.clip(classified, bbox=(35.2, 33.2, 35.6, 33.4), max_bytes=BUDGET)

    with opened(data) as clipped:
        assert (clipped.width, clipped.height, clipped.count) == (40, 20, 1)
        assert clipped.crs.to_epsg() == 4326
        assert clipped.nodata == 0
        assert clipped.dtypes == ("uint8",)
        assert tuple(round(n, 6) for n in clipped.bounds) == (35.2, 33.2, 35.6, 33.4)
        assert clipped.res == pytest.approx((0.01, 0.01))
        pixels = clipped.read(1)
        assert (pixels[:, :30] == 7).all()
        assert (pixels[:, 30:] == 1).all()


def test_a_clip_keeps_the_legend_the_palette_and_the_band_name(classified):
    data = raster.clip(classified, bbox=(35.2, 33.2, 35.6, 33.4), max_bytes=BUDGET)

    with opened(data) as clipped:
        tags = clipped.tags()
        assert tags["classes"] == '{"1": "water", "7": "built_area"}'
        assert tags["year"] == "2023"
        assert clipped.colormap(1)[7] == (255, 0, 0, 255)
        assert clipped.descriptions == ("land cover class",)


def test_a_clip_leaves_out_a_tag_that_holds_a_path(classified):
    data = raster.clip(classified, bbox=(35.2, 33.2, 35.6, 33.4), max_bytes=BUDGET)

    with opened(data) as clipped:
        assert "origin" not in clipped.tags()
    assert b"secret-bucket" not in data


def test_a_clip_is_tiled_and_compressed(classified):
    data = raster.clip(classified, bbox=(35.2, 33.2, 35.6, 33.4), max_bytes=BUDGET)

    with opened(data) as clipped:
        assert clipped.profile["compress"] == "deflate"
        assert clipped.profile["tiled"] is True


def test_a_clip_of_a_projected_raster_is_not_resampled(imagery):
    """The box is in degrees; the clip stays in Web Mercator on the 100 m grid."""
    bbox = mercator_box_in_degrees(3_901_000, 3_998_000, 3_902_000, 3_999_000)

    data = raster.clip(imagery, bbox=bbox, max_bytes=BUDGET)

    with opened(data) as clipped:
        assert clipped.crs.to_epsg() == 3857
        assert clipped.count == 3
        assert clipped.res == (100.0, 100.0)
        # Rounded outwards: the box's own pixels, and at most one more each side.
        assert 10 <= clipped.width <= 12
        assert 10 <= clipped.height <= 12
        assert clipped.bounds.left % 100 == 0
        assert clipped.bounds.top % 100 == 0
        assert (clipped.read(2) == 20).all()


def test_a_clip_above_the_cap_is_refused_with_both_numbers(classified):
    with pytest.raises(raster.ClipTooLarge) as refused:
        raster.clip(classified, bbox=(35.0, 33.0, 36.0, 34.0), max_bytes=9_999)

    assert (refused.value.pixels, refused.value.allowed) == (10_000, 9_999)


def test_a_clip_at_the_cap_is_served(classified):
    data = raster.clip(classified, bbox=(35.0, 33.0, 36.0, 34.0), max_bytes=10_000)

    with opened(data) as clipped:
        assert (clipped.width, clipped.height) == (100, 100)


def test_a_clip_that_misses_the_raster_is_refused(classified):
    with pytest.raises(raster.NoOverlap):
        raster.clip(classified, bbox=(2.2, 48.8, 2.4, 48.9), max_bytes=BUDGET)


# --- failures ----------------------------------------------------------------


def test_a_missing_file_is_a_read_error_that_names_no_path(tmp_path, caplog):
    missing = str(tmp_path / "secret-bucket-path.tif")

    with caplog.at_level(logging.WARNING), pytest.raises(raster.RasterReadError) as failed:
        raster.read_stats(missing, max_pixels=BUDGET)

    assert "secret-bucket-path" not in str(failed.value)
    assert "secret-bucket-path" not in caplog.text


def test_a_file_that_is_not_a_raster_is_a_read_error(tmp_path):
    path = tmp_path / "notes.tif"
    path.write_text("not a raster")

    with pytest.raises(raster.RasterReadError):
        raster.clip(str(path), bbox=(35.0, 33.0, 36.0, 34.0), max_bytes=BUDGET)


def test_a_raster_with_no_crs_cannot_take_a_place(tmp_path):
    path = write_floats(tmp_path / "bare.tif", crs=None)

    with pytest.raises(raster.RasterNotPlaceable):
        raster.read_stats(path, max_pixels=BUDGET, bbox=(35.0, 33.0, 36.0, 34.0))
    # The whole raster needs no place, so it still reads.
    assert raster.read_stats(path, max_pixels=BUDGET)["pixels"] == 100


@pytest.mark.parametrize(
    "message",
    [
        "CURL error: Failed to connect to 127.0.0.1 port 9: Could not connect to server",
        "CURL error: Could not resolve host: lake.invalid",
        "HTTP response code: 403",
        "SignatureDoesNotMatch: The request signature we calculated does not match",
        "The Access Key Id you provided does not exist in our records.",
        "Operation timed out after 30000 milliseconds",
        # What GDAL passes on when the lake itself answers 5xx, throttles, or
        # refuses credentials that ran out: the lake's sentence, not its code.
        "Service is unable to handle request",
        "Please reduce your request rate",
        "We encountered an internal error",
        "Invalid AWS response: <html>bad gateway</html>",
        "Invalid AWS response: <html>gateway time-out</html>",
        "Invalid AWS response: slow down",
        "The provided token has expired.",
        "The difference between the request time and the server time is too large",
    ],
)
def test_a_lake_that_cannot_be_reached_is_unavailable(message):
    failure = raster._classify(OSError(f"/vsis3/secret-bucket/x.tif: {message}"))

    assert isinstance(failure, raster.RasterUnavailable)
    # The type only: the message quotes the object's path.
    assert str(failure) == "OSError"


def test_any_other_failure_is_a_read_error():
    failure = raster._classify(OSError("'/vsis3/secret-bucket/x.tif' not recognized as a format"))

    assert isinstance(failure, raster.RasterReadError)
    assert str(failure) == "OSError"


# --- reaching the lake -------------------------------------------------------


def test_a_custom_endpoint_is_reached_path_style_over_plain_http(settings):
    settings.LAKE_S3_ENDPOINT = "127.0.0.1:9000"
    settings.LAKE_S3_URL_STYLE = "path"
    settings.LAKE_S3_USE_SSL = False

    options = raster._options()

    assert options["AWS_S3_ENDPOINT"] == "127.0.0.1:9000"
    assert options["AWS_VIRTUAL_HOSTING"] == "FALSE"
    assert options["AWS_HTTPS"] == "NO"


def test_aws_itself_needs_no_endpoint_options():
    options = raster._options()

    assert not any(name.startswith("AWS_") for name in options)


def test_a_dead_lake_is_given_up_on_without_a_retry():
    """GDAL waits 30 seconds before a retry: one retry made a lake that drops
    packets hold a worker for 85 seconds."""
    options = raster._options()

    assert options["GDAL_HTTP_CONNECTTIMEOUT"] == "5"
    assert options["GDAL_HTTP_TIMEOUT"] == "30"
    assert options["GDAL_HTTP_MAX_RETRY"] == "0"


def test_a_lake_that_connects_and_says_nothing_is_given_up_on():
    """Without these a silent lake cost three whole requests: 90 seconds."""
    options = raster._options()

    assert options["GDAL_HTTP_LOW_SPEED_TIME"] == "8"
    assert options["GDAL_HTTP_LOW_SPEED_LIMIT"] == "1024"
    # GDAL makes up to three requests to open one raster, each bounded alone.
    assert 3 * raster._CONNECT_SECONDS <= 30
    assert 3 * raster._STALL_SECONDS <= 30


class StalledLake:
    """A local socket that takes a connection and then stalls, as a sick lake does.

    `silent` never answers. `headers` answers a response's headers and four
    bytes of its body, and then nothing.
    """

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.requests = 0
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(16)
        self.open: list[socket.socket] = []
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def endpoint(self) -> str:
        return f"127.0.0.1:{self.server.getsockname()[1]}"

    def _accept(self) -> None:
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            self.open.append(connection)
            threading.Thread(target=self._hold, args=(connection,), daemon=True).start()

    def _hold(self, connection: socket.socket) -> None:
        try:
            connection.recv(65536)
            self.requests += 1
            if self.mode == "headers":
                connection.sendall(
                    b"HTTP/1.1 206 Partial Content\r\nContent-Length: 16384\r\n"
                    b"Content-Range: bytes 0-16383/5000000\r\n\r\nII*\x00"
                )
        except OSError:
            pass

    def close(self) -> None:
        self.server.close()
        for connection in self.open:
            connection.close()


@pytest.fixture
def stalled_lake(settings, monkeypatch):
    """Point the reader at a stalled lake, with one second where it waits eight."""
    monkeypatch.setattr(raster, "_STALL_SECONDS", 1)
    settings.LAKE_S3_URL_STYLE = "path"
    settings.LAKE_S3_USE_SSL = False
    settings.LAKE_S3_ACCESS_KEY = "key-id-placeholder"
    settings.LAKE_S3_SECRET_KEY = "secret-placeholder"
    lakes = []

    def start(mode: str) -> StalledLake:
        lake = StalledLake(mode)
        lakes.append(lake)
        settings.LAKE_S3_ENDPOINT = lake.endpoint
        return lake

    yield start
    for lake in lakes:
        lake.close()


def test_a_lake_that_connects_and_then_stalls_is_given_up_on_in_bounded_time(stalled_lake):
    """Three requests, each given up after the stall time: not three whole
    request timeouts, which was 90 seconds."""
    lake = stalled_lake("silent")
    began = time.monotonic()

    with pytest.raises(raster.RasterUnavailable):
        raster.read_stats("s3://secret-bucket/raster/landcover.tif", max_pixels=BUDGET)

    # Three one-second waits here; the bound is generous for a busy machine.
    assert time.monotonic() - began < 15
    assert lake.requests <= 3


def test_a_lake_that_stalls_after_its_headers_is_unavailable_not_a_bad_raster(stalled_lake):
    """GDAL keeps the few bytes it got and calls the file unreadable. The wait
    says otherwise: a bad file fails at once."""
    stalled_lake("headers")
    began = time.monotonic()

    with pytest.raises(raster.RasterUnavailable):
        raster.clip(
            "s3://secret-bucket/raster/landcover.tif", bbox=(35.0, 33.0, 35.1, 33.1), max_bytes=1
        )

    assert time.monotonic() - began < 15


def test_a_failure_after_a_stalled_wait_is_the_lakes_not_the_files(monkeypatch):
    clock = raster._Clock(60)
    unreadable = OSError("/vsis3/secret-bucket/x.tif: Cannot read TIFF header")

    assert isinstance(raster._classify(unreadable, clock), raster.RasterReadError)

    monkeypatch.setattr(clock, "step_started", clock.step_started - raster._STALL_SECONDS)
    failure = raster._classify(unreadable, clock)
    assert isinstance(failure, raster.RasterUnavailable)
    assert str(failure) == "OSError"


class Ticking:
    """A clock that moves on by a fixed number of seconds each time it is read."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.now = 0.0

    def monotonic(self) -> float:
        self.now += self.seconds
        return self.now


@pytest.fixture
def counted_reads(monkeypatch):
    """Every `read` the reader makes of a raster, as the arguments it was given."""
    reads = []
    real_read = raster._rasterio().io.DatasetReader.read

    def counted(self, *args, **kwargs):
        reads.append((args, kwargs))
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(raster._rasterio().io.DatasetReader, "read", counted)
    return reads


def test_a_read_past_its_time_limit_stops_before_the_next_chunk(
    tmp_path, monkeypatch, caplog, counted_reads
):
    """Many chunks of rows, 25 seconds a step: the third chunk is past 60 seconds.

    It used to look at the clock once a band, and one band of a long, thin
    place was sixty requests to a slow lake: minutes, with nothing to stop it.
    """
    path, _ = write_tall(tmp_path / "tall.tif")
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 1)
    monkeypatch.setattr(raster, "time", Ticking(25))

    with caplog.at_level(logging.WARNING), pytest.raises(raster.RasterUnavailable):
        raster.read_stats(path, max_pixels=BUDGET, max_seconds=60)

    assert len(counted_reads) == 2
    assert "given up on after" in caplog.text


def test_a_reduced_read_past_its_time_limit_stops_between_chunks_too(
    tmp_path, monkeypatch, counted_reads
):
    path, _ = write_tall(tmp_path / "tall.tif")
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 1)
    monkeypatch.setattr(raster, "time", Ticking(25))

    with pytest.raises(raster.RasterUnavailable):
        raster.read_stats(path, max_pixels=20_000, max_seconds=60)

    assert len(counted_reads) == 2


def test_a_time_limit_of_zero_is_no_limit(tmp_path, monkeypatch, counted_reads):
    """Zero used to give every read up at its first step."""
    path, _ = write_tall(tmp_path / "tall.tif")
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 1)
    monkeypatch.setattr(raster, "time", Ticking(1000))

    figures = raster.read_stats(path, max_pixels=BUDGET, max_seconds=0)

    assert figures["pixels"] == 300 * 700
    assert len(counted_reads) > 2


def test_a_clip_past_its_time_limit_stops_before_the_next_strip(tmp_path, monkeypatch):
    path, _ = write_tall(tmp_path / "tall.tif")
    monkeypatch.setattr(raster, "_STRIP_BYTES", 1)
    monkeypatch.setattr(raster, "time", Ticking(25))

    with pytest.raises(raster.RasterUnavailable):
        raster.clip(path, bbox=(35.0, 20.0, 36.0, 34.0), max_bytes=BUDGET, max_seconds=60)


def test_a_read_within_its_time_limit_is_not_cut_short(imagery, monkeypatch):
    monkeypatch.setattr(raster, "time", Ticking(1))

    figures = raster.read_stats(imagery, max_pixels=BUDGET, max_seconds=60)

    assert len(figures["bands"]) == 3


def test_gdal_keeps_a_bounded_cache_and_remembers_no_lake_object():
    options = raster._options()

    # GDAL's default block cache is 5% of the machine's memory.
    assert options["GDAL_CACHEMAX"] == 32 * 1024 * 1024
    # A replaced object, or revoked credentials, must not be answered from memory.
    assert options["CPL_VSIL_CURL_NON_CACHED"] == "/vsis3/"


def test_the_keys_are_never_plain_options(settings):
    """rasterio takes credentials through a session; as options it refuses them."""
    settings.LAKE_S3_ENDPOINT = "127.0.0.1:9000"
    settings.LAKE_S3_ACCESS_KEY = "key-id-placeholder"
    settings.LAKE_S3_SECRET_KEY = "secret-placeholder"

    assert "secret-placeholder" not in str(raster._options())
    with raster._env():
        # Scoped to the block and the thread: the process environment is untouched.
        assert "AWS_SECRET_ACCESS_KEY" not in os.environ


def test_inherited_gdal_variables_are_dropped_before_the_first_read(monkeypatch, classified):
    """Conda exports these shell-wide; an old PROJ_DATA fails every CRS lookup."""
    monkeypatch.setenv("PROJ_DATA", "/somewhere/else/share/proj")
    monkeypatch.setenv("GDAL_DATA", "/somewhere/else/share/gdal")

    stats = raster.read_stats(classified, max_pixels=BUDGET, bbox=(35.0, 33.0, 35.25, 33.5))

    assert stats["pixels"] == 1250
    assert "PROJ_DATA" not in os.environ
    assert "GDAL_DATA" not in os.environ


# --- a place far wider than the raster -----------------------------------------

# Boxes whose corners lie outside the area UTM zone 37N is defined for. Moved
# corner by corner they came back as an error, or as infinity and "no pixels".
WIDE_BOXES = [
    (-180.0, -85.0, 180.0, 85.0),
    (-180.0, -90.0, 180.0, 90.0),
    (-52.0, 0.0, 80.0, 60.0),
    (30.0, 0.0, 131.0, 40.0),
    (-60.0, -10.0, 120.0, 70.0),
]


@pytest.mark.parametrize("bbox", WIDE_BOXES)
def test_a_box_far_wider_than_a_projected_raster_counts_the_whole_raster(tmp_path, bbox):
    path = write_utm(tmp_path / "utm.tif")

    stats = raster.read_stats(path, max_pixels=BUDGET, bbox=bbox)

    assert stats["pixels"] == 60 * 40
    assert stats["bands"] == [{"index": 1, "min": 5, "max": 5, "mean": 5.0, "valid_percent": 100.0}]


@pytest.mark.parametrize("bbox", WIDE_BOXES)
def test_a_clip_of_a_box_far_wider_than_a_projected_raster_is_the_whole_raster(tmp_path, bbox):
    path = write_utm(tmp_path / "utm.tif")

    data = raster.clip(path, bbox=bbox, max_bytes=BUDGET)

    with opened(data) as clipped:
        assert (clipped.width, clipped.height) == (60, 40)
        assert clipped.crs.to_epsg() == 32637


def test_a_drawn_area_far_wider_than_a_projected_raster_counts_what_it_covers(tmp_path):
    """The polygon is cut to the raster, not dropped for its far corners."""
    path = write_utm(tmp_path / "utm.tif")
    # A triangle from the Atlantic to India with the raster well inside it.
    area = "POLYGON((-52 0, 131 0, 35 80, -52 0))"

    stats = raster.read_stats(path, max_pixels=BUDGET, bbox=(-52.0, 0.0, 131.0, 80.0), area=area)

    assert stats["pixels"] == 60 * 40


def test_a_wide_drawn_area_that_cuts_through_the_raster_counts_only_its_side(tmp_path):
    """Everything west of the raster's middle, out to the Atlantic."""
    path = write_utm(tmp_path / "utm.tif")
    whole = raster.read_stats(path, max_pixels=BUDGET)
    with raster._env(), raster._rasterio().open(path) as source:
        ((left, bottom, right, top),) = raster._footprints(source)
    middle = (left + right) / 2
    area = f"POLYGON((-52 0, {middle} 0, {middle} 60, -52 60, -52 0))"

    stats = raster.read_stats(path, max_pixels=BUDGET, bbox=(-52.0, 0.0, middle, 60.0), area=area)

    # About half: the cut runs down a meridian, which leans a little in UTM.
    assert 0.4 * whole["pixels"] < stats["pixels"] < 0.6 * whole["pixels"]


def test_a_wide_box_that_misses_the_raster_is_still_a_miss(tmp_path):
    path = write_utm(tmp_path / "utm.tif")

    assert (
        raster.read_stats(path, max_pixels=BUDGET, bbox=(-180.0, -85.0, 0.0, 85.0))["pixels"] == 0
    )
    with pytest.raises(raster.NoOverlap):
        raster.clip(path, bbox=(-180.0, -85.0, 0.0, 85.0), max_bytes=BUDGET)


def test_cutting_a_ring_to_a_box():
    box = (0.0, 0.0, 10.0, 10.0)
    square = [(-5.0, 2.0), (5.0, 2.0), (5.0, 8.0), (-5.0, 8.0), (-5.0, 2.0)]

    assert raster._cut(square, box) == [
        (0.0, 2.0),
        (5.0, 2.0),
        (5.0, 8.0),
        (0.0, 8.0),
        (0.0, 2.0),
    ]
    # Inside already: unchanged. Outside altogether: nothing.
    inside = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 1.0)]
    assert raster._cut(inside, box) == inside
    assert raster._cut([(20.0, 20.0), (30.0, 20.0), (30.0, 30.0), (20.0, 20.0)], box) is None


# --- what the figures leave out, and what they keep ----------------------------


def test_classes_beyond_the_list_are_summed_not_dropped(tmp_path):
    path = write_many_classes(tmp_path / "many.tif", values=300)

    stats = raster.read_stats(path, max_pixels=BUDGET)

    assert len(stats["classes"]) == raster.MAX_CLASSES
    assert stats["other_classes"] == {
        "values": 300 - raster.MAX_CLASSES,
        "pixels": 2 * (300 - raster.MAX_CLASSES),
        "share": pytest.approx((300 - raster.MAX_CLASSES) / 300),
    }
    listed = sum(row["share"] for row in stats["classes"])
    assert listed + stats["other_classes"]["share"] == pytest.approx(1.0)


def test_a_legend_that_fits_the_list_has_no_other_classes(classified):
    assert raster.read_stats(classified, max_pixels=BUDGET)["other_classes"] is None


def test_a_small_figure_is_not_rounded_to_zero(tmp_path):
    path = write_tiny_floats(tmp_path / "tiny.tif")

    (band,) = raster.read_stats(path, max_pixels=BUDGET)["bands"]

    assert band["min"] == pytest.approx(3e-9, rel=1e-6)
    assert band["max"] == pytest.approx(3e-9, rel=1e-6)
    assert band["mean"] == pytest.approx(3e-9, rel=1e-6)


def test_a_share_of_one_pixel_in_many_is_not_zero():
    assert raster._figure(1 / 40_000_000) == 2.5e-08
    assert raster._figure(0.601878123456) == 0.601878123


def test_an_alpha_band_is_a_mask_not_a_band_of_figures(tmp_path):
    path = write_with_alpha(tmp_path / "alpha.tif")

    stats = raster.read_stats(path, max_pixels=BUDGET)

    # The two transparent rows hold no data; the alpha band itself is not listed.
    assert stats["pixels"] == 100
    assert stats["bands"] == [
        {"index": 1, "min": 100, "max": 100, "mean": 100.0, "valid_percent": 80.0}
    ]


@pytest.mark.parametrize(
    ("width", "height", "budget"),
    [(2, 50_000, 1_000), (50_000, 2, 1_000), (1, 5_000_000, 4_000_000), (3_000, 3_000, 1_000_000)],
)
def test_a_reduced_read_is_never_above_the_budget(width, height, budget):
    out_width, out_height = raster._reduced(width, height, budget)

    assert out_width * out_height <= budget
    assert out_width >= 1 and out_height >= 1


def test_a_thin_strip_above_the_budget_is_read_within_it(tmp_path):
    path = write_many_classes(tmp_path / "strip.tif", values=300)  # 300 x 2 pixels

    stats = raster.read_stats(path, max_pixels=100)

    assert stats["approximate"] is True
    assert stats["pixels"] <= 100


# --- the clip's size, mask and tags --------------------------------------------


def test_the_clip_cap_counts_every_band(imagery):
    """50 x 50 pixels of three byte bands are 7,500 bytes, not 2,500."""
    whole = mercator_box_in_degrees(3_900_000, 3_995_000, 3_905_000, 4_000_000)

    with pytest.raises(raster.ClipTooLarge) as refused:
        raster.clip(imagery, bbox=whole, max_bytes=7_499)
    assert (refused.value.size, refused.value.pixels) == (7_500, 2_500)

    with opened(raster.clip(imagery, bbox=whole, max_bytes=7_500)) as clipped:
        assert (clipped.width, clipped.height, clipped.count) == (50, 50, 3)


def test_the_clip_cap_counts_the_bytes_of_a_value(tmp_path):
    """10 x 10 float32 pixels are 400 bytes."""
    path = write_floats(tmp_path / "floats.tif")

    with pytest.raises(raster.ClipTooLarge) as refused:
        raster.clip(path, bbox=(35.0, 33.0, 36.0, 34.0), max_bytes=399)
    assert refused.value.size == 400


def test_a_clip_above_the_cap_reads_no_pixel(classified, monkeypatch):
    """Refused from the window's size alone."""
    rasterio = raster._rasterio()

    def no_read(self, *args, **kwargs):
        raise AssertionError("a refused clip must not read")

    monkeypatch.setattr(rasterio.io.DatasetReader, "read", no_read, raising=False)

    with pytest.raises(raster.ClipTooLarge):
        raster.clip(classified, bbox=(35.0, 33.0, 36.0, 34.0), max_bytes=10)


def test_a_clip_written_strip_by_strip_holds_the_sources_pixels(tmp_path, monkeypatch):
    path, pixels = write_tall(tmp_path / "tall.tif")
    # One block of rows at a time: three strips for 700 rows.
    monkeypatch.setattr(raster, "_STRIP_BYTES", 1)

    data = raster.clip(path, bbox=(35.01, 33.31, 35.29, 33.99), max_bytes=BUDGET)

    with opened(data) as clipped:
        assert (clipped.width, clipped.height) == (280, 680)
        assert (clipped.read() == pixels[:, 10:690, 10:290]).all()


def test_a_clip_keeps_a_mask_stored_with_the_raster(tmp_path):
    from rasterio.enums import MaskFlags

    path = write_masked(tmp_path / "masked.tif")

    data = raster.clip(path, bbox=(35.05, 33.9, 35.15, 34.0), max_bytes=BUDGET)

    with opened(data) as clipped:
        assert clipped.nodata is None
        assert MaskFlags.per_dataset in clipped.mask_flag_enums[0]
        mask = clipped.dataset_mask()
        # Columns 5 to 9 are masked out in the source, 10 to 14 are data.
        assert (mask[:, :5] == 0).all()
        assert (mask[:, 5:] == 255).all()


def test_a_clip_carries_only_the_tags_on_the_list(classified):
    data = raster.clip(classified, bbox=(35.2, 33.2, 35.6, 33.4), max_bytes=BUDGET)

    with opened(data) as clipped:
        tags = clipped.tags()
    assert set(tags) - {"AREA_OR_POINT"} == {"classes", "year"}
    assert b"secret-bucket" not in data
    assert b"lake.internal" not in data


@pytest.mark.parametrize(
    "value",
    [
        "s3://bucket/key.tif",
        "https://minio.internal:9000/bucket/key.tif",
        "/home/x/y.tif",
        "~/data/y.tif",
        "../up/y.tif",
        "raw/landcover/y.tif",
        "src=/home/x/y.tif",
        "C:\\data\\y.tif",
        "\\\\server\\share\\y.tif",
        "/vsis3/bucket/key.tif",
    ],
)
def test_a_value_that_names_a_path_is_not_carried(value):
    assert raster._dataset_tags({"description": value}) == {}


def test_an_ordinary_description_is_carried():
    tags = {"description": "ESRI 10m Land Use/Land Cover 2023", "source": "Planetary Computer"}

    assert raster._dataset_tags(tags) == tags


# --- what reaches the log, and what counts as a failed read ---------------------


def test_rasterios_own_log_lines_never_reach_the_application_log(caplog):
    """rasterio logs each GDAL error with the object's URL: bucket and key."""
    raster._rasterio()

    with caplog.at_level(logging.DEBUG):
        logging.getLogger("rasterio._env").warning(
            "CPLE_AppDefined in HTTP response code on http://lake/secret-bucket/x.tif: 403"
        )
        logging.getLogger("rasterio").error("secret-bucket again")

    assert "secret-bucket" not in caplog.text


def test_a_failed_read_from_the_lake_logs_no_path(settings, caplog):
    """A refused port: GDAL fails at once, and rasterio logs the URL it tried."""
    settings.LAKE_S3_ENDPOINT = "127.0.0.1:9"
    settings.LAKE_S3_URL_STYLE = "path"
    settings.LAKE_S3_USE_SSL = False
    settings.LAKE_S3_ACCESS_KEY = "key-id-placeholder"
    settings.LAKE_S3_SECRET_KEY = "secret-placeholder"

    with caplog.at_level(logging.DEBUG), pytest.raises(raster.RasterUnavailable) as failed:
        raster.read_stats("s3://secret-bucket/raster/landcover.tif", max_pixels=BUDGET)

    assert "secret-bucket" not in caplog.text
    assert "landcover" not in caplog.text
    assert "secret-placeholder" not in caplog.text
    assert "secret-bucket" not in str(failed.value)
    # What failed is still logged, by type.
    assert "Lake unreachable while reading a raster" in caplog.text


def test_a_bug_in_the_reader_is_not_reported_as_an_unreadable_raster(classified, monkeypatch):
    """Only rasterio's and GDAL's errors mean the read failed."""

    def broken(*args, **kwargs):
        raise KeyError("a bug")

    monkeypatch.setattr(raster, "_stats", broken)

    with pytest.raises(KeyError):
        raster.read_stats(classified, max_pixels=BUDGET)


# --- a raster across the antimeridian, and one with no lon/lat box --------------


@pytest.fixture
def across_180(tmp_path):
    return write_across_180(tmp_path / "utm60.tif")


def test_a_raster_across_the_antimeridian_has_a_footprint_on_each_side(across_180):
    with raster._env(), raster._rasterio().open(across_180) as source:
        east_of_greenwich, west_of_greenwich = raster._footprints(source)

    assert 179 < east_of_greenwich[0] < 180 and east_of_greenwich[2] == 180.0
    assert west_of_greenwich[0] == -180.0 and -177 < west_of_greenwich[2] < -175


@pytest.mark.parametrize(
    "bbox",
    [
        (-180.0, -90.0, 180.0, 90.0),
        (-180.0, 0.0, 180.0, 90.0),
        (-180.0, 40.0, 180.0, 60.0),
    ],
)
def test_a_wide_box_over_a_raster_across_the_antimeridian_counts_all_of_it(across_180, bbox):
    """It answered 208 of 60,000 pixels, and said the figure was exact."""
    figures = raster.read_stats(across_180, max_pixels=BUDGET, bbox=bbox)

    assert figures["pixels"] == 300 * 200
    assert figures["approximate"] is False


def test_each_side_of_the_antimeridian_counts_its_own_pixels(across_180):
    """A hemisphere is the same as the part of it near the raster: a 502 before."""
    whole = raster.read_stats(across_180, max_pixels=BUDGET)["pixels"]
    east = raster.read_stats(across_180, max_pixels=BUDGET, bbox=(0.0, 0.0, 180.0, 90.0))
    west = raster.read_stats(across_180, max_pixels=BUDGET, bbox=(-180.0, 0.0, 0.0, 90.0))
    near_east = raster.read_stats(across_180, max_pixels=BUDGET, bbox=(175.0, 40.0, 180.0, 60.0))

    assert east["pixels"] == near_east["pixels"]
    assert 0 < east["pixels"] < west["pixels"]
    assert east["pixels"] + west["pixels"] == whole


def test_a_drawn_area_across_both_sides_counts_both(across_180):
    world = "POLYGON((-180 -90, 180 -90, 180 90, -180 90, -180 -90))"

    figures = raster.read_stats(
        across_180, max_pixels=BUDGET, bbox=(-180.0, -90.0, 180.0, 90.0), area=world
    )

    assert figures["pixels"] == 300 * 200


def test_a_clip_of_a_wide_box_across_the_antimeridian_is_the_whole_raster(across_180):
    data = raster.clip(across_180, bbox=(-180.0, -90.0, 180.0, 90.0), max_bytes=BUDGET)

    with opened(data) as clipped:
        assert (clipped.width, clipped.height) == (300, 200)


def test_a_clip_of_one_side_of_the_antimeridian_is_that_side(across_180):
    east = raster.clip(across_180, bbox=(0.0, 0.0, 180.0, 90.0), max_bytes=BUDGET)
    west = raster.clip(across_180, bbox=(-180.0, 0.0, 0.0, 90.0), max_bytes=BUDGET)

    with opened(east) as clipped:
        assert 0 < clipped.width < 60 and clipped.height == 200
    with opened(west) as clipped:
        assert 240 < clipped.width < 300 and clipped.height == 200


def test_a_raster_with_no_lon_lat_box_takes_no_place_rather_than_a_wrong_count(tmp_path, caplog):
    """The whole world in Mollweide was counted about 1% wrong, without a word."""
    path = write_whole_world_mollweide(tmp_path / "mollweide.tif")
    africa = (-20.0, -35.0, 60.0, 40.0)

    # With no place there is nothing to put on it, so it still reads.
    assert raster.read_stats(path, max_pixels=BUDGET)["pixels"] == 360 * 180
    with caplog.at_level(logging.WARNING):
        with pytest.raises(raster.RasterNotPlaceable):
            raster.read_stats(path, max_pixels=BUDGET, bbox=africa)
        with pytest.raises(raster.RasterNotPlaceable):
            raster.clip(path, bbox=africa, max_bytes=BUDGET)
        with pytest.raises(raster.RasterNotPlaceable):
            raster.clip_size(path, bbox=africa, max_bytes=BUDGET)
    assert "no lon/lat box" in caplog.text


def test_a_raster_with_longitudes_from_0_to_360_takes_no_place_either(tmp_path):
    """Its western half was missed without a word: a place there was "no pixels"."""
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    path = str(tmp_path / "lon360.tif")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=360,
        height=180,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(0, 90, 1, 1),
    ) as target:
        target.write(numpy.full((180, 360), 5, dtype="uint8"), 1)

    assert raster.read_stats(path, max_pixels=BUDGET)["pixels"] == 360 * 180
    with pytest.raises(raster.RasterNotPlaceable):
        raster.read_stats(path, max_pixels=BUDGET, bbox=(-100.0, 30.0, -80.0, 50.0))
    with pytest.raises(raster.RasterNotPlaceable):
        raster.read_stats(path, max_pixels=BUDGET, bbox=(10.0, 30.0, 30.0, 50.0))


@pytest.mark.parametrize(
    ("west", "pixel", "width", "height"),
    [
        # Pixels centred on the round degrees: half a pixel past each side.
        (-180.5, 1.0, 361, 181),
        # A rounding error wider than the world.
        (-180.0 - 1e-7, 1.0, 360, 180),
        (-180.0 + 1e-7, 1.0, 360, 180),
    ],
)
def test_a_world_grid_a_hair_past_180_still_takes_a_place(tmp_path, west, pixel, width, height):
    """It was a read error for a place in mid-Africa: any overshoot at all
    was taken for another way of writing longitude."""
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    north = 90.0 + (height - 180) / 2
    path = str(tmp_path / "world.tif")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(west, north, pixel, pixel),
    ) as target:
        target.write(numpy.full((height, width), 5, dtype="uint8"), 1)

    # Off the pixel centres on every side, so no centre sits on the box's edge.
    figures = raster.read_stats(path, max_pixels=BUDGET, bbox=(10.25, -10.25, 30.25, 10.25))

    # Twenty columns of centres between 10.25 and 30.25 either way; the rows
    # are centred on the round degrees (21 of them) or on the halves (20).
    assert figures["pixels"] == 20 * (21 if height == 181 else 20)
    with opened(raster.clip(path, bbox=(10.25, -10.25, 30.25, 10.25), max_bytes=BUDGET)) as clip:
        assert 20 <= clip.width <= 22


# --- a place with no size ----------------------------------------------------------


@pytest.mark.parametrize(
    "point",
    [
        (35.2, 33.1),  # exactly on a pixel corner of the 0.01 degree grid
        (35.205, 33.105),  # inside a pixel
        (35.2, 33.105),  # on a vertical pixel edge
        (35.0, 33.0),  # the raster's own corner
        (36.0, 33.0),  # its far corner
    ],
)
def test_a_point_on_the_raster_counts_one_pixel(classified, point):
    """A box with no size on a pixel edge was "no pixels", though it is on the raster."""
    lon, lat = point

    figures = raster.read_stats(classified, max_pixels=BUDGET, bbox=(lon, lat, lon, lat))
    data = raster.clip(classified, bbox=(lon, lat, lon, lat), max_bytes=BUDGET)

    assert figures["pixels"] == 1
    assert figures["bands"][0]["valid_percent"] == 100.0
    with opened(data) as clipped:
        assert (clipped.width, clipped.height) == (1, 1)


def test_a_point_on_a_pixel_corner_is_the_pixel_that_starts_there(classified):
    """Column 50 is where class 7 ends and class 1 begins."""
    figures = raster.read_stats(classified, max_pixels=BUDGET, bbox=(35.5, 33.5, 35.5, 33.5))

    assert [row["value"] for row in figures["classes"]] == [1]


def test_a_line_on_a_pixel_edge_counts_the_pixels_that_start_there(classified):
    figures = raster.read_stats(classified, max_pixels=BUDGET, bbox=(35.2, 33.1, 35.2, 33.5))

    assert figures["pixels"] == 40


def test_a_point_off_the_raster_is_still_a_miss(classified):
    assert raster.read_stats(classified, max_pixels=BUDGET, bbox=(40.0, 33.5, 40.0, 33.5)) == {
        "pixels": 0,
        "approximate": False,
        "bands": [],
        "classes": [],
        "other_classes": None,
    }
    with pytest.raises(raster.NoOverlap):
        raster.clip(classified, bbox=(40.0, 33.5, 40.0, 33.5), max_bytes=BUDGET)


def test_a_place_that_only_touches_the_rasters_edge_is_still_a_miss(classified):
    """Having size, and ending where the raster begins: it covers no pixel."""
    assert (
        raster.read_stats(classified, max_pixels=BUDGET, bbox=(34.0, 33.2, 35.0, 33.4))["pixels"]
        == 0
    )


@pytest.mark.parametrize(
    ("low", "high", "size", "expected"),
    [
        (2.2, 4.7, 10, (2, 5)),
        (2.0, 4.0, 10, (2, 4)),
        (3.0, 3.0, 10, (3, 4)),
        (3.4, 3.4, 10, (3, 4)),
        (0.0, 0.0, 10, (0, 1)),
        (10.0, 10.0, 10, (9, 10)),
        (-5.0, 0.0, 10, None),
        (10.0, 12.0, 10, None),
        (11.0, 11.0, 10, None),
        (-3.0, 30.0, 10, (0, 10)),
    ],
)
def test_the_pixels_a_stretch_covers(low, high, size, expected):
    assert raster._span(low, high, size) == expected


# --- a clip that cannot be written, and one whose check reads no pixel ----------


def test_a_clip_that_cannot_be_written_is_not_called_a_bad_raster(classified, monkeypatch, caplog):
    """A full disk failed inside rasterio's write, and was reported as the lake's."""
    from rasterio.errors import RasterioIOError

    def full_disk(self, *args, **kwargs):
        raise RasterioIOError("Write failed. /tmp/clip-abc/clip.tif: No space left on device")

    monkeypatch.setattr(raster._rasterio().io.DatasetWriter, "write", full_disk)

    with caplog.at_level(logging.WARNING), pytest.raises(raster.ClipNotWritten) as failed:
        raster.clip(classified, bbox=(35.2, 33.2, 35.6, 33.4), max_bytes=BUDGET)

    assert str(failed.value) == "RasterioIOError"
    assert "could not be written to local disk" in caplog.text
    assert "Unreadable raster" not in caplog.text
    assert "clip-abc" not in caplog.text


def test_a_temporary_folder_that_cannot_be_made_is_a_write_failure(classified, monkeypatch):
    def no_space(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(raster.tempfile, "TemporaryDirectory", no_space)

    with pytest.raises(raster.ClipNotWritten):
        raster.clip(classified, bbox=(35.2, 33.2, 35.6, 33.4), max_bytes=BUDGET)


def test_a_read_that_fails_in_the_middle_of_a_clip_is_still_a_read_error(tmp_path, monkeypatch):
    from rasterio.errors import RasterioIOError

    path, _ = write_tall(tmp_path / "tall.tif")
    monkeypatch.setattr(raster, "_STRIP_BYTES", 1)
    real_read = raster._rasterio().io.DatasetReader.read
    reads = []

    def second_strip_fails(self, *args, **kwargs):
        reads.append(1)
        if len(reads) == 2:
            raise RasterioIOError("Read failed")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(raster._rasterio().io.DatasetReader, "read", second_strip_fails)
    left_behind = set(os.listdir(raster.tempfile.gettempdir()))

    with pytest.raises(raster.RasterReadError):
        raster.clip(path, bbox=(35.0, 20.0, 36.0, 34.0), max_bytes=BUDGET)

    new = set(os.listdir(raster.tempfile.gettempdir())) - left_behind
    assert not [name for name in new if name.startswith("clip-")]


def test_the_size_of_a_clip_is_known_without_reading_a_pixel(classified, monkeypatch):
    def no_pixels(self, *args, **kwargs):
        raise AssertionError("a pixel was read")

    monkeypatch.setattr(raster._rasterio().io.DatasetReader, "read", no_pixels)

    assert raster.clip_size(classified, bbox=(35.2, 33.2, 35.6, 33.4), max_bytes=BUDGET) == 800
    with pytest.raises(raster.ClipTooLarge):
        raster.clip_size(classified, bbox=(35.2, 33.2, 35.6, 33.4), max_bytes=799)
    with pytest.raises(raster.NoOverlap):
        raster.clip_size(classified, bbox=(40.0, 33.2, 41.0, 33.4), max_bytes=BUDGET)


# --- which tag values a clip carries --------------------------------------------

# The shapes the review found carried on an allowed tag.
PATH_SHAPES = [
    "..\\share\\x",
    "data\\raw\\x.tif",
    "see ../raw/thing",
    "bucket/key/file.geotiff",
    "host:9000/bucket/key",
    "file:/etc/passwd",
    "bucket=geobase-silver key=raster/a/b",
]


@pytest.mark.parametrize("value", PATH_SHAPES)
@pytest.mark.parametrize("key", ["source", "collection", "year", "description"])
def test_no_allowed_tag_carries_the_shape_of_a_path(key, value):
    assert raster._dataset_tags({key: value}) == {}


@pytest.mark.parametrize(
    "value", ["raw/landcover", "a/b", "ratio 1/2", "https://example.org", "x\\y"]
)
def test_a_short_value_with_any_slash_is_not_carried(value):
    """A year, a collection id, a provider's name: none of them holds a slash."""
    assert raster._dataset_tags({"source": value, "collection": value, "year": value}) == {}


def test_a_sentence_may_hold_a_slash_that_is_not_a_path():
    tags = {"description": "Land Use/Land Cover, ratio 1/2, by the a/b team"}

    assert raster._dataset_tags(tags) == tags


def test_the_tags_the_real_rasters_carry_come_through():
    """As read from the catalog's land-cover rasters on 2026-11-10."""
    tags = {
        "AREA_OR_POINT": "Area",
        "classes": '{"1": "water", "2": "trees", "7": "built_area"}',
        "collection": "io-lulc-9-class",
        "description": "ESRI 10m Land Use Land Cover 2023",
        "source": "Microsoft Planetary Computer STAC",
        "year": "2023",
    }

    assert raster._dataset_tags(tags) == tags


def test_a_legend_is_carried_as_a_legend_even_with_a_slash_in_a_name():
    legend = '{"60": "Bare / sparse vegetation", "9": "snow/ice"}'

    assert raster._dataset_tags({"classes": legend}) == {"classes": legend}


def test_a_legend_is_written_again_from_its_entries_not_passed_on_as_text():
    """Any JSON object used to pass, and the clip got the raw text: a path as
    a key, a nested value, a key that is no class at all."""
    legend = json.dumps(
        {
            "1": "water",
            "/home/lake/x.tif": "trees",
            "2": {"src": "/vsis3/secret-bucket/x.tif"},
            "__src": "minio:9000/secret-bucket",
            "3": "s3://secret-bucket/raster/x.tif",
            "4": "raw/landcover/y.tif",
            "7": "built_area",
        }
    )

    carried = raster._dataset_tags({"classes": legend})

    assert json.loads(carried["classes"]) == {"1": "water", "7": "built_area"}
    assert "secret-bucket" not in carried["classes"]


def test_a_legend_with_no_entry_left_is_not_carried():
    legend = '{"__src": "minio:9000/secret-bucket", "1": {"a": 1}}'

    assert raster._dataset_tags({"classes": legend}) == {}


def test_a_slash_standing_alone_in_a_sentence_is_not_a_path():
    assert not raster._names_a_path("Land Use / Land Cover")
    assert raster._names_a_path("see /data/raw")


@pytest.mark.parametrize("value", ["s3://bucket/legend.json", "/data/legend.json", "[1, 2]", ""])
def test_a_classes_tag_that_is_not_a_legend_is_not_carried(value):
    assert raster._dataset_tags({"classes": value}) == {}


# --- a statistics read goes a chunk of rows at a time --------------------------


def write_bands(path, data, *, mask=None, nodata=None, legend=None, crs="EPSG:4326") -> str:
    """Bands of any type, 0.001 degrees a pixel from 35 E, 34 N, in 64-pixel tiles."""
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    count, height, width = data.shape
    with (
        rasterio.Env(GDAL_TIFF_INTERNAL_MASK="YES"),
        rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=count,
            dtype=data.dtype,
            crs=crs,
            transform=from_origin(35.0, 34.0, 0.001, 0.001),
            nodata=nodata,
            tiled=True,
            blockxsize=64,
            blockysize=64,
            interleave="pixel",
        ) as target,
    ):
        target.write(data)
        if mask is not None:
            target.write_mask(mask)
        if legend is not None:
            target.update_tags(classes=legend)
    return str(path)


def centres_inside_triangle(height, width, corners):
    """Which pixel centres lie inside a triangle given in pixel coordinates (col, row)."""
    cols, rows = numpy.meshgrid(numpy.arange(width) + 0.5, numpy.arange(height) + 0.5)
    signs = []
    for (c0, r0), (c1, r1) in zip(corners, corners[1:] + corners[:1], strict=True):
        signs.append((c1 - c0) * (rows - r0) - (r1 - r0) * (cols - c0))
    return ((signs[0] > 0) & (signs[1] > 0) & (signs[2] > 0)) | (
        (signs[0] < 0) & (signs[1] < 0) & (signs[2] < 0)
    )


def triangle_wkt(corners) -> tuple[str, tuple[float, float, float, float]]:
    """Pixel corners (col, row) as the WKT and envelope a caller would send."""
    points = [(35.0 + col * 0.001, 34.0 - row * 0.001) for col, row in corners]
    ring = ", ".join(f"{lon:.7f} {lat:.7f}" for lon, lat in [*points, points[0]])
    lons, lats = zip(*points, strict=True)
    return f"POLYGON(({ring}))", (min(lons), min(lats), max(lons), max(lats))


def expected_band(values, pixels) -> dict:
    return {
        "min": raster._number(values.min()),
        "max": raster._number(values.max()),
        "mean": raster._figure(float(values.mean(dtype=numpy.float64))),
        "valid_percent": raster._figure(100.0 * values.size / pixels),
    }


def test_a_chunked_read_gives_the_figures_of_the_whole_window_at_once(
    tmp_path, monkeypatch, counted_reads
):
    """Three bands with a mask of their own, inside a triangle, a block row at a time."""
    rng = numpy.random.default_rng(3)
    data = rng.integers(0, 60_000, size=(3, 300, 200), dtype="uint16")
    mask = (rng.random((300, 200)) > 0.25).astype("uint8") * 255
    path = write_bands(tmp_path / "bands.tif", data, mask=mask)
    corners = [(10.3, 20.7), (180.6, 60.2), (70.4, 280.9)]
    area, envelope = triangle_wkt(corners)
    inside = centres_inside_triangle(300, 200, corners)
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 1)

    figures = raster.read_stats(path, max_pixels=BUDGET, bbox=envelope, area=area)

    assert figures["pixels"] == int(inside.sum())
    assert figures["approximate"] is False
    valid = inside & (mask > 0)
    for position, band in enumerate(figures["bands"]):
        assert band == {
            "index": position + 1,
            **expected_band(data[position][valid], figures["pixels"]),
        }
    # Several chunks, and every band of a chunk in the one read.
    assert len(counted_reads) >= 4
    assert all(args[0] == [1, 2, 3] for args, _ in counted_reads)


def test_a_chunked_read_of_floats_skips_nodata_nan_and_infinity(tmp_path, monkeypatch):
    rng = numpy.random.default_rng(5)
    data = rng.normal(5.0, 3.0, size=(2, 260, 150)).astype("float32")
    data[0, ::7, ::5] = -9999.0
    data[1, ::11, ::3] = numpy.nan
    data[1, 5::13, 2::9] = numpy.inf
    path = write_bands(tmp_path / "floats.tif", data, nodata=-9999.0)
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 1)

    figures = raster.read_stats(path, max_pixels=BUDGET)

    assert figures["pixels"] == 260 * 150
    for position, band in enumerate(figures["bands"]):
        values = data[position]
        values = values[numpy.isfinite(values) & (values != -9999.0)]
        assert band == {"index": position + 1, **expected_band(values, figures["pixels"])}


def test_classes_are_counted_across_chunks(tmp_path, monkeypatch, counted_reads):
    rng = numpy.random.default_rng(9)
    data = rng.integers(0, 9, size=(1, 300, 130), dtype="uint8")
    legend = '{"1": "water", "7": "built_area"}'
    path = write_bands(tmp_path / "classes.tif", data, nodata=0, legend=legend)
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 1)

    figures = raster.read_stats(path, max_pixels=BUDGET)

    values, counts = numpy.unique(data[data != 0], return_counts=True)
    assert {row["value"]: row["pixels"] for row in figures["classes"]} == dict(
        zip(values.tolist(), counts.tolist(), strict=True)
    )
    assert sum(row["share"] for row in figures["classes"]) == pytest.approx(1.0)
    assert figures["classes"][0]["pixels"] == counts.max()
    assert len(counted_reads) >= 4


def test_a_chunk_is_whole_rows_of_blocks_and_ends_where_a_block_row_ends(tmp_path, monkeypatch):
    """A block is fetched whole, so a chunk that ended inside one would have
    the lake send it again for the next chunk."""
    from rasterio.windows import Window

    data = numpy.zeros((3, 300, 200), dtype="uint8")
    path = write_bands(tmp_path / "blocks.tif", data)
    # Room for two of this file's blocks (64 x 64 x 3 bytes), and no more.
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 2 * 64 * 64 * 3)

    with raster._rasterio().open(path) as source:
        # One block across: two rows of blocks a chunk.
        assert raster._chunk_rows(source, Window(70, 10, 40, 280), 40, 280, [1, 2, 3]) == 128
        # Three blocks across: one row of blocks is already more than the room.
        assert raster._chunk_rows(source, Window(10, 10, 180, 280), 180, 280, [1, 2, 3]) == 64

    # A window that starts at row 10: the first chunk ends on the raster's
    # row 128, not 128 rows further down.
    assert raster._row_chunks(10, 280, 128) == [(0, 118), (118, 246), (246, 280)]
    assert raster._row_chunks(0, 64, 128) == [(0, 64)]


def test_a_chunk_never_holds_more_than_its_cap(tmp_path, monkeypatch):
    from rasterio.windows import Window

    data = numpy.zeros((2, 100, 400), dtype="float64")
    path = write_bands(tmp_path / "wide.tif", data)
    # Two float64 bands and a mask byte each: 18 bytes a pixel, 7,200 a row.
    monkeypatch.setattr(raster, "_CHUNK_HELD_BYTES", 7_200 * 10)

    with raster._rasterio().open(path) as source:
        assert raster._chunk_rows(source, Window(0, 0, 400, 100), 400, 100, [1, 2]) == 10


def test_a_reduced_read_in_chunks_is_the_reduced_read(tmp_path, monkeypatch, counted_reads):
    """The same reduced grid, a few rows of it at a time."""
    rng = numpy.random.default_rng(13)
    data = rng.integers(1, 200, size=(2, 600, 400), dtype="uint8")
    path = write_bands(tmp_path / "large.tif", data)

    at_once = raster.read_stats(path, max_pixels=30_000)
    assert len(counted_reads) == 1
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 1)
    in_chunks = raster.read_stats(path, max_pixels=30_000)

    assert at_once["approximate"] is True and in_chunks["approximate"] is True
    assert in_chunks["pixels"] == at_once["pixels"] <= 30_000
    assert len(counted_reads) > 3
    for one, other in zip(at_once["bands"], in_chunks["bands"], strict=True):
        assert other["mean"] == pytest.approx(one["mean"], rel=0.02)
        assert other["valid_percent"] == one["valid_percent"] == 100.0


# --- a reduced read of a raster with no overview -------------------------------


def test_a_reduced_read_with_no_overview_keeps_the_pixels_gdal_would(tmp_path, monkeypatch):
    """The reader picks the pixels itself, from full-size slices. They are
    the ones GDAL keeps when it is asked for the window at reduced size."""
    from rasterio.enums import Resampling

    rng = numpy.random.default_rng(17)
    data = rng.integers(0, 250, size=(2, 610, 430), dtype="uint8")
    mask = (rng.random((610, 430)) > 0.2).astype("uint8") * 255
    path = write_bands(tmp_path / "plain.tif", data, mask=mask)
    # Slices of a few rows, and chunks of a few rows of the reduced grid.
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 1)
    monkeypatch.setattr(raster, "_CHUNK_HELD_BYTES", 430 * 4 * 7)

    figures = raster.read_stats(path, max_pixels=20_000)

    out_width, out_height = raster._reduced(430, 610, 20_000)
    with raster._rasterio().open(path) as source:
        assert source.overviews(1) == []
        reduced = source.read(
            out_shape=(2, out_height, out_width), resampling=Resampling.nearest, masked=True
        )
    assert figures["approximate"] is True
    assert figures["pixels"] == out_width * out_height
    for position, band in enumerate(figures["bands"]):
        values = reduced[position].compressed()
        assert band == {"index": position + 1, **expected_band(values, figures["pixels"])}


def test_a_slice_no_kept_row_falls_in_is_not_read(tmp_path, monkeypatch, counted_reads):
    """One row in twenty is kept, and slices are five rows: three in four are skipped."""
    data = numpy.arange(1000, dtype="uint16").repeat(10).reshape(1, 1000, 10)
    path = write_bands(tmp_path / "thin.tif", data)
    monkeypatch.setattr(raster, "_CHUNK_HELD_BYTES", 10 * 3 * 5)

    figures = raster.read_stats(path, max_pixels=50)

    assert figures["pixels"] == 50
    assert len(counted_reads) == 50
    # Row 10 is the first kept (the centre of the first twenty), row 990 the last.
    assert figures["bands"][0]["min"] == 10 and figures["bands"][0]["max"] == 990


def test_a_reduced_read_with_no_overview_looks_at_the_clock_before_each_slice(
    tmp_path, monkeypatch, counted_reads
):
    path, _ = write_tall(tmp_path / "tall.tif")
    # One chunk, in slices of ten full-size rows (two byte bands and a mask byte each).
    monkeypatch.setattr(raster, "_CHUNK_HELD_BYTES", 300 * 4 * 10)
    monkeypatch.setattr(raster, "time", Ticking(25))

    with pytest.raises(raster.RasterUnavailable):
        raster.read_stats(path, max_pixels=20_000, max_seconds=60)

    assert len(counted_reads) == 2


def test_a_reduced_read_from_an_overview_in_chunks_is_close_to_the_read_at_once(
    tmp_path, monkeypatch, counted_reads
):
    """GDAL reads an overview when there is one; each chunk asks it for its
    share of the window. A pixel or two may fall the other way."""
    from rasterio.enums import Resampling

    rng = numpy.random.default_rng(19)
    data = rng.integers(1, 200, size=(2, 800, 640), dtype="uint8")
    path = write_bands(tmp_path / "cog.tif", data)
    with raster._rasterio().open(path, "r+") as target:
        target.build_overviews([2, 4], Resampling.nearest)

    at_once = raster.read_stats(path, max_pixels=40_000)
    assert len(counted_reads) == 1
    assert counted_reads[0][1]["out_shape"][1:] == (223, 178)
    monkeypatch.setattr(raster, "_CHUNK_BLOCK_BYTES", 1)
    in_chunks = raster.read_stats(path, max_pixels=40_000)

    assert len(counted_reads) > 3
    assert in_chunks["pixels"] == at_once["pixels"]
    for one, other in zip(at_once["bands"], in_chunks["bands"], strict=True):
        assert other["mean"] == pytest.approx(one["mean"], rel=0.01)
        assert other["valid_percent"] == 100.0


def test_gdal_reads_the_coarsest_overview_that_is_fine_enough(tmp_path):
    from rasterio.enums import Resampling

    path = write_bands(tmp_path / "cog.tif", numpy.zeros((1, 800, 640), dtype="uint8"))
    with raster._rasterio().open(path, "r+") as target:
        target.build_overviews([2, 4], Resampling.nearest)

    with raster._rasterio().open(path) as source:
        assert raster._overview_factor(source, 1, 1.0) == 1
        assert raster._overview_factor(source, 1, 1.5) == 1
        assert raster._overview_factor(source, 1, 2.0) == 2
        assert raster._overview_factor(source, 1, 3.5) == 4  # a fifth coarser is allowed
        assert raster._overview_factor(source, 1, 50.0) == 4
