# Code Standards

## Commits & branches

- **Conventional Commits** (`feat:`, `fix:`, `docs:`, `test:`, `chore:`,
  `refactor:`); reference the HLR/ticket ID in the body when the change
  implements one.
- **Branches:** `main` deploys to the firm's VPS (production); `dev`
  deploys to the developer VPS (development). Feature branches come off
  `dev` and PR into it; `dev` promotes to `main` by PR. Nothing merges
  without a human (Gate C).
- **Requirement changes carry the product owner's sign-off (Gate A).** A
  change under `specs/` is a requirement change: the approving PO is
  recorded as an `Approved-by:` trailer on the commit, or as their
  approval on the PR when one is used. Sign-off is approval provenance,
  not status — status stays in Jira.

## Backend (Python 3.12)

- **ruff** for linting and formatting, default configuration.
- Tests with **pytest + pytest-django**; run with `pytest`.
- Type hints on new code.

## Frontend (Node 22 LTS, pnpm)

- **eslint + prettier**, default configurations; `pnpm lint`.
- Tests with **Vitest + React Testing Library**; `pnpm test`.

## Both

- Pin exact dependency versions.
- Every Must requirement's done criteria exist as automated tests tagged
  with its HLR ID — the traceability check in CI fails the build if a
  Must/MVP requirement has no passing linked test. The tag is
  `@pytest.mark.hlr("HLR-002")` on the backend (the marker is registered
  in `backend/pyproject.toml`) and the id in the `describe` name on the
  frontend. One test may carry one id; a requirement may have several
  tests.
- Secrets by name, never by value — see CLAUDE.md.
