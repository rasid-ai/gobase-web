# Raster access for desktop clients

`GET /api/map/assets/{asset_id}/raster-access` tells a desktop client where
one raster is in the lake, with credentials that read it for a while. The
ArcGIS Pro add-in uses it to open a COG the way Pro opens any file in a cloud
store. Decided in docs/adr/022; the lake side is in
context/integrations/lake-sts.md.

## Built

- **Who may ask:** any signed-in user, with a JWT or an API key
  (docs/adr/021). Every signed-in user can already see every raster in the
  catalog.
- **What comes back** for an active raster asset: `asset_id`, `url` (the
  object on the public endpoint, path-style), `endpoint`, `region`, `bucket`,
  `key`, and `credentials` — `access_key_id`, `secret_access_key`,
  `session_token` and `expires_at`. One hour by default.
- **What the credentials can do:** read that one object, and list the names
  in its folder. Nothing else: not another raster, not a write.
- **Each call issues a new set.** Nothing is stored in the portal.
- **`Cache-Control: no-store`**, because the body is a secret.
- **Answers:**
  - 404 for anything but an active raster, as `/data` is for anything but a
    vector.
  - 503 when the portal is not set up for it (no `LAKE_PUBLIC_ENDPOINT`, or
    no issuer), and when the lake cannot be reached or refuses the issuer.
  - 502 when the lake answers with any other error, or the raster is not in
    the lake.
- **Logged:** which user got credentials for which asset. Never a key, a
  token or an STS error message.

## Not built

- **A public address for the lake.** Until nginx serves one,
  `LAKE_PUBLIC_ENDPOINT` is the VPS's Tailscale address, so rasters open only
  on machines on the tailnet.
- **The web map.** It does not draw rasters; TiTiler tiles remain the plan
  (docs/adr/003).
- **Rate limits.** Nothing stops a key asking every second; each answer
  still reads only one raster.
- **AWS S3.** `AssumeRole` there needs a real role ARN, which is not a setting.
