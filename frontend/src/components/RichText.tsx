import type { ReactNode } from 'react';

/**
 * A deliberately small Markdown subset for model answers: paragraphs, bullet and numbered
 * lists, headings (as bold lines), **bold**, *italic* and `code`. Underscores are left alone
 * so identifiers like memory_type survive. It builds React elements
 * (never innerHTML), so model output cannot inject markup.
 */
export function RichText({ text }: { text: string }) {
  return <div className="rich">{blocks(text)}</div>;
}

type Block =
  | { kind: 'p'; lines: string[] }
  | { kind: 'ul' | 'ol'; items: string[] }
  | { kind: 'h'; text: string };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

function parse(text: string): Block[] {
  const out: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length > 0) out.push({ kind: 'p', lines: para });
    para = [];
  };
  for (const line of text.replace(/\r\n?/g, '\n').split('\n')) {
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    const heading = bullet || numbered ? null : HEADING.exec(line);
    if (bullet || numbered) {
      flush();
      const kind = bullet ? 'ul' : 'ol';
      const item = (bullet ?? numbered)?.[1] ?? '';
      const last = out[out.length - 1];
      if (last && last.kind === kind) last.items.push(item);
      else out.push({ kind, items: [item] });
    } else if (heading) {
      flush();
      out.push({ kind: 'h', text: heading[1] ?? '' });
    } else if (line.trim() === '') {
      flush();
    } else {
      const last = out[out.length - 1];
      // An indented continuation of a list item.
      if (para.length === 0 && last && (last.kind === 'ul' || last.kind === 'ol') && /^\s{2,}\S/.test(line)) {
        last.items[last.items.length - 1] += ` ${line.trim()}`;
      } else {
        para.push(line);
      }
    }
  }
  flush();
  return out;
}

function blocks(text: string): ReactNode[] {
  return parse(text).map((b, i) => {
    switch (b.kind) {
      case 'p':
        return (
          <p key={i}>
            {b.lines.map((l, j) => (
              <span key={j}>
                {j > 0 && <br />}
                {inline(l)}
              </span>
            ))}
          </p>
        );
      case 'h':
        return (
          <p key={i}>
            <strong>{inline(b.text)}</strong>
          </p>
        );
      case 'ul':
        return (
          <ul key={i}>
            {b.items.map((it, j) => (
              <li key={j}>{inline(it)}</li>
            ))}
          </ul>
        );
      case 'ol':
        return (
          <ol key={i}>
            {b.items.map((it, j) => (
              <li key={j}>{inline(it)}</li>
            ))}
          </ol>
        );
    }
  });
}

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;

function inline(s: string): ReactNode[] {
  const parts = s.split(INLINE);
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4) return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith('`') && p.endsWith('`') && p.length > 2) return <code key={i}>{p.slice(1, -1)}</code>;
    if (p.startsWith('*') && p.endsWith('*') && p.length > 2) return <em key={i}>{p.slice(1, -1)}</em>;
    return p;
  });
}
