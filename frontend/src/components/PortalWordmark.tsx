/** GEO·PORTAL wordmark — the emerald half is the Rasid identity cue. */
export function PortalWordmark({ className = '' }: { className?: string }) {
  return (
    <span className={`text-sm font-bold tracking-[0.1em] ${className}`}>
      GEO<span className="text-primary">PORTAL</span>
    </span>
  )
}
