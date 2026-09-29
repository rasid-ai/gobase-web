import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { PortalWordmark } from '@/components/PortalWordmark'

/**
 * The unauthenticated root.
 *
 * Describes the tool, offers sign-in as its only action, and shows no
 * knowledge-base data — it makes no API call at all. The map graphic below is
 * decorative CSS, never a live map.
 *
 * Ported from context/designs/Landing Page.dc.html. Every colour in that
 * mockup already maps 1:1 onto an existing token, so no new values appear here.
 */
export function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center gap-6 border-b border-border px-10 py-[18px]">
        <PortalWordmark />
        <span className="flex-1" />
        <Link
          to="/signin"
          className="shrink-0 whitespace-nowrap text-[13.5px] text-muted-foreground hover:text-primary"
        >
          Sign in
        </Link>
      </header>

      <section className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-14 px-10 py-[88px]">
        <div className="min-w-[340px] flex-1">
          <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
            Geo Portal
          </p>
          <h1 className="mb-5 text-[40px] font-bold leading-[1.15] tracking-[-0.02em]">
            Ask your geospatial knowledge base. See the answer on a map.
          </h1>
          <p className="mb-8 max-w-[480px] text-base leading-relaxed text-muted-foreground">
            Query satellite imagery, tabular data, and documents in plain language. Every answer
            cites its sources and can be drawn as a layer over the area you&rsquo;re asking about.
          </p>
          <div className="flex items-center gap-3.5">
            <Button asChild>
              <Link to="/signin">Sign in</Link>
            </Button>
            <span className="text-[13px] text-muted-foreground">
              Access is provisioned by your workspace admin.
            </span>
          </div>
        </div>

        <MapGraphic />
      </section>

      <section className="mx-auto grid max-w-[1180px] grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-9 border-t border-border px-10 py-14">
        {CAPABILITIES.map((capability) => (
          <article key={capability.label}>
            <p className="mb-2.5 font-mono text-[10.5px] uppercase tracking-[0.06em] text-primary">
              {capability.label}
            </p>
            <h2 className="mb-2 text-base font-semibold">{capability.title}</h2>
            <p className="text-[13.5px] leading-relaxed text-muted-foreground">{capability.body}</p>
          </article>
        ))}
      </section>

      <footer className="border-t border-border px-10 py-[22px] text-center text-xs text-muted-foreground">
        Seeing Earth, Smarter. Internal tool for Geo Portal analysts.
      </footer>
    </div>
  )
}

const CAPABILITIES = [
  {
    label: 'Ask',
    title: 'Natural-language questions',
    body: 'Draw a rectangle to scope a question to one area, then ask in plain language. Answers cite the imagery, tables, and documents behind them — never internal tool traces.',
  },
  {
    label: 'See',
    title: 'Answers on the map',
    body: 'Every answer can carry a map layer you can show or hide. Click any point to see what covers it, grouped by imagery, tabular data, and documents.',
  },
  {
    label: 'Monitor',
    title: 'Ingestion pipeline health',
    body: 'See every run, newest first, with per-step status and failure reasons — no server access or log viewer needed.',
  },
] as const

/**
 * Decorative only — three rectangles standing in for the three map token
 * roles. No data, no map library, no request.
 */
function MapGraphic() {
  return (
    <div
      aria-hidden
      className="relative h-80 min-w-[340px] flex-1 overflow-hidden rounded-lg border border-border bg-foreground/[0.03]"
    >
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(color-mix(in oklab, var(--foreground) 4%, transparent) 1px, transparent 1px), linear-gradient(90deg, color-mix(in oklab, var(--foreground) 4%, transparent) 1px, transparent 1px)',
          backgroundSize: '26px 26px, 26px 26px',
        }}
      />
      <div className="absolute left-[12%] top-[22%] h-[52%] w-[34%] rounded-[2px] border-2 border-map-result bg-map-result/20" />
      <div className="absolute left-[40%] top-[12%] h-[40%] w-[44%] rounded-[2px] border-[1.5px] border-dashed border-map-footprint bg-map-footprint/15" />
      <div className="absolute left-[56%] top-[44%] h-[44%] w-[34%] rounded-[2px] border-2 border-dashed border-map-selection" />

      <div className="absolute bottom-3.5 left-3.5 flex gap-3.5 text-[11.5px] text-muted-foreground">
        <LegendItem className="bg-map-result">Answer layer</LegendItem>
        <LegendItem className="bg-map-footprint">Footprint</LegendItem>
        <LegendItem className="bg-map-selection">Selection</LegendItem>
      </div>
    </div>
  )
}

function LegendItem({ className, children }: { className: string; children: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block size-2.5 rounded-[2px] ${className}`} />
      {children}
    </span>
  )
}
