"""Small GeoTIFFs for the raster tests, written with rasterio into a temporary directory.

The reader opens a local path exactly as it opens one in the lake, so these
exercise it for real (docs/adr/029). `rasterio` is imported inside each
helper, after `raster._rasterio()` has dropped any inherited GDAL variables:
importing it at module level would read them first.
"""

import numpy

from apps.map import raster

# What the data platform writes on a land-cover raster: the legend as JSON text.
LEGEND = '{"1": "water", "7": "built_area"}'


def write_classified(path) -> str:
    """A land-cover style raster: one uint8 band, a legend, a palette, nodata 0.

    100 x 100 pixels of 0.01 degrees: longitude 35 to 36, latitude 33 to 34.
    The left half is class 7, the right half class 1, and the top ten rows
    hold no data. Several tags name a lake path, which a clip must not carry.
    """
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    data = numpy.empty((100, 100), dtype="uint8")
    data[:, :50] = 7
    data[:, 50:] = 1
    data[:10, :] = 0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=100,
        height=100,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(35.0, 34.0, 0.01, 0.01),
        nodata=0,
    ) as target:
        target.write(data, 1)
        target.update_tags(
            classes=LEGEND,
            year="2023",
            # Not on the list of tags a clip carries.
            origin="s3://secret-bucket/raw/landcover.tif",
            producer="someone",
            # On the list, but each value names a place in the lake.
            source="https://lake.internal:9000/secret-bucket/raw/landcover.tif",
            collection="secret-bucket/landcover/y.tif",
            description="src=/home/secret-bucket/y.tif",
        )
        target.write_colormap(1, {1: (0, 0, 255, 255), 7: (255, 0, 0, 255)})
        target.set_band_description(1, "land cover class")
    return str(path)


def write_imagery(path) -> str:
    """A three-band image in Web Mercator, as the city satellite rasters are bands of bytes.

    50 x 50 pixels of 100 metres from x 3,900,000, y 4,000,000 (about 35.03 E,
    33.80 N). Band 1 is 10 everywhere, band 2 is 20, band 3 is 30. No nodata.
    """
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=50,
        height=50,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(3_900_000, 4_000_000, 100, 100),
    ) as target:
        for band in (1, 2, 3):
            target.write(numpy.full((50, 50), band * 10, dtype="uint8"), band)
    return str(path)


def write_floats(path, *, crs="EPSG:4326", legend: str | None = None) -> str:
    """One float32 band, 10 x 10 pixels of 0.1 degrees from 35 E, 34 N.

    Each value is its row number (0 at the top), and the first column is NaN.
    """
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    data = numpy.repeat(numpy.arange(10, dtype="float32")[:, None], 10, axis=1)
    data[:, 0] = numpy.nan
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(35.0, 34.0, 0.1, 0.1),
    ) as target:
        target.write(data, 1)
        if legend is not None:
            target.update_tags(classes=legend)
    return str(path)


def mercator_box_in_degrees(left, bottom, right, top) -> tuple[float, float, float, float]:
    """A Web Mercator box as the lon/lat bbox a caller would send."""
    raster._rasterio()
    from rasterio.warp import transform_bounds

    return transform_bounds("EPSG:3857", "EPSG:4326", left, bottom, right, top)


def write_utm(path) -> str:
    """A projected raster, as the land-cover rasters are: UTM zone 37N (EPSG:32637).

    60 x 40 pixels of 100 metres from x 700,000, y 3,800,000: about 35.2 E,
    34.3 N. Every pixel is 5. UTM is defined near its zone only, so a place
    far wider than the raster has corners the projection cannot take.
    """
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=60,
        height=40,
        count=1,
        dtype="uint8",
        crs="EPSG:32637",
        transform=from_origin(700_000, 3_800_000, 100, 100),
    ) as target:
        target.write(numpy.full((40, 60), 5, dtype="uint8"), 1)
    return str(path)


def write_tall(path) -> tuple[str, numpy.ndarray]:
    """Two bands of varied bytes, 300 x 700 pixels: taller than two blocks of rows.

    0.001 degrees a pixel from 35 E, 34 N. Returns the path and the pixels.
    """
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    data = numpy.random.default_rng(7).integers(0, 255, size=(2, 700, 300), dtype="uint8")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=300,
        height=700,
        count=2,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(35.0, 34.0, 0.001, 0.001),
    ) as target:
        target.write(data)
    return str(path), data


def write_masked(path) -> str:
    """One byte band with no nodata value and a mask of its own, stored in the file.

    20 x 20 pixels of 0.01 degrees from 35 E, 34 N, every pixel 9. The left
    half is masked out.
    """
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    mask = numpy.full((20, 20), 255, dtype="uint8")
    mask[:, :10] = 0
    with (
        rasterio.Env(GDAL_TIFF_INTERNAL_MASK="YES"),
        rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=20,
            height=20,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(35.0, 34.0, 0.01, 0.01),
        ) as target,
    ):
        target.write(numpy.full((20, 20), 9, dtype="uint8"), 1)
        target.write_mask(mask)
    return str(path)


def write_with_alpha(path) -> str:
    """A grey band and an alpha band: 10 x 10 pixels of 0.1 degrees from 35 E, 34 N.

    The grey band is 100 everywhere. The alpha band is 255, and 0 in the top
    two rows: those pixels are transparent, so they hold no data.
    """
    rasterio = raster._rasterio()
    from rasterio.enums import ColorInterp
    from rasterio.transform import from_origin

    alpha = numpy.full((10, 10), 255, dtype="uint8")
    alpha[:2, :] = 0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=2,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(35.0, 34.0, 0.1, 0.1),
    ) as target:
        target.write(numpy.full((10, 10), 100, dtype="uint8"), 1)
        target.write(alpha, 2)
        target.colorinterp = [ColorInterp.gray, ColorInterp.alpha]
    return str(path)


def write_many_classes(path, values: int = 300) -> str:
    """A classified raster with more values than a class list holds.

    One uint16 band, `values` x 2 pixels: value v fills column v - 1, so
    every value has two pixels. The legend names value 1 only.
    """
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    data = numpy.repeat(numpy.arange(1, values + 1, dtype="uint16")[None, :], 2, axis=0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values,
        height=2,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(35.0, 34.0, 0.001, 0.001),
    ) as target:
        target.write(data, 1)
        target.update_tags(classes='{"1": "first"}')
    return str(path)


def write_tiny_floats(path) -> str:
    """One float32 band whose every value is 3e-9: small, and not zero."""
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(35.0, 34.0, 0.1, 0.1),
    ) as target:
        target.write(numpy.full((4, 4), 3e-9, dtype="float32"), 1)
    return str(path)


def write_across_180(path) -> str:
    """A projected raster that crosses the antimeridian: UTM zone 60N (EPSG:32660).

    300 x 200 pixels of 1 km from x 700,000, y 5,600,000: from about 179.7 E,
    across 180°, to about 176 W, near 49 N. Every pixel is 5. In lon/lat its
    west edge is at a larger longitude than its east edge.
    """
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=300,
        height=200,
        count=1,
        dtype="uint8",
        crs="EPSG:32660",
        transform=from_origin(700_000, 5_600_000, 1000, 1000),
    ) as target:
        target.write(numpy.full((200, 300), 5, dtype="uint8"), 1)
    return str(path)


def write_whole_world_mollweide(path) -> str:
    """The whole world in Mollweide: a raster whose extent has no lon/lat box.

    The corners of its rectangle lie outside the projected globe, so they
    have no longitude and latitude at all.
    """
    rasterio = raster._rasterio()
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=360,
        height=180,
        count=1,
        dtype="uint8",
        crs="ESRI:54009",
        transform=from_origin(-18040095.7, 9020047.85, 100222.75, 100222.75),
    ) as target:
        target.write(numpy.full((180, 360), 5, dtype="uint8"), 1)
    return str(path)
