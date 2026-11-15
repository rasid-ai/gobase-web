import { Fragment, type ReactNode } from 'react'

import { CitationMark } from './ReferenceChips'
import type { Mark } from './references'

/**
 * An answer's text: paragraphs, lists, bold and citation marks, nothing more.
 *
 * The model writes light Markdown. Rather than a Markdown library, this reads
 * the three things an answer uses — blank-line paragraphs, `-` or `1.` lists,
 * and `**bold**` — and shows anything else as the plain text it is. No HTML is
 * ever built from the text, so nothing in an answer can inject markup.
 *
 * A citation marker, `[A1]`, becomes a small numbered button that opens the
 * asset it cites (`marks`, from references.ts). A bracket the turn has no
 * reference for — `[sic]`, or a handle the agent did not send — stays as text.
 *
 * `trailing` goes at the end of the last block: the streaming caret, which
 * belongs after the last word rather than on a line of its own.
 */
export function AnswerText({
  text,
  marks = NO_MARKS,
  onSelect,
  trailing,
}: {
  text: string
  marks?: Map<string, Mark>
  onSelect?: (assetId: string) => void
  trailing?: ReactNode
}) {
  const blocks = text.split(/\n{2,}/).filter((block) => block.trim() !== '')
  if (blocks.length === 0) return trailing ? <p>{trailing}</p> : null

  const cite = { marks, onSelect }
  return (
    <div className="flex flex-col gap-3">
      {blocks.map((block, index) => (
        <Block
          key={index}
          block={block}
          cite={cite}
          trailing={index === blocks.length - 1 ? trailing : null}
        />
      ))}
    </div>
  )
}

const NO_MARKS: Map<string, Mark> = new Map()

type Cite = { marks: Map<string, Mark>; onSelect?: (assetId: string) => void }

const BULLET = /^\s*[-*•]\s+/
const NUMBERED = /^\s*\d+[.)]\s+/

function Block({ block, cite, trailing }: { block: string; cite: Cite; trailing: ReactNode }) {
  const lines = block.split('\n').filter((line) => line.trim() !== '')

  if (lines.every((line) => BULLET.test(line))) {
    return (
      <ul className="flex flex-col gap-1.5">
        {lines.map((line, index) => (
          <li key={index} className="flex gap-3">
            <span aria-hidden="true" className="text-muted-foreground">
              –
            </span>
            <span>
              {inline(line.replace(BULLET, ''), cite)}
              {index === lines.length - 1 ? trailing : null}
            </span>
          </li>
        ))}
      </ul>
    )
  }

  if (lines.every((line) => NUMBERED.test(line))) {
    return (
      <ol className="flex list-decimal flex-col gap-1.5 pl-5">
        {lines.map((line, index) => (
          <li key={index}>
            {inline(line.replace(NUMBERED, ''), cite)}
            {index === lines.length - 1 ? trailing : null}
          </li>
        ))}
      </ol>
    )
  }

  // A heading is shown as a bold line: the panel is too narrow for sizes.
  return (
    <p>
      {lines.map((line, index) => {
        const heading = /^#{1,6}\s+/.test(line)
        const content = inline(line.replace(/^#{1,6}\s+/, ''), cite)
        return (
          <Fragment key={index}>
            {index > 0 ? <br /> : null}
            {heading ? <strong className="font-semibold">{content}</strong> : content}
          </Fragment>
        )
      })}
      {trailing}
    </p>
  )
}

/** `**bold**` as bold, with marks inside it too. An unclosed pair, mid-stream, stays as typed until it closes. */
function inline(line: string, cite: Cite): ReactNode[] {
  return line.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
      <strong key={index} className="font-semibold">
        {marked(part.slice(2, -2), cite)}
      </strong>
    ) : (
      <Fragment key={index}>{marked(part, cite)}</Fragment>
    ),
  )
}

/** The whole marker, kept by the split so the text around it stays intact. */
const MARKER_SPLIT = /(\[[AP][1-9][0-9]{0,4}\])/g

/** Each `[A1]` the turn has a reference for as its numbered mark; any other bracket as text. */
function marked(text: string, { marks, onSelect }: Cite): ReactNode[] {
  return text.split(MARKER_SPLIT).map((part, index) => {
    const mark = part.startsWith('[') && part.endsWith(']') ? marks.get(part.slice(1, -1)) : null
    return mark && onSelect ? (
      <CitationMark key={index} mark={mark} onSelect={onSelect} />
    ) : (
      <Fragment key={index}>{part}</Fragment>
    )
  })
}
