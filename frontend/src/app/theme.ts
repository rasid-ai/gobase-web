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
