/**
 * Theme application.
 *
 * The pre-auth pages follow the visitor's system theme and offer no toggle —
 * the toggle lives inside the shell (context/ui-rules.md). This module owns
 * the `.dark` class so the shell's stored preference can drop in later
 * without the landing page changing.
 */

export type ThemePreference = 'light' | 'dark' | 'system'

function systemPrefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

export function applyTheme(preference: ThemePreference): void {
  const dark = preference === 'system' ? systemPrefersDark() : preference === 'dark'
  document.documentElement.classList.toggle('dark', dark)
}

/** Follow the system theme, and keep following it if the OS setting changes. */
export function startSystemTheme(): () => void {
  applyTheme('system')
  const media = window.matchMedia?.('(prefers-color-scheme: dark)')
  if (!media) return () => {}
  const listener = () => applyTheme('system')
  media.addEventListener('change', listener)
  return () => media.removeEventListener('change', listener)
}

const STORAGE_KEY = 'gp-theme'

/**
 * The shell's remembered choice, or null to follow the system
 * (context/ui-rules.md: remembered per browser).
 *
 * Private windows and blocked site data make these throw rather than return
 * nothing, so both directions are guarded. A browser that will not remember
 * still honours the choice for the session.
 */
export function readStoredTheme(): 'light' | 'dark' | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

export function storeTheme(preference: 'light' | 'dark'): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, preference)
  } catch {
    // Nothing to do: the choice still applies until the page is reloaded.
  }
}

/** What the system theme currently is, for seeding the shell's toggle. */
export function currentSystemTheme(): 'light' | 'dark' {
  return systemPrefersDark() ? 'dark' : 'light'
}
