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

A user can also get a key for themselves with their username and password:
`POST /api/auth/api-keys` with `{username, password, name}`. The answer is a
201 holding the key, its prefix, its name and when it was made, and it is
never cached. A wrong username or password gets a 400 with the same message
as login, and no key is made. No session is started.

The add-in sends the computer's name as `name`. Getting a key revokes that
user's other live keys with the same name, so each computer has one.

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
- Revoking a key from the add-in when signing out
- Rate limits
- Sign-in with a key as a Basic-auth password
