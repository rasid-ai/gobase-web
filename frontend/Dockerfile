# Frontend image: the built SPA served by nginx.
#
# Stage order matters. `production` is last, so a plain `docker build` — which
# is what .github/workflows/deploy.yml runs — gets the shipping image, while
# docker-compose.dev.yml asks for `--target dev` explicitly.

# ---- deps: the pnpm install layer both dev and prod share -------------------
FROM node:22.23.2-alpine AS deps
WORKDIR /app
# corepack honours package.json's packageManager field, so the image builds
# with the same pnpm the developer runs.
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ---- dev: Vite dev server with HMR (docker-compose.dev.yml only) -----------
FROM deps AS dev
COPY . .
EXPOSE 5173
# --host binds 0.0.0.0: without it Vite listens on loopback inside the
# container and the published port answers nothing.
CMD ["pnpm", "dev", "--host", "0.0.0.0"]

# ---- build: type-check and bundle ------------------------------------------
FROM deps AS build
COPY . .
RUN pnpm build

# ---- production: static files only, no Node at runtime ---------------------
FROM nginx:1.29-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
