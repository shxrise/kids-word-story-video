import {interpolate} from 'remotion';
import type {TimedChar} from './types';

type Segment = {start: number; end: number; text: string};

const splitSegments = (text: string): Segment[] => {
  const segments: Segment[] = [];
  for (const match of text.matchAll(/[^。！？!?，,]+[。！？!?，,]?/gu)) {
    if (match.index === undefined || match[0].length === 0) continue;
    segments.push({start: match.index, end: match.index + match[0].length, text: match[0]});
  }
  return segments.length > 0 ? segments : [{start: 0, end: text.length, text}];
};

export const RollingCaption: React.FC<{
  text: string;
  timings?: TimedChar[];
  currentTimeSec: number;
  progress: number;
  style?: React.CSSProperties;
}> = ({text, timings, currentTimeSec, progress, style}) => {
  const chars = Array.from(text);
  const timedVisible = timings
    ? timings.filter((item) => item.t <= currentTimeSec).length
    : null;
  const visibleCount = timedVisible ?? Math.floor(
    interpolate(progress, [0, 1], [0, chars.length], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }),
  );
  const cursor = Math.max(0, Math.min(chars.length - 1, visibleCount - 1));
  const segments = splitSegments(text);
  const segment = segments.find((item) => cursor < item.end) ?? segments[segments.length - 1];
  const localCount = Math.max(0, Math.min(segment.text.length, visibleCount - segment.start));
  const visibleText = Array.from(segment.text).slice(0, localCount).join('');

  return (
    <div style={{...style, position: 'relative'}}>
      <span style={{visibility: 'hidden'}}>{segment.text}</span>
      <span style={{position: 'absolute', inset: 0}}>{visibleText}</span>
    </div>
  );
};
