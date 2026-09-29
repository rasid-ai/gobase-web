# ADR-017: One deployed environment, deployed from `main`

**Status:** Proposed · 2026-09-29
**Relates to:** docs/adr/001 (the deploy pipeline, unchanged)

## Context

The pipeline deployed two environments by branch: `main` to the firm's VPS
(production) and `dev` to the developer VPS (development). Management has
decided there will be no production deployment on our side: at delivery the
repository's ownership moves to the client, who will run deployment on their
own infrastructure. A production host we set up now would be handed over
unused or torn down. `main` had never been deployed; all work lived on `dev`.

## Decision

The developer VPS is the only deployed environment, and it is deployed from
`main`. `dev` no longer deploys and is deleted once promoted into `main`;
feature branches come off `main` and PR into it.

## Rejected

- **Keep both environments** — builds and secures a production host that is
  never used before the client takes over.
- **Keep deploying from `dev`, leave `main` idle** — the branch handed to the
  client at delivery would not be the one that was running.
- **Keep `dev` as an integration branch that no longer deploys** — a second
  long-lived branch with no job; it drifts and PRs land in the wrong one.
- **Force-reset `main` to `dev`** — same tree as a reviewed fast-forward PR,
  minus the review.

## Consequences

- There is no production environment until the client builds one. Anything
  that reaches `main` reaches the only deployed portal, so `main` needs
  branch protection and green checks carry more weight.
- The GitHub Environment `production` and its secrets are removed; the
  `development` environment must allow deployments from `main`.
- The `dev` image tag stops being published; `latest` follows `main`.
- "Production" in code and docs keeps meaning "the deployed stack" (the
  production Docker target, `docker-compose.prod.yml`, docs/adr/007); those
  stay true on the developer VPS and on whatever the client runs.
- Revisit at delivery: the client decides their own environments and
  branching, and may supersede this ADR.
