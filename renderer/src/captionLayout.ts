// Caption layout without React or Remotion, so it can be tested on its own.
const FONT_SIZE = 40;
const ROW_HEIGHT = FONT_SIZE * 1.35;
const PAD_X = 36;
const PAD_Y = 16;
const MAX_TEXT_WIDTH = 1480 - 2 * PAD_X;

export type CaptionLayout = {rows: string[]; width: number; height: number};

/**
 * Break a caption into balanced rows by measured width (as CSS `text-wrap: balance` would), so the box size
 * is known in advance and can ease from one line's size to the next instead of snapping.
 */
export const layoutCaption = (text: string, measure: (text: string) => number, maxWidth = MAX_TEXT_WIDTH): CaptionLayout => {
  const words = text.split(/\s+/).filter(Boolean);
  const rowsWithin = (limit: number) => {
    const rows: string[] = [];
    for (const word of words) {
      const joined = rows.length ? `${rows[rows.length - 1]} ${word}` : word;
      if (rows.length && measure(joined) <= limit) rows[rows.length - 1] = joined;
      else rows.push(word);
    }
    return rows;
  };
  const count = rowsWithin(maxWidth).length;
  // The narrowest width that still needs no more rows than a full-width fill.
  let low = measure(text) / count;
  let high = maxWidth;
  for (let step = 0; step < 24; step++) {
    const middle = (low + high) / 2;
    if (rowsWithin(middle).length <= count) high = middle;
    else low = middle;
  }
  const rows = rowsWithin(high);
  return {rows, width: Math.max(...rows.map(measure)) + 2 * PAD_X, height: rows.length * ROW_HEIGHT + 2 * PAD_Y};
};
