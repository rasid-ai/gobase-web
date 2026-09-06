/**
 * Route-level done criteria for specs/auth.md.
 * Each test names the HLR id it proves.
 */

import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockFetch, renderApp, resetSession } from '@/test/harness'

const NO_SESSION = {
  'POST /api/auth/refresh': { status: 401, body: { detail: 'No refresh credential.' } },
}
const LIVE_SESSION = {
  'POST /api/auth/refresh': { status: 200, body: { access: 'access-token' } },
  'GET /api/auth/me': { status: 200, body: { username: 'viewer1', role: 'viewer' } },
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  resetSession()
})

describe('HLR-027 — the landing page is the unauthenticated root', () => {
  it('renders the tool description with sign-in as its only action', async () => {
    mockFetch(NO_SESSION)
    renderApp('/')

    expect(
      await screen.findByRole('heading', {
        name: /ask your geospatial knowledge base/i,
      }),
    ).toBeInTheDocument()

    // The three capabilities the page must describe.
    expect(screen.getByText(/natural-language questions/i)).toBeInTheDocument()
    expect(screen.getByText(/answers on the map/i)).toBeInTheDocument()
    expect(screen.getByText(/ingestion pipeline health/i)).toBeInTheDocument()

    // Sign-in is the only action offered.
    const links = screen.getAllByRole('link')
    expect(links.length).toBeGreaterThan(0)
    links.forEach((link) => expect(link).toHaveAttribute('href', '/signin'))
  })

  it('shows no knowledge-base data and calls no data endpoint', async () => {
    const { calls } = mockFetch(NO_SESSION)
    renderApp('/')
    await screen.findByRole('heading', { name: /ask your geospatial knowledge base/i })

    // The only request the page may ever make is the boot session check.
    expect(calls).toEqual(['POST /api/auth/refresh'])
  })
})

describe('HLR-001 — authentication gates every route but landing and sign-in', () => {
  it('redirects an unauthenticated deep link to the sign-in screen', async () => {
    mockFetch(NO_SESSION)
    renderApp('/runs')

    expect(
      await screen.findByRole('heading', { name: /sign in to geo portal/i }),
    ).toBeInTheDocument()
  })

  it('leaves the sign-in screen reachable without a session', async () => {
    mockFetch(NO_SESSION)
    renderApp('/signin')

    expect(
      await screen.findByRole('heading', { name: /sign in to geo portal/i }),
    ).toBeInTheDocument()
  })
})

describe('HLR-002 — the session survives a page refresh', () => {
  it('restores the session from the refresh cookie alone, with no credential prompt', async () => {
    // A reload: no access token in memory, only the httpOnly cookie the
    // fetch double stands in for.
    mockFetch(LIVE_SESSION)
    renderApp('/')

    expect(await screen.findByText(/viewer1/)).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: /sign in to geo portal/i }),
    ).not.toBeInTheDocument()
  })

  it('never shows the landing page to a signed-in user at the root', async () => {
    mockFetch(LIVE_SESSION)
    renderApp('/')

    await screen.findByText(/viewer1/)
    expect(
      screen.queryByRole('heading', { name: /ask your geospatial knowledge base/i }),
    ).not.toBeInTheDocument()
  })
})

describe('HLR-004 — an unrenewable session returns the user to sign-in', () => {
  it('signs out and renders no partial data when the session ends', async () => {
    mockFetch(LIVE_SESSION)
    renderApp('/')
    await screen.findByText(/viewer1/)

    const { notifySessionEnded } = await import('@/api/token-store')
    notifySessionEnded()

    expect(
      await screen.findByRole('heading', { name: /sign in to geo portal/i }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/viewer1/)).not.toBeInTheDocument()
  })
})

describe('HLR-005 — the client gates from the role the API reports', () => {
  it('shows the signed-in identity and role', async () => {
    mockFetch({
      ...LIVE_SESSION,
      'GET /api/auth/me': { status: 200, body: { username: 'admin1', role: 'admin' } },
    })
    renderApp('/')

    expect(await screen.findByText(/admin1 · admin/)).toBeInTheDocument()
  })
})

describe('sign-in form', () => {
  it('reports bad credentials inline without navigating', async () => {
    mockFetch({
      ...NO_SESSION,
      'POST /api/auth/login': {
        status: 400,
        body: { non_field_errors: ['Incorrect username or password.'] },
      },
    })
    renderApp('/signin')
    await screen.findByRole('heading', { name: /sign in to geo portal/i })

    await userEvent.type(screen.getByLabelText(/username/i), 'viewer1')
    await userEvent.type(screen.getByLabelText(/password/i), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/incorrect username or password/i)
    expect(screen.getByRole('heading', { name: /sign in to geo portal/i })).toBeInTheDocument()
  })

  it('enters the workspace on valid credentials', async () => {
    mockFetch({
      ...NO_SESSION,
      'POST /api/auth/login': { status: 200, body: { access: 'access-token' } },
      'GET /api/auth/me': { status: 200, body: { username: 'viewer1', role: 'viewer' } },
    })
    renderApp('/signin')
    await screen.findByRole('heading', { name: /sign in to geo portal/i })

    await userEvent.type(screen.getByLabelText(/username/i), 'viewer1')
    await userEvent.type(screen.getByLabelText(/password/i), 'correct')
    await userEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

    await waitFor(() => expect(screen.getByText(/viewer1 · viewer/)).toBeInTheDocument())
  })
})
