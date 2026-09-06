import { defineConfig } from 'orval'

/**
 * The frontend client is generated from backend/openapi.yaml and never
 * hand-written (CLAUDE.md non-negotiable). Regenerate with `pnpm orval`
 * after the backend exports a new schema.
 */
export default defineConfig({
  portal: {
    input: '../backend/openapi.yaml',
    output: {
      mode: 'tags-split',
      target: './src/api/generated',
      schemas: './src/api/generated/model',
      client: 'react-query',
      override: {
        mutator: {
          path: './src/api/http-client.ts',
          name: 'httpClient',
        },
      },
    },
  },
})
