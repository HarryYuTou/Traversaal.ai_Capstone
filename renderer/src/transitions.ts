/** Related shots keep their stage in place; unrelated content fades through the backdrop. */
export type Transition = 'cut' | 'fade';

type Part = {from: number; durationInFrames: number; stage?: number; continuousFromPrevious?: boolean};

/** A shared presentation is meaningful only across an uninterrupted, adjacent scene boundary. */
export const transitionBetween = (before?: Part, after?: Part): Transition =>
  before?.stage !== undefined && before.stage === after?.stage &&
  after.continuousFromPrevious !== false &&
  before.from + before.durationInFrames === after.from ? 'cut' : 'fade';

const sine = (value: number) => (1 - Math.cos(Math.PI * Math.max(0, Math.min(1, value)))) / 2;

/**
 * Fade inside the authored shot interval, never over a second cast or title. This also bounds the
 * scene's lifetime: once a shot ends it cannot keep walking, blinking or changing its state under
 * its successor. Every result depends only on the requested frame, including out-of-order seeks.
 */
export const transitionOpacity = (frame: number, durationInFrames: number, enter: Transition,
  exit: Transition, enterFrames: number, exitFrames: number): number => {
  if (frame < 0 || frame >= durationInFrames) return 0;
  // Very short cards must remain legible; reserve at least one fully visible frame in every shot.
  if (durationInFrames < 3) return 1;
  const entering = enter === 'fade' ? Math.max(0, enterFrames) : 0;
  const leaving = exit === 'fade' ? Math.max(0, exitFrames) : 0;
  const ratio = Math.min(1, (durationInFrames - 2) / Math.max(1, entering + leaving));
  const inLength = Math.floor(entering * ratio);
  const outLength = Math.floor(leaving * ratio);
  const shown = inLength ? sine(frame / inLength) : 1;
  const retained = outLength ? sine((durationInFrames - 1 - frame) / outLength) : 1;
  return Math.min(shown, retained);
};
