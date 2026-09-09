import { cn } from '@/lib/utils'

import { ACTIVE_RUN_STATUSES } from './runStatus'

/**
 * The filter groups Dagster's nine statuses into the four things anyone
 * actually looks for. Nothing selected means everything, so the list starts
 * unfiltered and the API gets no status parameter at all.
 */
export const STATUS_GROUPS: { key: string; label: string; statuses: string[] }[] = [
  { key: 'running', label: 'Running', statuses: ACTIVE_RUN_STATUSES },
  { key: 'success', label: 'Success', statuses: ['SUCCESS'] },
  { key: 'failed', label: 'Failed', statuses: ['FAILURE'] },
  { key: 'canceled', label: 'Canceled', statuses: ['CANCELING', 'CANCELED'] },
]

export function statusesFor(selected: readonly string[]): string[] {
  return STATUS_GROUPS.filter((group) => selected.includes(group.key)).flatMap(
    (group) => group.statuses,
  )
}

export function StatusFilter({
  selected,
  onChange,
}: {
  selected: readonly string[]
  onChange: (next: string[]) => void
}) {
  const toggle = (key: string) =>
    onChange(selected.includes(key) ? selected.filter((item) => item !== key) : [...selected, key])

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by status">
      <Chip active={selected.length === 0} onClick={() => onChange([])}>
        All
      </Chip>
      {STATUS_GROUPS.map((group) => (
        <Chip
          key={group.key}
          active={selected.includes(group.key)}
          onClick={() => toggle(group.key)}
        >
          {group.label}
        </Chip>
      ))}
    </div>
  )
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: string
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'rounded-full border px-3 py-1 text-xs transition-colors',
        active
          ? 'border-primary/40 bg-primary/10 text-primary'
          : 'border-border text-muted-foreground hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}
