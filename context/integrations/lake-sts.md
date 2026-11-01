# The lake's STS — short-lived credentials for desktop clients

STS (Security Token Service) is the S3 API that turns a user's long-lived
keys into temporary ones. The portal uses one call of it, `AssumeRole`, to
give the ArcGIS Pro add-in credentials that read one raster for an hour
(docs/adr/022). The portal never reads the raster itself.

Checked on 2026-11-01 against RustFS 1.0.4 in a local container, with boto3
1.43.114 and GDAL 3.6.

## What talks to it

`backend/apps/map/sts.py`, and nothing else. It is the only module that
imports `boto3`. `apps/map/raster_views.py` serves the result as
`GET /api/map/assets/{asset_id}/raster-access`.

## Configuration

| setting | value |
|---|---|
| `LAKE_PUBLIC_ENDPOINT` | the lake as a desktop reaches it, scheme included: `http://<VPS Tailscale IP>:9000` today, an `https://` hostname later |
| `LAKE_STS_ACCESS_KEY` | the issuer's user name, `portal-raster-issuer` |
| `LAKE_STS_SECRET_KEY` | the issuer's password |
| `LAKE_STS_DURATION_SECONDS` | 3600; clamped to 900–43200 |
| `LAKE_STS_TIMEOUT_SECONDS` | 5 |

The STS call goes to `LAKE_S3_ENDPOINT`, with `LAKE_S3_USE_SSL`, where the
portal already reaches the lake. It is signed for `LAKE_S3_REGION`, or
`us-east-1` when that is blank, which is RustFS's default region. The same
region goes to the client.

With any of the first three blank, or `LAKE_S3_ENDPOINT` blank, the endpoint
answers 503 and the portal runs without raster access.

## Setting up the issuer, once per lake

The issuer must be a **regular RustFS user**, whose name and password are its
keys. Keys made on the Console's Access Keys page are service accounts, and
RustFS refuses `AssumeRole` from them. The user needs at least one policy and
no MFA.

The policy, `portal-raster-read`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::geobase-silver/raster/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::geobase-silver"],
      "Condition": {"StringLike": {"s3:prefix": ["raster/*"]}}
    }
  ]
}
```

With `mc` (MinIO's client; RustFS accepts its admin calls), as the root user:

```sh
mc alias set lake http://127.0.0.1:9000 <root user> <root password>
mc admin policy create lake portal-raster-read portal-raster-read.json
mc admin user add lake portal-raster-issuer <new password>
mc admin policy attach lake portal-raster-read --user portal-raster-issuer
```

The RustFS Console does the same under Identity → Policies and Identity →
Users. The `minio/minio` image ships `mc` if it is not installed.

Then set `LAKE_STS_ACCESS_KEY=portal-raster-issuer`, the password as
`LAKE_STS_SECRET_KEY`, and `LAKE_PUBLIC_ENDPOINT`, and restart the backend.

## The call

```python
boto3.client("sts", endpoint_url=..., region_name=...).assume_role(
    RoleArn="arn:aws:iam::000000000000:role/portal-raster-reader",
    RoleSessionName="portal-user-<user id>",
    DurationSeconds=3600,
    Policy=<session policy>,
)
```

- **`RoleArn` is a placeholder.** boto3 requires one and RustFS ignores it:
  the credentials carry the calling user's own policy. AWS would assume the
  role, so moving the lake to AWS needs a real one.
- **The session policy** names the one object for `GetObject` and allows
  listing its folder (`s3:prefix` `raster/<dataset>/*`). RustFS grants the
  overlap with the issuer's policy. It must be 2,048 bytes or less; a raster
  key would have to be over 1,500 characters to break that.
- **RustFS's STS is `POST /`** on the S3 port, form-encoded. If it is ever
  put behind nginx, that request must pass through unchanged.

What the credentials could do, measured against the local RustFS:

| request | answer |
|---|---|
| ranged GET of the object | 206 |
| HEAD of the object | 200 |
| list the object's folder | 200 |
| GET another raster | 403 |
| GET outside `raster/` | 403 |
| list another folder, or the bucket root | 403 |
| PUT | 403 |

GDAL opened the COG with them through `/vsis3/` (`AWS_SESSION_TOKEN`,
`AWS_S3_ENDPOINT`, `AWS_HTTPS=NO`, `AWS_VIRTUAL_HOSTING=FALSE`). Since RustFS
1.0.1 a request whose `x-amz-security-token` header is not signed is
refused; GDAL signs it.

## Failures

- The lake unreachable, timed out, or refusing the issuer's keys
  (`AccessDenied`, `InvalidAccessKeyId`, `SignatureDoesNotMatch`, any 401 or
  403) → **503**. The configuration or the lake is the problem.
- Any other STS error → **502**.
- A raster whose `source_uri` is not an `s3://` URI → **502**, logged as an
  error: the catalog is wrong.

Errors are logged by code only. An STS error message can quote the request,
which carries the session policy, and the answer carries the secret.

## Two things to know

- **Changing RustFS's root secret ends every live set.** RustFS signs session
  tokens with it. Upstream knows and will not change it.
- **An expired set is refused with `ExpiredToken`** (RustFS 1.0.2 and later).
  The add-in renews ten minutes before `expires_at`.
