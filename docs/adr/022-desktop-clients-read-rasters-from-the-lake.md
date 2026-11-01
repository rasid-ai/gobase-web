# ADR-022: Desktop clients read rasters from the lake with short-lived credentials

**Status:** Accepted · 2026-11-01

## Context

The ArcGIS Pro add-in (docs/adr/021) lists the catalog's rasters but cannot
open them. The catalog's rasters are COGs (Cloud-Optimized GeoTIFFs: rasters
laid out so a client can read just the part it needs with HTTP range
requests), in `s3://geobase-silver/raster/<dataset>/`. No endpoint serves
them; raster display was left for a later phase (docs/adr/003).

ArcGIS Pro cannot add a COG from a plain HTTPS URL; Esri has had this as an
open request since 2023. It reads remote rasters through a cloud storage
connection file (`.acs`): an S3 endpoint, a bucket and credentials. Pro signs
its own requests with them and fetches only the parts on screen. A manual
test on 2026-10-29 passed: Pro 3.7 on Windows, over Tailscale, opened a COG
from the VPS's RustFS through an `.acs` with the MinIO provider,
`AWS_HTTPS=NO` and `AWS_VIRTUAL_HOSTING=FALSE`.

The rules said no. CLAUDE.md and docs/adr/011 send anything carrying a
credential through the backend. The lake (RustFS, the S3-compatible object
store) listens only on localhost and the VPS's Tailscale address.

## Decision

**The portal hands a desktop client short-lived, read-only credentials for
one raster, and the raster's place in the lake.** It never sends pixels.

- **Endpoint:** `GET /api/map/assets/{asset_id}/raster-access`. For an active
  raster asset it returns:
  ```json
  {"asset_id": "…",
   "url": "http://100.64.0.10:9000/geobase-silver/raster/esri_landcover_landuse/lulc_2021_….tif",
   "endpoint": "http://100.64.0.10:9000", "region": "us-east-1",
   "bucket": "geobase-silver", "key": "raster/esri_landcover_landuse/lulc_2021_….tif",
   "credentials": {"access_key_id": "…", "secret_access_key": "…",
                   "session_token": "…", "expires_at": "2026-11-01T18:00:00Z"}}
  ```
  `url` is path-style and is not a presigned link: reading it takes the
  credentials. Anything but an active raster is a 404, as `/data` is for
  anything but a vector. The response carries `Cache-Control: no-store`.
- **A GET, though each call issues new credentials.** An API key may only
  read (docs/adr/021), and nothing in the portal or the lake changes.
- **Where the credentials come from:** RustFS's STS (Security Token
  Service) `AssumeRole` call, which turns a user's long-lived keys into
  temporary ones. One hour by default (`LAKE_STS_DURATION_SECONDS`, clamped
  to 900–43,200).
- **Who issues them:** a dedicated RustFS user, `portal-raster-issuer`, not
  the portal's own `LAKE_S3_*` keys. Its policy allows `s3:GetObject` on
  `geobase-silver/raster/*` and listing under `raster/`, nothing else.
  - It must be a regular RustFS user: its keys are its name and password.
    Keys from the Console's Access Keys page are service accounts, and
    RustFS refuses `AssumeRole` from them.
  - It needs at least one policy and no MFA.
- **Each set reads one object.** The call sends an inline session policy:
  `GetObject` on that one object, and listing its folder. RustFS grants the
  overlap of the two policies. Listing is there because Pro opens a raster
  the way GDAL does, by listing the folder for side files (`.aux.xml`,
  `.ovr`) first. It shows file names the catalog already lists to every
  signed-in user.
- **Session name:** `portal-user-<user id>`, so RustFS can trace a set to
  the user it went to.
- **Dependency:** `boto3`, for the STS call only. One module imports it,
  `apps/map/sts.py`, the way only `lake.py` imports `duckdb`.
- **Settings:** five new ones. `LAKE_PUBLIC_ENDPOINT` is the lake as the
  desktop reaches it, scheme included. `LAKE_STS_ACCESS_KEY` and
  `LAKE_STS_SECRET_KEY` are the issuer's name and password.
  `LAKE_STS_DURATION_SECONDS` and `LAKE_STS_TIMEOUT_SECONDS` complete the
  set. The STS call goes to `LAKE_S3_ENDPOINT`, where the portal already
  reaches the lake.
- **Unset is a supported state.** A blank public endpoint or issuer answers
  503, the way address search does without `ESRI_API_KEY` (docs/adr/011).
  An unreachable lake is 503 too, and one that answers with any other error
  is 502, as for `/data`.

**The lake's address for desktops is Tailscale until there is a public
hostname.** `LAKE_PUBLIC_ENDPOINT=http://<VPS Tailscale IP>:9000`. Rasters
then open only on machines on the tailnet, which is enough for the team. A
public entrance later is one nginx server block: TLS, `Host` passed through
unchanged (the signature covers it), path-style, and `limit_except GET HEAD`.
Only the setting changes; the credentials are not tied to a host name.

The add-in writes each set into its own `.acs`, with the
`CreateCloudStorageConnectionFile` geoprocessing tool, and adds the raster
from it. Ten minutes before a set expires it asks for a new one and points
the layer at a new `.acs`.

## Why

- **Temporary credentials, not a presigned URL.** A presigned URL is one
  link that expires. Pro cannot open one as a layer; the add-in would have
  to download the whole file first, which throws away the point of a COG.
- **Not a proxy through Django.** Every tile read would hold a gunicorn
  worker. `lake.read_blob` reads objects whole (docs/adr/017), so a
  streaming S3 client would be needed anyway. And Pro can send a bearer
  token to a generic web endpoint only from 3.5 on, where a 15-minute token
  is the wrong shape.
- **A dedicated issuer, and a policy per set,** so RustFS limits what a
  leaked set can do, not code that could be wrong. It also keeps the
  portal's read-only rule true: nothing here can write.
- **Checked against RustFS 1.0.4 before building, on 2026-11-01** (a local
  container, the user and policy above):
  - boto3's `assume_role` works against it.
  - The credentials read the one object, with a ranged GET.
  - They are refused on another raster, outside `raster/`, on listing any
    other folder, and on any write.
  - GDAL opened the COG with them through `/vsis3/`, sending and signing the
    session token. RustFS has rejected an unsigned token since 1.0.1.

## Consequences

- **The credential rule gets one exception.** The SPA still never talks to
  S3. CLAUDE.md now reads: anything carrying a credential goes through the
  backend, except short-lived, read-only, one-raster lake credentials handed
  to a signed-in desktop client.
- **A leaked `.acs` reads one raster until it expires.** Every signed-in
  user can already read every raster, so it reaches nothing new; it only
  skips the sign-in, for an hour.
- **A project saved with GoBase rasters stops drawing them once the
  credentials run out.** The add-in renews them when the project is open
  and it is signed in. Without the add-in, the layers stay broken, which is
  intended.
- **RustFS signs session tokens with its root secret.** Changing that
  secret ends every live set. Upstream knows and will not change it.
- **The contract has one more endpoint the add-in depends on.** Changing
  `raster-access` breaks a client that ships separately (docs/adr/021).
- **`/api/map/assets/{asset_id}` already returns `source_uri`,** against the
  comment in `apps/map/views.py`. This ADR does not change that, but the
  raster path is now handed out on purpose, so the leak is worth closing.
- **Infra:** one RustFS user and policy, three `.env` names to set
  (context/integrations/lake-sts.md).

## Open

- **Does Pro sign the session token in an `.acs`?** GDAL does, and Esri
  documents `AWS_SESSION_TOKEN` for the MinIO provider, but Esri's own S3
  code is untested with RustFS. The first Windows test answers it.
- **Does repointing a layer at a new `.acs` pick up the new credentials
  without a restart?** The add-in uses a new file name each time so that no
  cached connection is reused. Untested.

## Rejected

- **Presigned URLs, and a range proxy through Django.** See "Why".
- **Long-lived read-only S3 keys for each desktop user.** They never
  expire, and revoking one means changing RustFS users. A leaked `.acs`
  would read forever.
- **No session policy, the issuer's policy alone.** Simpler, and still
  read-only, but a leaked set would read every raster for an hour.
- **Raster tiles (TiTiler) for the desktop.** Tiles are pictures, not
  pixel values. They stay the plan for the web map (docs/adr/003).

## Revisit when

- The lake gets a public hostname: set `LAKE_PUBLIC_ENDPOINT`, nothing else.
- The catalog gets per-asset permissions: the session policy already
  narrows to one object, so only the endpoint's check changes.
- The lake moves to AWS S3: `AssumeRole` there needs a real role ARN, which
  `apps/map/sts.py` does not yet take.
