/** Fold per-fragment source chips into the video interval they came from.
 *
 * Tutorial generation appends one `[来源:<id>]（03:06）` marker per cited
 * fragment, which renders as a long row of "原文出处" chips. Readers only need
 * to know which stretch of video the section came from, so every marker-only
 * line is folded into a single `视频来源 03:06–03:22` label.
 *
 * The markers stay in the stored Markdown: they are what the backend validates
 * and what keeps each paragraph traceable. Only the displayed line changes.
 */

export type SourceLike = {id: string; start?: number | null};
export type VideoRange = {start: number; end: number};

/** Fallback length for the last fragment of a document, which has no next start. */
export const FALLBACK_SPAN = 3;
/** Fragments closer than this are treated as one continuous stretch of video. */
export const MERGE_GAP = 15;

const MARKER_ITEM = /\[来源:([0-9a-fA-F-]{36})\](?:\s*[（(](\d{1,2}:\d{2}(?::\d{2})?)[）)])?/g;
const LINE_ONLY_MARKERS = /^(?:\s*\[来源:[0-9a-fA-F-]{36}\](?:\s*[（(]\d{1,2}:\d{2}(?::\d{2})?[）)])?)+\s*$/;

/** `mm:ss`, or `h:mm:ss` once the video runs past an hour. */
export function formatClock(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  const clock = `${String(Math.floor(value / 60) % 60).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  return Math.floor(value / 3600) ? `${Math.floor(value / 3600)}:${clock}` : clock;
}

/** Start and end of every fragment, using the next fragment as its end. */
export function segmentSpans(sources: SourceLike[]): Map<string, VideoRange> {
  const ordered = sources
    .filter(source => typeof source.start === 'number' && Number.isFinite(source.start))
    .map(source => ({id: source.id, start: source.start as number}))
    .sort((left, right) => left.start - right.start);
  const spans = new Map<string, VideoRange>();
  ordered.forEach((row, index) => {
    const next = ordered[index + 1];
    const end = next && next.start > row.start ? next.start : row.start + FALLBACK_SPAN;
    spans.set(row.id, {start: row.start, end: Math.max(end, row.start + 1)});
  });
  return spans;
}

/** Merge touching or nearly touching stretches, keeping clearly separate ones. */
export function mergeRanges(ranges: VideoRange[]): VideoRange[] {
  const sorted = ranges
    .filter(range => Number.isFinite(range.start) && Number.isFinite(range.end))
    .map(range => ({start: Math.min(range.start, range.end), end: Math.max(range.start, range.end)}))
    .sort((left, right) => left.start - right.start || left.end - right.end);
  const merged: VideoRange[] = [];
  for (const range of sorted) {
    const current = merged[merged.length - 1];
    if (current && range.start <= current.end + MERGE_GAP) current.end = Math.max(current.end, range.end);
    else merged.push({...range});
  }
  return merged;
}

/** `03:06–03:22`, or `03:06–03:22、05:40–06:10` when the section stitches stretches. */
export function rangeLabel(ranges: VideoRange[]): string {
  return ranges.map(range => `${formatClock(range.start)}–${formatClock(range.end)}`).join('、');
}

/**
 * Fold one marker-only line into a single `[视频来源:…]` token.
 * Returns null for anything else — prose lines, code, or fragments without a
 * known video time keep their original chips and stay clickable.
 */
export function compactSourceLine(line: string, spans: Map<string, VideoRange>): string | null {
  if (/^(?: {4,}|\t)/.test(line) || !LINE_ONLY_MARKERS.test(line)) return null;
  const ranges: VideoRange[] = [];
  for (const match of line.matchAll(MARKER_ITEM)) {
    const span = spans.get(match[1]);
    if (!span) return null;
    ranges.push(span);
  }
  if (!ranges.length || line.replace(MARKER_ITEM, '').trim()) return null;
  const label = rangeLabel(mergeRanges(ranges));
  return label ? `[视频来源:${label}]` : null;
}

/** Fold every citation-only line outside fenced code blocks. */
export function compactSourceLines(markdown: string, sources: SourceLike[] = []): string {
  if (!markdown.includes('[来源:')) return markdown;
  const spans = segmentSpans(sources);
  let fence: string | null = null;
  return markdown.split('\n').map(raw => {
    const fenceMatch = /^\s*(`{3,}|~{3,})/.exec(raw);
    if (fenceMatch) {
      const marker = fenceMatch[1][0];
      fence = fence ? (fence === marker ? null : fence) : marker;
      return raw;
    }
    if (fence) return raw;
    return compactSourceLine(raw, spans) ?? raw;
  }).join('\n');
}
