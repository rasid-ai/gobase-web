/** What the Runs page promises: specs/runs.md and context/ui-rules.md. */

import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockFetch, renderApp, resetSession } from '@/test/harness'

const RUN_ID = '11111111-1111-1111-1111-111111111111'
const LIST_URL = 'GET /api/runs/?limit=25'
const DETAIL_URL = `GET /api/runs/${RUN_ID}`

function session(role: 'admin' | 'viewer') {
  return {
    'POST /api/auth/refresh': { status: 200, body: { access: 'access-token' } },
    'GET /api/auth/me': { status: 200, body: { username: `${role}1`, role } },
  }
}

function run(overrides: Record<string, unknown> = {}) {
  return {
    id: RUN_ID,
    short_id: '11111111',
    job_name: 'weekly_pipeline',
    status: 'SUCCESS',
    created_at: '2026-09-04T15:33:20+00:00',
    started_at: '2026-09-04T15:33:30+00:00',
    ended_at: '2026-09-04T15:34:30+00:00',
    duration_seconds: 60,
    trigger: { kind: 'manual', name: null },
    partition: null,
    steps_succeeded: 1,
    steps_failed: 0,
    materializations: 1,
    assets: ['catalog_ingest'],
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  resetSession()
})

describe('the run list', () => {
  it('shows each run with its status', async () => {
    mockFetch({
      ...session('viewer'),
      [LIST_URL]: { status: 200, body: { results: [run()], next_cursor: null } },
    })
    renderApp('/runs')

    expect(await screen.findByText('11111111')).toBeInTheDocument()
    expect(screen.getByText('Success')).toBeInTheDocument()
    expect(screen.getByText('1 min')).toBeInTheDocument()
  })

  it('names a status Dagster added that the design system has no colour for', async () => {
    mockFetch({
      ...session('viewer'),
      [LIST_URL]: {
        status: 200,
        body: { results: [run({ status: 'CANCELED' })], next_cursor: null },
      },
    })
    renderApp('/runs')

    expect(await screen.findByText('Canceled')).toBeInTheDocument()
  })

  it('does not crash on a status it has never seen', async () => {
    mockFetch({
      ...session('viewer'),
      [LIST_URL]: {
        status: 200,
        body: { results: [run({ status: 'SOME_NEW_STATE' })], next_cursor: null },
      },
    })
    renderApp('/runs')

    expect(await screen.findByText('Some new state')).toBeInTheDocument()
  })

  it('says so when there are no runs at all', async () => {
    mockFetch({
      ...session('viewer'),
      [LIST_URL]: { status: 200, body: { results: [], next_cursor: null } },
    })
    renderApp('/runs')

    expect(await screen.findByText('No runs yet')).toBeInTheDocument()
  })

  it('separates an unreachable pipeline service from a broken page', async () => {
    mockFetch({
      ...session('viewer'),
      [LIST_URL]: { status: 503, body: { detail: 'Dagster is unreachable' } },
    })
    renderApp('/runs')

    expect(await screen.findByText(/pipeline service is unreachable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('opening a run', () => {
  it('loads its steps only once it is opened', async () => {
    const { calls } = mockFetch({
      ...session('viewer'),
      [LIST_URL]: { status: 200, body: { results: [run()], next_cursor: null } },
      [DETAIL_URL]: {
        status: 200,
        body: {
          ...run(),
          tags: [],
          failure_summary: null,
          steps: [
            {
              step_key: 'catalog_ingest',
              status: 'SUCCESS',
              started_at: '2026-09-04T15:33:30+00:00',
              ended_at: '2026-09-04T15:34:00+00:00',
              duration_seconds: 30,
            },
          ],
        },
      },
    })
    renderApp('/runs')

    const row = await screen.findByRole('button', { expanded: false })
    expect(calls).not.toContain(DETAIL_URL)

    await userEvent.click(row)

    expect(await screen.findByText('Catalog ingest')).toBeInTheDocument()
    expect(screen.getByText('30s')).toBeInTheDocument()
    expect(calls).toContain(DETAIL_URL)
  })

  it('puts the failure reason in front of a failed run', async () => {
    mockFetch({
      ...session('viewer'),
      [LIST_URL]: {
        status: 200,
        body: { results: [run({ status: 'FAILURE' })], next_cursor: null },
      },
      [DETAIL_URL]: {
        status: 200,
        body: {
          ...run({ status: 'FAILURE' }),
          tags: [],
          steps: [],
          failure_summary: 'rclone exited 1',
        },
      },
    })
    renderApp('/runs')

    await userEvent.click(await screen.findByRole('button', { expanded: false }))

    expect(await screen.findByText('rclone exited 1')).toBeInTheDocument()
  })
})

describe('triggering a run', () => {
  it('is invisible to a Viewer', async () => {
    mockFetch({
      ...session('viewer'),
      [LIST_URL]: { status: 200, body: { results: [run()], next_cursor: null } },
    })
    renderApp('/runs')

    await screen.findByText('11111111')
    expect(screen.queryByRole('button', { name: 'Run pipeline' })).not.toBeInTheDocument()
  })

  it('launches nothing until an Admin confirms', async () => {
    const { calls } = mockFetch({
      ...session('admin'),
      [LIST_URL]: { status: 200, body: { results: [run()], next_cursor: null } },
    })
    renderApp('/runs')

    await userEvent.click(await screen.findByRole('button', { name: 'Run pipeline' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    expect(calls).not.toContain('POST /api/runs/trigger')
  })

  it('reports the new run once the Admin confirms', async () => {
    mockFetch({
      ...session('admin'),
      [LIST_URL]: { status: 200, body: { results: [run()], next_cursor: null } },
      'POST /api/runs/trigger': { status: 202, body: { id: 'abcdef12-0000', status: 'QUEUED' } },
    })
    renderApp('/runs')

    await userEvent.click(await screen.findByRole('button', { name: 'Run pipeline' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Start run' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Run abcdef12 started.')
  })

  it('explains a refusal when one is already running', async () => {
    mockFetch({
      ...session('admin'),
      [LIST_URL]: { status: 200, body: { results: [run()], next_cursor: null } },
      'POST /api/runs/trigger': {
        status: 409,
        body: { detail: 'A run is already in progress', run_id: RUN_ID },
      },
    })
    renderApp('/runs')

    await userEvent.click(await screen.findByRole('button', { name: 'Run pipeline' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Start run' }))

    expect(await screen.findByRole('status')).toHaveTextContent('A run is already in progress.')
  })

  it('is disabled when the pipeline service did not answer', async () => {
    // Offering to launch a run into a service that is down invites a failure
    // the user can do nothing about.
    mockFetch({
      ...session('admin'),
      [LIST_URL]: { status: 503, body: { detail: 'Dagster is unreachable' } },
    })
    renderApp('/runs')

    await screen.findByText(/pipeline service is unreachable/i)
    expect(screen.getByRole('button', { name: 'Run pipeline' })).toBeDisabled()
  })

  it('is disabled while a run is still going, mirroring the server guard', async () => {
    mockFetch({
      ...session('admin'),
      [LIST_URL]: {
        status: 200,
        body: { results: [run({ status: 'STARTED', duration_seconds: null })], next_cursor: null },
      },
    })
    renderApp('/runs')

    // Wait for the list, or the button is still in its unknown-yet state.
    await screen.findByText('11111111')
    expect(screen.getByRole('button', { name: 'Run pipeline' })).toBeDisabled()
  })
})
