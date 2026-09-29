import { useCallback, useEffect, useState } from 'react'

import { applyTheme, currentSystemTheme, readStoredTheme, storeTheme } from '@/app/theme'

/**
 * The shell's light/dark toggle.
 *
 * The shell owns the theme only while it is mounted; leaving it hands the
 * page back to the system theme, which is what the pre-auth pages are
 * required to use (context/ui-rules.md).
 */
export function useThemeToggle() {
  const [theme, setTheme] = useState<'light' | 'dark'>(
    () => readStoredTheme() ?? currentSystemTheme(),
  )

  useEffect(() => {
    applyTheme(theme)
    return () => applyTheme('system')
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next = current === 'dark' ? 'light' : 'dark'
      storeTheme(next)
      return next
    })
  }, [])

  return { theme, toggle }
}
