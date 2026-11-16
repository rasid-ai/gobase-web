import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

type Record_ = Record<string, unknown>

function isRecord(value: unknown): value is Record_ {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/**
 * Whether a metadata value is shown as a table rather than as text.
 *
 * Objects, and lists holding objects. A list of plain values — `[2, 4, 8]` —
 * reads fine on one line, so it stays text. Decided by the value's shape and
 * never by its key: the catalog's keys differ by data type and grow, and the
 * panel holds no list of them (specs/map.md).
 */
export function isStructured(value: unknown): boolean {
  if (Array.isArray(value)) return value.some((item) => item !== null && typeof item === 'object')
  return isRecord(value)
}

/** A plain value as text. Text inside a value is shown as text, never parsed. */
export function formatScalar(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.map(formatScalar).join(', ') : '—'
  return String(value)
}

/**
 * Any metadata value, as a table when it has structure.
 *
 * - a list of objects is a table with one column per key, in the order the
 *   keys first appear — `columns` becomes a Name | Dtype table;
 * - an object is a two-column key / value table;
 * - anything else is text.
 *
 * Nested values get the same treatment inside their cell, so no value is ever
 * printed as raw JSON.
 */
export function MetadataValue({ value }: { value: unknown }) {
  if (!isStructured(value)) return <span className="break-words">{formatScalar(value)}</span>

  if (Array.isArray(value)) {
    return value.every(isRecord) ? (
      <RecordsTable rows={value} />
    ) : (
      // A list mixing objects and plain values has no shared columns, so each
      // item gets its position as its key.
      <KeyValueTable entries={value.map((item, index) => [String(index + 1), item])} />
    )
  }
  return <KeyValueTable entries={Object.entries(value as Record_)} />
}

function RecordsTable({ rows }: { rows: readonly Record_[] }) {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))]
  if (rows.length === 0 || columns.length === 0) return <span>—</span>

  return (
    <Frame>
      <thead>
        <tr>
          {columns.map((column) => (
            <Th key={column}>{column}</Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index} className="border-t border-border">
            {columns.map((column) => (
              <Td key={column}>
                <MetadataValue value={row[column]} />
              </Td>
            ))}
          </tr>
        ))}
      </tbody>
    </Frame>
  )
}

function KeyValueTable({ entries }: { entries: readonly [string, unknown][] }) {
  if (entries.length === 0) return <span>—</span>

  return (
    <Frame>
      <tbody>
        {entries.map(([key, value], index) => (
          <tr key={key} className={cn(index > 0 && 'border-t border-border')}>
            <Th scope="row" className="w-0 whitespace-nowrap align-top">
              {key}
            </Th>
            <Td>
              <MetadataValue value={value} />
            </Td>
          </tr>
        ))}
      </tbody>
    </Frame>
  )
}

/** Hairline frame; a wide table scrolls inside it rather than widening the panel. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-full overflow-x-auto rounded-md border border-border">
      <table className="w-full border-collapse text-left font-mono text-[12px]">{children}</table>
    </div>
  )
}

function Th({
  children,
  className,
  scope = 'col',
}: {
  children: ReactNode
  className?: string
  scope?: 'col' | 'row'
}) {
  return (
    <th scope={scope} className={cn(MICRO, 'bg-muted/50 px-2.5 py-1.5 font-normal', className)}>
      {children}
    </th>
  )
}

function Td({ children }: { children: ReactNode }) {
  return <td className="px-2.5 py-1.5 align-top">{children}</td>
}
