import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { authLoginCreate } from '@/api/generated/auth/auth'
import { useAuth } from '@/app/auth/useAuth'
import { PortalWordmark } from '@/components/PortalWordmark'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const schema = z.object({
  username: z.string().min(1, 'Enter your username.'),
  password: z.string().min(1, 'Enter your password.'),
})

type FormValues = z.infer<typeof schema>

export function SignInPage() {
  const { signIn, sessionExpired } = useAuth()
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null)
    // The API deliberately gives one message for unknown user and wrong
    // password alike; the form must not reveal which usernames exist.
    const failed = () => setFormError('Incorrect username or password.')
    try {
      const response = await authLoginCreate(values)
      if (response.status !== 200) return failed()
      await signIn(response.data.access)
      navigate('/', { replace: true })
    } catch {
      failed()
    }
  })

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="flex items-center gap-6 border-b border-border px-10 py-[18px]">
        <Link to="/">
          <PortalWordmark />
        </Link>
      </header>

      <main className="flex flex-1 items-center justify-center px-6 py-16">
        <div className="w-full max-w-[380px]">
          <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
            Sign in
          </p>
          <h1 className="mb-8 text-[28px] font-bold leading-tight tracking-[-0.02em]">
            Sign in to Geo Portal
          </h1>

          <form onSubmit={onSubmit} noValidate className="rounded-lg border border-border p-6">
            {formError && <Alert className="mb-5">{formError}</Alert>}
            {!formError && sessionExpired && (
              <p className="mb-5 rounded-md border border-border bg-muted px-3 py-2 text-[13px] text-muted-foreground">
                Your session has ended. Please sign in again.
              </p>
            )}

            <div className="mb-4">
              <Label htmlFor="username" className="mb-2 block">
                Username
              </Label>
              <Input
                id="username"
                autoComplete="username"
                autoFocus
                aria-invalid={Boolean(errors.username)}
                {...register('username')}
              />
              {errors.username && (
                <p className="mt-1.5 text-[13px] text-destructive">{errors.username.message}</p>
              )}
            </div>

            <div className="mb-6">
              <Label htmlFor="password" className="mb-2 block">
                Password
              </Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                aria-invalid={Boolean(errors.password)}
                {...register('password')}
              />
              {errors.password && (
                <p className="mt-1.5 text-[13px] text-destructive">{errors.password.message}</p>
              )}
            </div>

            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          <p className="mt-5 text-center text-[13px] text-muted-foreground">
            Access is provisioned by your workspace admin.
          </p>
        </div>
      </main>
    </div>
  )
}
