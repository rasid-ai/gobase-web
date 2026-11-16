/** A page that throws while rendering says so, instead of blanking the app. */

import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { PageBoundary } from './PageBoundary'

function Broken(): never {
  throw new Error('metadata is not an object')
}

afterEach(() => {
  vi.restoreAllMocks()
})

it('shows what broke, and a way to reload', () => {
  // React reports a caught render error to the console; that is expected here.
  vi.spyOn(console, 'error').mockImplementation(() => {})

  render(
    <PageBoundary>
      <Broken />
    </PageBoundary>,
  )

  expect(screen.getByText('This page could not be shown.')).toBeInTheDocument()
  expect(screen.getByText('metadata is not an object')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
})

it('renders the page untouched when nothing throws', () => {
  render(
    <PageBoundary>
      <p>fine</p>
    </PageBoundary>,
  )

  expect(screen.getByText('fine')).toBeInTheDocument()
})
