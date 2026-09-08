# Code Standards

## Commits & branches

- **Conventional Commits** (`feat:`, `fix:`, `docs:`, `test:`, `chore:`,
  `refactor:`); reference the Jira ticket in the body when the change
  implements one.
- **Branches:** `main` deploys to the firm's VPS (production); `dev`
  deploys to the developer VPS (development). Feature branches come off
  `dev` and PR into it; `dev` promotes to `main` by PR. Nothing merges
  without a human.
- **Update `specs/` when behaviour ships.** The specs describe what the
  system does, so a change that alters behaviour updates them in the
  same PR.

## Backend (Python 3.12)

- **ruff** for linting and formatting, default configuration.
- Tests with **pytest + pytest-django**; run with `pytest`.
- Type hints on new code.

## Frontend (Node 22 LTS, pnpm)

- **eslint + prettier**, default configurations; `pnpm lint`.
- Tests with **Vitest + React Testing Library**; `pnpm test`.

## Both

- Pin exact dependency versions.
- Test the behaviour a change ships, named for what it does.
- Secrets by name, never by value — see CLAUDE.md.
