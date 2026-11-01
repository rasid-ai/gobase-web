"""Short-lived lake credentials that can read one raster, and nothing else.

The only module that imports boto3, and only for one call: STS `AssumeRole`
(the Security Token Service, which turns a user's long-lived keys into
temporary ones). It exists for desktop clients. ArcGIS Pro cannot open a COG
from a URL; it reads one through a cloud storage connection that signs its
own range requests to the bucket. So the portal hands the add-in what that
connection needs, never the pixels (docs/adr/022).

The credentials come from a dedicated lake user, not from the portal's own
`LAKE_S3_*` keys. That user may only read the raster folder, and each call
narrows it further with a session policy naming one object: the lake grants
the overlap of the two. A leaked set reads one file until it expires.
"""

import json
import logging
import threading
from urllib.parse import quote, urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, HTTPClientError
from botocore.exceptions import ConnectionError as BotoConnectionError
from django.conf import settings

logger = logging.getLogger(__name__)


class IssuerUnavailable(Exception):
    """The lake could not be reached, or refused the issuing user's keys."""


class IssueFailed(Exception):
    """The lake answered the request for credentials with an error."""


# boto3 needs a role ARN, and AWS would assume that role. RustFS and MinIO
# ignore it: the credentials carry the calling user's own policy, which is
# the point. It only has to be well-formed.
_ROLE_ARN = "arn:aws:iam::000000000000:role/portal-raster-reader"

# What STS allows for DurationSeconds. RustFS clamps to the same range.
_MIN_DURATION, _MAX_DURATION = 900, 43200

# An inline session policy may be at most 2,048 bytes.
_MAX_POLICY_BYTES = 2048

# Errors that mean the lake refused the issuer itself: the keys or the user
# are wrong, which is a configuration fault, not a fault with the raster.
_REFUSED = {
    "AccessDenied",
    "InvalidAccessKeyId",
    "InvalidClientTokenId",
    "SignatureDoesNotMatch",
    "ExpiredToken",
}

# The region the credentials are signed for. RustFS answers to its own,
# `us-east-1` unless RUSTFS_REGION says otherwise, and clients insist on one.
DEFAULT_REGION = "us-east-1"

# One client per worker process, built on first use. A boto3 client is safe to
# share between threads once built; building one is not, hence the lock.
_client = None
_lock = threading.Lock()


def configured() -> bool:
    """Whether this portal hands out raster credentials at all.

    False is a supported state, not a failure: with no public address for the
    lake, or no issuing user, the endpoint answers 503 and the portal runs
    without raster access, as it does without an Esri key (docs/adr/011).
    """
    endpoint = urlsplit(settings.LAKE_PUBLIC_ENDPOINT)
    return bool(
        endpoint.scheme in {"http", "https"}
        and endpoint.netloc
        and settings.LAKE_S3_ENDPOINT
        and settings.LAKE_STS_ACCESS_KEY
        and settings.LAKE_STS_SECRET_KEY
    )


def region() -> str:
    return settings.LAKE_S3_REGION or DEFAULT_REGION


def public_endpoint() -> str:
    """The lake as a desktop client reaches it: scheme, host and port, no slash."""
    return settings.LAKE_PUBLIC_ENDPOINT.rstrip("/")


def split_s3_uri(uri: str) -> tuple[str, str]:
    """`s3://bucket/key` as (bucket, key). Raises ValueError for anything else."""
    parts = urlsplit(uri or "")
    key = parts.path.lstrip("/")
    if parts.scheme != "s3" or not parts.netloc or not key:
        raise ValueError("not an s3:// object URI")
    return parts.netloc, key


def object_url(bucket: str, key: str) -> str:
    """The object's address on the public endpoint, path-style.

    Path-style, `endpoint/bucket/key`, because RustFS serves it that way
    (`LAKE_S3_URL_STYLE=path`). Not a presigned link: reading it needs the
    credentials, signed by the client.
    """
    return f"{public_endpoint()}/{quote(bucket)}/{quote(key, safe='/')}"


def session_policy(bucket: str, key: str) -> str:
    """The inline policy for one set of credentials: this object, and its folder's names.

    `GetObject` on the one object is what reading it takes. Listing its folder
    is there because ArcGIS opens a raster the way GDAL does, by listing the
    folder to look for side files (`.aux.xml`, `.ovr`) first; that shows
    file names the catalog already lists to every signed-in user.
    """
    folder = key.rpartition("/")[0]
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/{key}"],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
                "Condition": {"StringLike": {"s3:prefix": [f"{folder}/*" if folder else "*"]}},
            },
        ],
    }
    text = json.dumps(policy, separators=(",", ":"))
    if len(text.encode()) > _MAX_POLICY_BYTES:
        raise ValueError("the session policy is over the lake's 2,048-byte limit")
    return text


def duration_seconds() -> int:
    return max(_MIN_DURATION, min(_MAX_DURATION, settings.LAKE_STS_DURATION_SECONDS))


def issue(bucket: str, key: str, session_name: str) -> dict:
    """Ask the lake for credentials that read `key` in `bucket`, for a while.

    Returns `access_key_id`, `secret_access_key`, `session_token` and
    `expires_at` (an aware datetime). `session_name` is recorded by the lake
    against the credentials, so a set can be traced to the user it went to.

    The request goes to the lake's own address (`LAKE_S3_ENDPOINT`), not the
    public one: the credentials are not bound to a host name, only the
    client's signature on each request is.
    """
    try:
        policy = session_policy(bucket, key)
    except ValueError as exc:
        raise IssueFailed(str(exc)) from exc

    try:
        answer = _sts_client().assume_role(
            RoleArn=_ROLE_ARN,
            RoleSessionName=session_name,
            DurationSeconds=duration_seconds(),
            Policy=policy,
        )
    except ClientError as exc:
        # Reported by code only. The message can quote the request.
        code = exc.response.get("Error", {}).get("Code", "")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        logger.warning("The lake refused raster credentials: %s (HTTP %s)", code, status)
        if code in _REFUSED or status in {401, 403}:
            raise IssuerUnavailable(code) from exc
        raise IssueFailed(code) from exc
    except (BotoConnectionError, HTTPClientError) as exc:
        # Refused, unresolved, timed out, or cut off mid-answer.
        logger.warning("The lake's STS could not be reached: %s", type(exc).__name__)
        raise IssuerUnavailable(type(exc).__name__) from exc
    except BotoCoreError as exc:
        logger.warning("Asking the lake for raster credentials failed: %s", type(exc).__name__)
        raise IssueFailed(type(exc).__name__) from exc

    credentials = answer["Credentials"]
    return {
        "access_key_id": credentials["AccessKeyId"],
        "secret_access_key": credentials["SecretAccessKey"],
        "session_token": credentials["SessionToken"],
        "expires_at": credentials["Expiration"],
    }


def _sts_client():
    global _client
    with _lock:
        if _client is None:
            scheme = "https" if settings.LAKE_S3_USE_SSL else "http"
            _client = boto3.client(
                "sts",
                endpoint_url=f"{scheme}://{settings.LAKE_S3_ENDPOINT}",
                region_name=region(),
                aws_access_key_id=settings.LAKE_STS_ACCESS_KEY,
                aws_secret_access_key=settings.LAKE_STS_SECRET_KEY,
                # One try, bounded: a dead lake must not hold a portal worker.
                config=Config(
                    connect_timeout=settings.LAKE_STS_TIMEOUT_SECONDS,
                    read_timeout=settings.LAKE_STS_TIMEOUT_SECONDS,
                    retries={"total_max_attempts": 1},
                ),
            )
        return _client


def reset() -> None:
    """Drop the client, so the next call builds one from the current settings."""
    global _client
    with _lock:
        _client = None
