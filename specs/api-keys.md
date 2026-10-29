# API keys

Desktop clients, such as the ArcGIS Pro add-in, sign in with an API key
instead of the browser session. The decision is docs/adr/021.

Built.

## Issuing

An Admin creates a key in Django admin, under Accounts → API keys: pick the
user and give the key a name. The next page shows the key once. It is not
stored and cannot be shown again.
`python manage.py create_api_key <username> <name>` does the same from a
shell and prints only the key.

## Using

The client sends `Authorization: Api-Key <key>` on every request. The key
signs in as its user, with that user's role.

A key works only for reading: GET, HEAD and OPTIONS. Any other method gets a
403, whoever owns the key.

These get a 401:
- an unknown, mistyped or revoked key
- a key whose user has been disabled
- a wrong key sent with a write: the 401 comes before the read-only rule

## Revoking

An Admin selects keys in the list and runs "Revoke selected API keys". The
keys stop working at once. The list shows when each key was last used, to
within five minutes.

## Not built

- Expiry dates
- Self-service keys for users who are not Admins
- Rate limits
- Sign-in with a key as a Basic-auth password
