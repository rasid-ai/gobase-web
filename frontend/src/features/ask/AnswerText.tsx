import { Fragment, type ReactNode } from 'react'

/**
 * An answer's text: paragraphs, lists and bold, nothing more.
 *
 * The model writes light Markdown. Rather than a Markdown library, this reads
 * the three things an answer uses — blank-line paragraphs, `-` or `1.` lists,
 * and `**bold**` — and shows anything else as the plain text it is. No HTML is
 * ever built from the text, so nothing in an answer can inject markup.
 *
 * `trailing` goes at the end of the last block: the streaming caret, which
 * belongs after the last word rather than on a line of its own.
 */
export function AnswerText({ text, trailing }: { text: string; trailing?: ReactNode }) {
  const blocks = text.split(/\n{2,}/).filter((block) => block.trim() !== '')
  if (blocks.length === 0) return trailing ? <p>{trailing}</p> : null

  return (
    <div className="flex flex-col gap-3">
      {blocks.map((block, index) => (
        <Block key={index} block={block} trailing={index === blocks.length - 1 ? trailing : null} />
      ))}
    </div>
  )
}

const BULLET = /^\s*[-*•]\s+/
const NUMBERED = /^\s*\d+[.)]\s+/

function Block({ block, trailing }: { block: string; trailing: ReactNode }) {
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
              {inline(line.replace(BULLET, ''))}
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
            {inline(line.replace(NUMBERED, ''))}
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
        const content = inline(line.replace(/^#{1,6}\s+/, ''))
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

/** `**bold**` as bold. An unclosed pair, mid-stream, stays as typed until it closes. */
function inline(line: string): ReactNode[] {
  return line.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
      <strong key={index} className="font-semibold">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <Fragment key={index}>{part}</Fragment>
    ),
  )
}
