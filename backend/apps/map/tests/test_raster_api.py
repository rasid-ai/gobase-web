"""GET /api/map/assets/{id}/raster-stats and /clip.tif — a raster's figures and a clip of it.

The catalog is faked at its own boundary, as for `/data`; the raster is not:
both endpoints read a real GeoTIFF from a temporary directory. What the reader
itself does with each place is in `test_raster.py`; here it is the endpoints
around it (docs/adr/029).
"""

import uuid

import pytest
from django.contrib.auth.models import User

from apps.accounts.models import ApiKey, Role, UserProfile
from apps.catalog import kb
from apps.map import raster

from .rasters import write_classified, write_imagery, write_many_classes, write_utm

ASSET_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TRIANGLE = "POLYGON((35.0 33.0, 35.5 33.0, 35.0 33.5, 35.0 33.0))"


def stats_url(asset_id=ASSET_ID) -> str:
    return f"/api/map/assets/{asset_id}/raster-stats"


def clip_url(asset_id=ASSET_ID) -> str:
    return f"/api/map/assets/{asset_id}/clip.tif"


@pytest.fixture(autouse=True)
def no_object_store(settings):
    """A local path needs no store: whatever the developer's .env holds is blanked."""
    settings.LAKE_S3_ENDPOINT = ""
    settings.LAKE_S3_REGION = ""
    settings.LAKE_S3_ACCESS_KEY = ""
    settings.LAKE_S3_SECRET_KEY = ""
    settings.RASTER_STATS_MAX_PIXELS = 1_000_000
    settings.RASTER_CLIP_MAX_BYTES = 1_000_000


@pytest.fixture
def landcover(monkeypatch, tmp_path):
    """A classified raster over longitude 35-36, latitude 33-34 (see `rasters.py`)."""
    path = write_classified(tmp_path / "secret-bucket-path.tif")
    monkeypatch.setattr(
        kb, "raster_source", lambda asset_id: {"source_uri": path, "name": "lulc_2023"}
    )
    return path


@pytest.fixture
def imagery(monkeypatch, tmp_path):
    path = write_imagery(tmp_path / "city.tif")
    monkeypatch.setattr(
        kb, "raster_source", lambda asset_id: {"source_uri": path, "name": "tripoli_z18"}
    )
    return path


def opened(data: bytes):
    from rasterio.io import MemoryFile

    return MemoryFile(data).open()


# --- raster-stats --------------------------------------------------------------


def test_stats_require_authentication(api):
    assert api.get(stats_url()).status_code == 401


def test_stats_over_a_bbox(as_viewer, landcover):
    response = as_viewer.get(stats_url(), {"bbox": "35.0,33.0,35.25,33.5"})

    assert response.status_code == 200
    assert response.json() == {
        "asset_id": str(ASSET_ID),
        "pixels": 1250,
        "approximate": False,
        "bands": [{"index": 1, "min": 7.0, "max": 7.0, "mean": 7.0, "valid_percent": 100.0}],
        "classes": [{"value": 7, "name": "built_area", "pixels": 1250, "share": 1.0}],
        "other_classes": None,
    }


def test_stats_over_a_drawn_area_count_the_shape(as_viewer, landcover):
    boxed = as_viewer.get(stats_url(), {"bbox": "35.0,33.0,35.5,33.5"}).json()
    shaped = as_viewer.get(stats_url(), {"area": TRIANGLE}).json()

    assert boxed["pixels"] == 2500
    assert 1200 <= shaped["pixels"] <= 1300


def test_stats_over_the_whole_raster_without_a_place(as_viewer, landcover):
    body = as_viewer.get(stats_url()).json()

    assert body["pixels"] == 10_000
    assert [(row["name"], row["share"]) for row in body["classes"]] == [
        ("water", 0.5),
        ("built_area", 0.5),
    ]


def test_stats_above_the_budget_say_they_are_approximate(as_viewer, landcover, settings):
    settings.RASTER_STATS_MAX_PIXELS = 100

    body = as_viewer.get(stats_url()).json()

    assert body["approximate"] is True
    assert body["pixels"] <= 100


def test_a_raster_with_no_legend_has_null_classes(as_viewer, imagery):
    body = as_viewer.get(stats_url()).json()

    assert body["classes"] is None
    assert [band["mean"] for band in body["bands"]] == [10.0, 20.0, 30.0]


def test_a_place_that_misses_the_raster_is_an_empty_answer(as_viewer, landcover):
    response = as_viewer.get(stats_url(), {"bbox": "2.2,48.8,2.4,48.9"})

    assert response.status_code == 200
    assert response.json() == {
        "asset_id": str(ASSET_ID),
        "pixels": 0,
        "approximate": False,
        "bands": [],
        "classes": [],
        "other_classes": None,
    }


def test_stats_refuse_a_bbox_and_an_area_together(as_viewer, landcover):
    response = as_viewer.get(stats_url(), {"bbox": "35.0,33.0,35.5,33.5", "area": TRIANGLE})

    assert response.status_code == 400
    assert "not both" in str(response.json())


@pytest.mark.parametrize(
    "params",
    [
        {"bbox": "35.5,33.0,35.0,33.5"},
        {"bbox": "west,33.0,35.0,33.5"},
        {"area": "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"},
        {"area": "DROP TABLE assets"},
    ],
)
def test_stats_refuse_an_unreadable_place(as_viewer, landcover, params):
    assert as_viewer.get(stats_url(), params).status_code == 400


def test_stats_for_anything_but_an_active_raster_are_404(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "raster_source", lambda asset_id: None)

    assert as_viewer.get(stats_url()).status_code == 404


def test_stats_from_an_unreachable_lake_are_503(as_viewer, landcover, monkeypatch):
    def unreachable(*args, **kwargs):
        raise raster.RasterUnavailable("RasterioIOError")

    monkeypatch.setattr(raster, "read_stats", unreachable)

    assert as_viewer.get(stats_url()).status_code == 503


def test_stats_of_an_unreadable_raster_are_502(as_viewer, monkeypatch, tmp_path):
    """The catalog names a raster the lake does not hold."""
    missing = str(tmp_path / "secret-bucket-path.tif")
    monkeypatch.setattr(
        kb, "raster_source", lambda asset_id: {"source_uri": missing, "name": "gone"}
    )

    response = as_viewer.get(stats_url())

    assert response.status_code == 502
    assert "secret-bucket-path" not in response.content.decode()


def test_the_lake_path_is_in_no_answer(as_viewer, landcover):
    for response in (
        as_viewer.get(stats_url()),
        as_viewer.get(stats_url(), {"bbox": "35.0,33.0,35.25,33.5"}),
        as_viewer.get(clip_url()),
        as_viewer.get(clip_url(), {"bbox": "2.2,48.8,2.4,48.9"}),
    ):
        assert "secret-bucket-path" not in response.content.decode(errors="replace")


def test_an_api_key_may_read_both(api, db, landcover):
    """The Ask agent calls with a key, and a key may only GET (docs/adr/021)."""
    user = User.objects.create_user(username="gobase-agent", password="unused-password-1")
    UserProfile.objects.create(user=user, role=Role.VIEWER)
    _, raw = ApiKey.issue(user, "the Ask agent")
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    place = {"bbox": "35.0,33.0,35.25,33.5"}

    assert api.get(stats_url(), place).status_code == 200
    assert api.get(clip_url(), place).status_code == 200


# --- clip.tif -------------------------------------------------------------------


def test_a_clip_requires_authentication(api):
    assert api.get(clip_url(), {"bbox": "35.0,33.0,35.25,33.5"}).status_code == 401


def test_a_clip_is_a_geotiff_download_named_after_the_asset(as_viewer, landcover):
    response = as_viewer.get(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"})

    assert response.status_code == 200
    assert response["Content-Type"] == "image/tiff"
    assert response["Content-Disposition"] == 'attachment; filename="lulc_2023_clip.tif"'
    assert response["Content-Length"] == str(len(response.content))
    with opened(response.content) as clipped:
        assert (clipped.width, clipped.height) == (40, 20)
        assert clipped.crs.to_epsg() == 4326
        assert clipped.tags()["classes"] == '{"1": "water", "7": "built_area"}'


def test_a_clip_of_a_drawn_area_is_its_envelope_not_a_mask(as_viewer, landcover):
    """The triangle's corner away from the hypotenuse still holds its pixels."""
    response = as_viewer.get(clip_url(), {"area": TRIANGLE})

    with opened(response.content) as clipped:
        assert (clipped.width, clipped.height) == (50, 50)
        # Top right of the envelope, outside the triangle: data, not nodata.
        assert clipped.read(1)[0, 49] == 7


def test_a_clip_counts_what_the_stats_counted(as_viewer, landcover):
    """The same rectangle, both ways: the clip's pixels are the stats' pixels."""
    import numpy

    place = {"bbox": "35.3,33.1,35.7,33.6"}
    stats = as_viewer.get(stats_url(), place).json()

    with opened(as_viewer.get(clip_url(), place).content) as clipped:
        values, counts = numpy.unique(clipped.read(1), return_counts=True)

    assert stats["pixels"] == clipped.width * clipped.height
    assert {row["value"]: row["pixels"] for row in stats["classes"]} == dict(
        zip(values.tolist(), counts.tolist(), strict=True)
    )


def test_a_clip_needs_a_place(as_viewer, landcover):
    response = as_viewer.get(clip_url())

    assert response.status_code == 400
    assert "bbox or an area" in str(response.json())


def test_a_clip_refuses_a_bbox_and_an_area_together(as_viewer, landcover):
    response = as_viewer.get(clip_url(), {"bbox": "35.0,33.0,35.5,33.5", "area": TRIANGLE})

    assert response.status_code == 400


def test_a_clip_above_the_cap_is_a_400_that_gives_both_numbers(as_viewer, landcover, settings):
    settings.RASTER_CLIP_MAX_BYTES = 1_024

    response = as_viewer.get(clip_url(), {"bbox": "35.0,33.0,35.5,33.5"})

    assert response.status_code == 400
    assert response.json() == {
        "bbox": [
            "This place is too large to clip: it covers 2,500 pixels, 2.4 KB "
            "uncompressed, and a clip may hold at most 1.0 KB. Ask for a smaller place."
        ]
    }


def test_a_clip_that_misses_the_raster_is_a_400(as_viewer, landcover):
    response = as_viewer.get(clip_url(), {"area": "POLYGON((2 48, 3 48, 3 49, 2 48))"})

    assert response.status_code == 400
    assert response.json() == {"area": ["This place does not overlap the raster."]}


def test_a_clip_of_anything_but_an_active_raster_is_404(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "raster_source", lambda asset_id: None)

    assert as_viewer.get(clip_url(), {"bbox": "35.0,33.0,35.25,33.5"}).status_code == 404


def test_a_clip_from_an_unreachable_lake_is_503(as_viewer, landcover, monkeypatch):
    def unreachable(*args, **kwargs):
        raise raster.RasterUnavailable("RasterioIOError")

    monkeypatch.setattr(raster, "clip", unreachable)

    assert as_viewer.get(clip_url(), {"bbox": "35.0,33.0,35.25,33.5"}).status_code == 503


def test_a_clip_of_an_unreadable_raster_is_502(as_viewer, landcover, monkeypatch):
    def unreadable(*args, **kwargs):
        raise raster.RasterReadError("RasterioIOError")

    monkeypatch.setattr(raster, "clip", unreadable)

    assert as_viewer.get(clip_url(), {"bbox": "35.0,33.0,35.25,33.5"}).status_code == 502


def test_a_non_ascii_asset_name_still_names_the_download(as_viewer, monkeypatch, tmp_path):
    path = write_classified(tmp_path / "landcover.tif")
    monkeypatch.setattr(
        kb, "raster_source", lambda asset_id: {"source_uri": path, "name": "غطاء_2023"}
    )

    response = as_viewer.get(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"})

    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment; filename*=utf-8''")


# --- the review of 2026-11-10 (docs/adr/029) -----------------------------------


@pytest.fixture
def utm(monkeypatch, tmp_path):
    """A raster in UTM zone 37N, as the land-cover rasters are (see `rasters.py`)."""
    path = write_utm(tmp_path / "utm.tif")
    monkeypatch.setattr(kb, "raster_source", lambda asset_id: {"source_uri": path, "name": "utm"})
    return path


@pytest.mark.parametrize(
    "place",
    [
        {"bbox": "-180,-85,180,85"},
        {"bbox": "-52,0,80,60"},
        {"bbox": "30,0,131,40"},
        {"area": "POLYGON((-52 0, 131 0, 131 60, -52 60, -52 0))"},
    ],
)
def test_a_zoomed_out_view_over_a_projected_raster_is_measured(as_viewer, utm, place):
    """It was a 502, or a false "no pixels": the view's corners are outside UTM's reach."""
    response = as_viewer.get(stats_url(), place)

    assert response.status_code == 200
    assert response.json()["pixels"] == 60 * 40


def test_a_zoomed_out_view_over_a_projected_raster_is_clipped(as_viewer, utm):
    response = as_viewer.get(clip_url(), {"bbox": "-52,0,80,60"})

    assert response.status_code == 200
    with opened(response.content) as clipped:
        assert (clipped.width, clipped.height) == (60, 40)


def test_classes_beyond_the_list_come_back_as_one_sum(as_viewer, monkeypatch, tmp_path):
    path = write_many_classes(tmp_path / "many.tif", values=300)
    monkeypatch.setattr(kb, "raster_source", lambda asset_id: {"source_uri": path, "name": "many"})

    body = as_viewer.get(stats_url()).json()

    assert len(body["classes"]) == 256
    assert body["other_classes"]["values"] == 44
    assert body["other_classes"]["pixels"] == 88
    assert sum(row["share"] for row in body["classes"]) + body["other_classes"][
        "share"
    ] == pytest.approx(1.0)


def test_the_clip_cap_is_in_bytes_and_counts_the_bands(as_viewer, imagery, settings):
    """50 x 50 pixels of three byte bands: 7,500 bytes."""
    settings.RASTER_CLIP_MAX_BYTES = 4_000
    whole = {"bbox": "35.0,33.7,35.1,33.85"}

    refused = as_viewer.get(clip_url(), whole)

    assert refused.status_code == 400
    assert refused.json() == {
        "bbox": [
            "This place is too large to clip: it covers 2,500 pixels, 7.3 KB "
            "uncompressed, and a clip may hold at most 3.9 KB. Ask for a smaller place."
        ]
    }
    settings.RASTER_CLIP_MAX_BYTES = 7_500
    assert as_viewer.get(clip_url(), whole).status_code == 200


def test_a_bug_in_the_reader_is_a_500_not_a_502(as_viewer, landcover, monkeypatch):
    """Only a failed read is the lake's fault."""

    def broken(*args, **kwargs):
        raise KeyError("a bug")

    monkeypatch.setattr(raster, "_stats", broken)
    as_viewer.raise_request_exception = False

    assert as_viewer.get(stats_url()).status_code == 500


# --- HEAD, caching, and a clip the portal could not write ------------------------


def test_a_head_request_builds_no_clip(as_viewer, landcover, monkeypatch):
    """Django answers HEAD by running GET: a whole clip made to be thrown away."""

    def built(*args, **kwargs):
        raise AssertionError("a clip was built for a HEAD request")

    monkeypatch.setattr(raster, "clip", built)

    response = as_viewer.head(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"})

    assert response.status_code == 200
    assert response.content == b""
    assert response["Content-Type"] == "image/tiff"
    assert response["Content-Disposition"] == 'attachment; filename="lulc_2023_clip.tif"'
    # The file's length is not known without making it: this is the empty
    # body's, written by Django.
    assert response["Content-Length"] == "0"


def test_a_head_request_answers_as_the_get_would(as_viewer, landcover, settings):
    get = as_viewer.get(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"})
    head = as_viewer.head(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"})
    assert head["ETag"] == get["ETag"]
    assert head["Cache-Control"] == get["Cache-Control"]

    assert as_viewer.head(clip_url(), {"bbox": "40.0,33.2,41.0,33.4"}).status_code == 400
    assert as_viewer.head(clip_url()).status_code == 400
    settings.RASTER_CLIP_MAX_BYTES = 100
    assert as_viewer.head(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"}).status_code == 400


def test_a_clip_is_kept_by_the_browser_and_asked_about_before_reuse(as_viewer, landcover):
    """As the document PDF is: an ETag, and `private, no-cache`."""
    response = as_viewer.get(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"})

    assert response["Cache-Control"] == "private, no-cache"
    assert response["ETag"].startswith('W/"')


def test_a_clip_the_browser_still_holds_is_a_304_with_no_read(as_viewer, landcover, monkeypatch):
    params = {"bbox": "35.2,33.2,35.6,33.4"}
    etag = as_viewer.get(clip_url(), params)["ETag"]

    def read(*args, **kwargs):
        raise AssertionError("the raster was read to answer a revalidation")

    monkeypatch.setattr(raster, "clip", read)
    monkeypatch.setattr(raster, "clip_size", read)

    response = as_viewer.get(clip_url(), params, HTTP_IF_NONE_MATCH=etag)

    assert response.status_code == 304
    assert response.content == b""
    assert response["ETag"] == etag


def test_another_place_or_another_raster_is_another_etag(as_viewer, landcover):
    one = as_viewer.get(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"})["ETag"]
    other_place = as_viewer.get(clip_url(), {"bbox": "35.2,33.2,35.6,33.5"})["ETag"]
    other_raster = as_viewer.get(clip_url(uuid.uuid4()), {"bbox": "35.2,33.2,35.6,33.4"})["ETag"]

    assert len({one, other_place, other_raster}) == 3


def test_a_drawn_area_and_its_envelope_are_one_clip(as_viewer, landcover):
    """A clip is the box, so the two requests get one file and one ETag."""
    by_area = as_viewer.get(clip_url(), {"area": TRIANGLE})
    by_box = as_viewer.get(clip_url(), {"bbox": "35.0,33.0,35.5,33.5"})

    assert by_area["ETag"] == by_box["ETag"]
    assert by_area.content == by_box.content


def test_a_raster_that_is_gone_is_a_404_even_with_a_matching_etag(
    as_viewer, landcover, monkeypatch
):
    params = {"bbox": "35.2,33.2,35.6,33.4"}
    etag = as_viewer.get(clip_url(), params)["ETag"]
    monkeypatch.setattr(kb, "raster_source", lambda asset_id: None)

    assert as_viewer.get(clip_url(), params, HTTP_IF_NONE_MATCH=etag).status_code == 404


def test_a_clip_the_portal_could_not_write_is_a_503_that_does_not_blame_the_lake(
    as_viewer, landcover, monkeypatch
):
    def not_written(*args, **kwargs):
        raise raster.ClipNotWritten("OSError")

    monkeypatch.setattr(raster, "clip", not_written)

    response = as_viewer.get(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"})

    assert response.status_code == 503
    assert response.json() == {"detail": "The portal could not write the clip. Try again later."}


def test_both_endpoints_give_the_reader_the_configured_time_limit(
    as_viewer, landcover, monkeypatch, settings
):
    settings.RASTER_READ_TIMEOUT_SECONDS = 12.5
    seen = {}
    real_stats, real_clip = raster.read_stats, raster.clip

    def stats(*args, **kwargs):
        seen["stats"] = kwargs["max_seconds"]
        return real_stats(*args, **kwargs)

    def clip(*args, **kwargs):
        seen["clip"] = kwargs["max_seconds"]
        return real_clip(*args, **kwargs)

    monkeypatch.setattr(raster, "read_stats", stats)
    monkeypatch.setattr(raster, "clip", clip)

    as_viewer.get(stats_url(), {"bbox": "35.2,33.2,35.6,33.4"})
    as_viewer.get(clip_url(), {"bbox": "35.2,33.2,35.6,33.4"})

    assert seen == {"stats": 12.5, "clip": 12.5}


# --- a place with no size --------------------------------------------------------


def test_a_point_on_a_pixel_edge_is_on_the_raster(as_viewer, landcover):
    """It answered "no pixels" and "does not overlap", though it is inside."""
    point = {"bbox": "35.2,33.1,35.2,33.1"}

    assert as_viewer.get(stats_url(), point).json()["pixels"] == 1
    clip = as_viewer.get(clip_url(), point)
    assert clip.status_code == 200
    with opened(clip.content) as clipped:
        assert (clipped.width, clipped.height) == (1, 1)


# --- a raster no place can be put on ---------------------------------------------


@pytest.fixture
def lon360(monkeypatch, tmp_path):
    """A whole-world grid with longitudes from 0 to 360, every pixel 5."""
    import numpy

    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    path = str(tmp_path / "secret-bucket-path.tif")
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
    monkeypatch.setattr(kb, "raster_source", lambda asset_id: {"source_uri": path, "name": "sst"})
    return path


def test_a_raster_no_place_can_be_put_on_is_a_422_that_says_so(as_viewer, lon360):
    """It was a 502 "The data lake returned an error": the lake and the file were fine."""
    place = {"bbox": "10.0,30.0,30.0,50.0"}

    stats = as_viewer.get(stats_url(), place)
    clip = as_viewer.get(clip_url(), place)
    head = as_viewer.head(clip_url(), place)

    assert stats.status_code == clip.status_code == head.status_code == 422
    for response in (stats, clip):
        detail = response.json()["detail"]
        assert "cannot be measured or clipped over a place" in detail
        assert "lake" not in detail
        assert "secret-bucket-path" not in response.content.decode()


def test_a_raster_no_place_can_be_put_on_is_still_measured_whole(as_viewer, lon360):
    response = as_viewer.get(stats_url())

    assert response.status_code == 200
    assert response.json()["pixels"] == 360 * 180


def test_the_time_limit_setting_reaches_the_reader(as_viewer, landcover, settings, monkeypatch):
    seen = {}
    real = raster.read_stats

    def spied(uri, **kwargs):
        seen.update(kwargs)
        return real(uri, **kwargs)

    settings.RASTER_READ_TIMEOUT_SECONDS = 7.0
    monkeypatch.setattr(raster, "read_stats", spied)

    assert as_viewer.get(stats_url()).status_code == 200
    assert seen["max_seconds"] == 7.0


# --- the held copy, however the client names it ---------------------------------


@pytest.mark.parametrize("spelling", ["weak", "strong", "listed", "any"])
def test_a_held_clip_is_matched_weakly(as_viewer, landcover, spelling):
    """`"x"` and `W/"x"` name the same copy when asking "is mine still good"."""
    params = {"bbox": "35.2,33.2,35.6,33.4"}
    etag = as_viewer.get(clip_url(), params)["ETag"]
    assert etag.startswith('W/"')
    sent = {
        "weak": etag,
        "strong": etag.removeprefix("W/"),
        "listed": f'"something-else", {etag.removeprefix("W/")}',
        "any": "*",
    }[spelling]

    response = as_viewer.get(clip_url(), params, HTTP_IF_NONE_MATCH=sent)

    assert response.status_code == 304


def test_another_etag_is_not_a_match(as_viewer, landcover):
    params = {"bbox": "35.2,33.2,35.6,33.4"}

    response = as_viewer.get(clip_url(), params, HTTP_IF_NONE_MATCH='"not-this-one"')

    assert response.status_code == 200
