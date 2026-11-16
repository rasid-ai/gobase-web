"""The Catalog API: browsing everything the knowledge base holds."""

import logging
import re

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotModified
from django.utils.http import content_disposition_header, parse_etags
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.map import lake
from apps.map.http import LakeFailed, LakeUnreachable, cacheable

from . import chunks, godoc, kb, pages, passages
from .serializers import (
    CHUNK_ID_PATTERN,
    AssetListQuerySerializer,
    AssetListSerializer,
    DatasetListQuerySerializer,
    DatasetListSerializer,
    DocumentPageQuerySerializer,
    DocumentPassageSerializer,
    PassagesQuerySerializer,
    PassagesSerializer,
    SimilarAssetsQuerySerializer,
    SimilarAssetsSerializer,
)

logger = logging.getLogger(__name__)


class AssetListView(APIView):
    """One page of the catalog, filtered and sorted.

    Both pages browse through here. The Assets page narrows it to a searched
    place, and the map's panel to a clicked point or a drawn area — one
    question with three geometries, and one answer to it, so the search, the
    datasets and the counts cannot differ between the two (docs/adr/016).
    What the place is compared with is the caller's to say: each asset's own
    coverage for the map, its dataset's for the Assets page (docs/adr/019).
    """

    @extend_schema(
        parameters=[AssetListQuerySerializer],
        responses={
            200: AssetListSerializer,
            400: OpenApiResponse(
                description="A filter that cannot be read, half a point, or more than one place."
            ),
        },
        operation_id="catalog_asset_list",
        summary="Browse the asset catalog",
        tags=["catalog"],
    )
    def get(self, request):
        query = AssetListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data

        page = kb.asset_list(
            # An absent filter and an empty one mean the same thing here: no
            # restriction. `q=` is what the search box sends once it is cleared.
            q=filters.get("q") or None,
            data_types=filters.get("data_type") or None,
            dataset=filters.get("dataset") or None,
            **query.place(),
            ingested_after=filters.get("ingested_after"),
            ingested_before=filters.get("ingested_before"),
            sort=filters["sort"],
            limit=filters["limit"],
            offset=filters["offset"],
        )
        return Response(AssetListSerializer(page).data)


class DatasetListView(APIView):
    """The datasets holding matching assets, and how many of each type.

    The first step of browsing by dataset, on both pages: pick one here, then
    list its assets with `dataset=` on the asset list, sending the same place,
    coverage and window so the count shown here is the count found there.
    """

    @extend_schema(
        parameters=[DatasetListQuerySerializer],
        responses={
            200: DatasetListSerializer,
            400: OpenApiResponse(
                description="A filter that cannot be read, half a point, or more than one place."
            ),
        },
        operation_id="catalog_dataset_list",
        summary="Datasets in the catalog",
        tags=["catalog"],
    )
    def get(self, request):
        query = DatasetListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data

        datasets = kb.dataset_list(
            q=filters.get("q") or None,
            **query.place(),
            ingested_after=filters.get("ingested_after"),
            ingested_before=filters.get("ingested_before"),
        )
        return Response(DatasetListSerializer({"results": datasets}).data)


class DocumentPdfView(APIView):
    """The PDF behind one document, read from bronze.

    A document's `source_uri` is the parsed bundle in silver; the file a person
    wants to open is the PDF it was parsed from, which the data platform leaves
    in bronze and records in `doc_documents.pdf_uri`. The bytes come through
    here rather than through a link into the bucket because the browser never
    talks to the lake (docs/adr/011, docs/adr/027).

    Served whole and uncompressed — a PDF is already compressed — with a strong
    ETag: `content_hash` is the PDF's own sha256, so a revalidation is a
    catalog lookup and never a lake read. The client opens it in a new tab, so
    the body is `inline` and carries the file's name.
    """

    @extend_schema(
        responses={
            (200, "application/pdf"): OpenApiTypes.BINARY,
            304: OpenApiResponse(
                description=(
                    "The ETag sent in If-None-Match still matches; use the copy already held."
                )
            ),
            404: OpenApiResponse(
                description=(
                    "No active document with that id, or one whose PDF the catalog does not record."
                )
            ),
            502: OpenApiResponse(description="The PDF could not be read."),
            503: OpenApiResponse(description="The lake could not be reached."),
        },
        operation_id="catalog_document_pdf",
        summary="A document's PDF",
        tags=["catalog"],
    )
    def get(self, request, asset_id):
        # The bronze URI is resolved here and never leaves the server.
        document = kb.document_pdf(asset_id)
        if document is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Checked after the catalog, not before: a superseded document must
        # answer 404, not tell the browser its old copy is still good.
        etag = f'"{document["content_hash"]}"'
        held = parse_etags(request.headers.get("If-None-Match", ""))
        if etag in held or "*" in held:
            return cacheable(HttpResponseNotModified(), etag)

        try:
            data = lake.read_blob(document["pdf_uri"])
        except lake.LakeUnavailable as exc:
            raise LakeUnreachable() from exc
        except lake.LakeReadError as exc:
            raise LakeFailed() from exc

        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = content_disposition_header(False, document["filename"])
        response["Content-Length"] = str(len(data))
        return cacheable(response, etag)


class SemanticSearchUnreachable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Semantic search is unavailable"


class SemanticSearchFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Semantic search returned an error"


class SimilarAssetsView(APIView):
    """The assets whose card is closest in meaning to a question.

    The map's Semantic mode (docs/adr/018). The question is embedded by the
    data platform's document service — the model that embedded the cards —
    and the catalog ranks its cards by cosine similarity. Cards only, in
    Postgres: the shallow search, never the chunk index. Meaning only: no
    place narrows it yet.
    """

    @extend_schema(
        parameters=[SimilarAssetsQuerySerializer],
        responses={
            200: SimilarAssetsSerializer,
            400: OpenApiResponse(description="Missing or empty text, or a limit out of range."),
            502: OpenApiResponse(description="The embedding service refused the question."),
            503: OpenApiResponse(
                description="The embedding service is unreachable, or no URL is set for it."
            ),
        },
        operation_id="catalog_similar_assets",
        summary="Assets matching a question",
        tags=["catalog"],
    )
    def get(self, request):
        query = SimilarAssetsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        asked = query.validated_data

        # Checked before the call, not after it: with no URL every request
        # would spend a round trip to be told the same thing. The detail
        # differs from the unreachable one so an operator can tell the two
        # apart in the log, while the caller sees one message.
        if not settings.GODOC_URL:
            logger.warning("Semantic search asked for, but no GoDoc URL is configured")
            raise SemanticSearchUnreachable("Semantic search is not configured")

        model, vector = _embed(asked["q"])
        results = kb.similar_assets(vector, model, asked["limit"])
        return Response(SimilarAssetsSerializer({"embedder": model, "results": results}).data)


def _embed(text: str) -> tuple[str, list[float]]:
    """Embed the question, turning the service's two failure modes into HTTP ones.

    Unreachable is 503 (try again later); a refused request is 502 (it is up
    and saying no). Neither is a 500: the portal itself is fine. The upstream
    message stays in the log, as with the geocoder (apps/places/views.py) —
    and the question itself never reaches the log at all.
    """
    try:
        return godoc.embed(text)
    except godoc.GoDocUnavailable as exc:
        logger.warning("GoDoc unreachable: %s", exc)
        raise SemanticSearchUnreachable() from exc
    except godoc.GoDocError as exc:
        logger.warning("GoDoc error: %s", exc)
        raise SemanticSearchFailed() from exc


class ChunkIndexUnreachable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The chunk index is unreachable"


class ChunkIndexFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The chunk index returned an error"


class PassagesView(APIView):
    """The documents whose passages best answer a question (docs/adr/020).

    The Assets page's Semantic search. The question is embedded by the data
    platform's document service, the catalog names the documents in scope —
    narrowed by place, window and dataset like any browse — and the chunk
    index ranks their passages. Deep, where `assets/similar` is shallow.
    """

    @extend_schema(
        parameters=[PassagesQuerySerializer],
        responses={
            200: PassagesSerializer,
            400: OpenApiResponse(
                description="Missing or empty text, a limit out of range, or a bad place."
            ),
            502: OpenApiResponse(
                description="The embedding service refused the question, or the index failed."
            ),
            503: OpenApiResponse(
                description=(
                    "The embedding service is unreachable or not configured, or the "
                    "index could not be reached."
                )
            ),
        },
        operation_id="catalog_passages",
        summary="Passages answering a question",
        tags=["catalog"],
    )
    def get(self, request):
        query = PassagesQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        asked = query.validated_data

        if not settings.GODOC_URL:
            logger.warning("Semantic search asked for, but no GoDoc URL is configured")
            raise SemanticSearchUnreachable("Semantic search is not configured")

        model, vector = _embed(asked["q"])
        try:
            results = passages.search(
                vector,
                model,
                limit=asked["limit"],
                per_document=asked["passages"],
                dataset=asked.get("dataset") or None,
                **query.place(),
                ingested_after=asked.get("ingested_after"),
                ingested_before=asked.get("ingested_before"),
                asset_ids=[str(one) for one in asked.get("asset_id") or []] or None,
            )
        except chunks.ChunkStoreUnavailable as exc:
            logger.warning("Chunk index unreachable: %s", exc)
            raise ChunkIndexUnreachable() from exc
        except chunks.ChunkStoreError as exc:
            logger.warning("Chunk index error: %s", exc)
            raise ChunkIndexFailed() from exc
        return Response(PassagesSerializer({"embedder": model, "results": results}).data)


_CHUNK_ID = re.compile(CHUNK_ID_PATTERN)


class DocumentPassageView(APIView):
    """One passage of a document, by its id: the text, its headings and its pages.

    What the Ask agent's `doc_read` tool calls to quote a passage exactly
    (docs/adr/024). Pages are counted from 1, as the passages endpoint reports
    them. The same read the page image does, without the image.
    """

    @extend_schema(
        responses={
            200: DocumentPassageSerializer,
            400: OpenApiResponse(description="A chunk id that is not one."),
            404: OpenApiResponse(
                description=(
                    "No active document with that id, a document with no passages "
                    "indexed, or a chunk that is not in it."
                )
            ),
            502: OpenApiResponse(description="The chunk index failed."),
            503: OpenApiResponse(description="The chunk index could not be reached."),
        },
        operation_id="catalog_document_passage",
        summary="One passage of a document, by its id",
        tags=["catalog"],
    )
    def get(self, request, asset_id, chunk_id):
        if not _CHUNK_ID.fullmatch(chunk_id):
            raise ValidationError({"chunk_id": ["This is not a chunk id."]})
        try:
            passage = passages.read(asset_id, chunk_id)
        except chunks.ChunkStoreUnavailable as exc:
            logger.warning("Chunk index unreachable: %s", exc)
            raise ChunkIndexUnreachable() from exc
        except chunks.ChunkStoreError as exc:
            logger.warning("Chunk index error: %s", exc)
            raise ChunkIndexFailed() from exc
        if passage is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(DocumentPassageSerializer(passage).data)


class DocumentPageView(APIView):
    """One page of a document's PDF as an image, a passage drawn on it (docs/adr/020).

    The page is counted from 1, as the passages endpoint reports it. With
    `chunk`, the passage's boxes are drawn; without, the plain page. Read from
    bronze through the lake, like the PDF itself, and rendered here: the browser
    never sees the bucket, and an `<img>` cannot carry a token anyway.

    The ETag is the PDF's hash, the chunk, the page and the renderer's version,
    so a revalidation is a catalog lookup and neither a lake read nor a render.
    """

    @extend_schema(
        parameters=[DocumentPageQuerySerializer],
        responses={
            (200, "image/png"): OpenApiTypes.BINARY,
            304: OpenApiResponse(
                description=(
                    "The ETag sent in If-None-Match still matches; use the copy already held."
                )
            ),
            400: OpenApiResponse(description="A chunk id that is not one."),
            404: OpenApiResponse(
                description=(
                    "No active document with that id or no PDF recorded for it, a page "
                    "it does not have, or a chunk that is not in it."
                )
            ),
            502: OpenApiResponse(description="The PDF could not be read or rendered."),
            503: OpenApiResponse(description="The lake or the chunk index could not be reached."),
        },
        operation_id="catalog_document_page",
        summary="A page of a document's PDF, with a passage marked",
        tags=["catalog"],
    )
    def get(self, request, asset_id, page):
        query = DocumentPageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        chunk_id = query.validated_data.get("chunk")

        document = kb.document_pdf(asset_id)
        if document is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if page < 1 or (document.get("pages") and page > document["pages"]):
            return Response(status=status.HTTP_404_NOT_FOUND)

        etag = f'"{document["content_hash"]}:{chunk_id or "-"}:{page}:r{pages.RENDER_VERSION}"'
        held = parse_etags(request.headers.get("If-None-Match", ""))
        if etag in held or "*" in held:
            return cacheable(HttpResponseNotModified(), etag)

        boxes = []
        if chunk_id:
            if not document.get("chunks_uri"):
                return Response(status=status.HTTP_404_NOT_FOUND)
            try:
                hit = chunks.chunk(document["chunks_uri"], asset_id, chunk_id)
            except chunks.ChunkStoreUnavailable as exc:
                logger.warning("Chunk index unreachable: %s", exc)
                raise ChunkIndexUnreachable() from exc
            except chunks.ChunkStoreError as exc:
                logger.warning("Chunk index error: %s", exc)
                raise ChunkIndexFailed() from exc
            if hit is None:
                return Response(status=status.HTTP_404_NOT_FOUND)
            # The index counts pages from 0; the URL from 1.
            boxes = [box["bbox"] for box in hit["bboxes"] if box["page"] == page - 1]

        try:
            data = lake.read_blob(document["pdf_uri"])
        except lake.LakeUnavailable as exc:
            raise LakeUnreachable() from exc
        except lake.LakeReadError as exc:
            raise LakeFailed() from exc

        try:
            png = pages.render(data, page - 1, boxes)
        except pages.PageUnreadable as exc:
            logger.warning("Page %s of document %s could not be rendered: %s", page, asset_id, exc)
            raise LakeFailed() from exc

        response = HttpResponse(png, content_type="image/png")
        response["Content-Length"] = str(len(png))
        return cacheable(response, etag)
