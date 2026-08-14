import {
  AbsoluteFill,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {RollingCaption} from './RollingCaption';
import {sceneDuration, visualTargetDuration} from './timing';
import type {Scene, StoryMeta, TargetHighlight} from './types';

const TargetWordLabel: React.FC<{
  event: TargetHighlight;
  scene: Scene;
  meta: StoryMeta;
  currentTimeSec: number;
  collisionOffsetY: number;
}> = ({event, scene, meta, currentTimeSec, collisionOffsetY}) => {
  const marker = scene.targetMarkers?.[event.word];
  if (!marker) return null;
  const safeX = Math.max(6, Math.min(94, marker.x));
  const safeY = Math.max(7, Math.min(78, marker.y));

  const elapsed = Math.max(0, currentTimeSec - event.start);
  const breathProgress = Math.min(1, elapsed / Math.min(1, visualTargetDuration(event, meta)));
  const scale = interpolate(breathProgress, [0, 0.5, 1], [1, 1.05, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = interpolate(breathProgress, [0, 0.5, 1], [0.96, 1, 0.98], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      className="font-en"
      style={{
        position: 'absolute',
        left: `${safeX}%`,
        top: `calc(${safeY}% + ${collisionOffsetY}px)`,
        transform: `translate(-50%, -50%) scale(${scale})`,
        opacity,
        zIndex: 5,
        padding: '7px 16px 8px',
        borderRadius: 10,
        backgroundColor: 'rgba(255, 255, 255, 0.58)',
        color: 'rgba(24, 54, 42, 0.74)',
        boxShadow: '0 2px 9px rgba(0, 0, 0, 0.12)',
        fontSize: 36,
        lineHeight: 1,
        fontWeight: 900,
        letterSpacing: 0.5,
      }}
    >
      {event.displayWord}
    </div>
  );
};

export const SceneView: React.FC<{
  scene: Scene;
  meta: StoryMeta;
}> = ({scene, meta}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const dur = sceneDuration(scene, meta, fps);
  const currentTimeSec = frame / fps;
  const progress = dur <= 1 ? 1 : frame / (dur - 1);
  const activeEvents = (scene.targetHighlights ?? []).filter(
    (event) => currentTimeSec >= event.start
      && currentTimeSec < event.start + visualTargetDuration(event, meta),
  );
  const activeByWord = new Map<string, TargetHighlight>();
  for (const event of activeEvents) {
    const existing = activeByWord.get(event.word);
    if (!existing || event.start >= existing.start) activeByWord.set(event.word, event);
  }
  const activeHighlights = Array.from(activeByWord.values());

  return (
    <AbsoluteFill className="font-body" style={{backgroundColor: '#111'}}>
      <Img
        src={staticFile(scene.image)}
        style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain'}}
      />

      {activeHighlights.map((event, eventIndex) => (
        <TargetWordLabel
          key={`${event.word}-${event.start}-${eventIndex}`}
          event={event}
          scene={scene}
          meta={meta}
          currentTimeSec={currentTimeSec}
          collisionOffsetY={(() => {
            const marker = scene.targetMarkers?.[event.word];
            if (!marker) return 0;
            const collisions = activeHighlights.slice(0, eventIndex).filter((other) => {
              const otherMarker = scene.targetMarkers?.[other.word];
              return otherMarker
                && Math.abs(otherMarker.x - marker.x) < 12
                && Math.abs(otherMarker.y - marker.y) < 10;
            }).length;
            if (collisions === 0) return 0;
            if (marker.y < 20) return collisions * 54;
            if (marker.y > 65) return -collisions * 54;
            const step = Math.ceil(collisions / 2) * 54;
            return collisions % 2 === 1 ? -step : step;
          })()}
        />
      ))}

      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: 107,
          background: 'linear-gradient(transparent, rgba(0, 0, 0, 0.62))',
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 53,
          right: 53,
          bottom: 19,
          minHeight: 36,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '5px 12px 7px',
          borderRadius: 8,
          backgroundColor: 'rgba(0, 0, 0, 0.28)',
          color: 'rgba(255, 255, 255, 0.92)',
          textAlign: 'center',
          textShadow: '0 1px 3px rgba(0, 0, 0, 0.72)',
          zIndex: 6,
        }}
      >
        <RollingCaption
          text={scene.zh}
          timings={scene.zhChars}
          currentTimeSec={currentTimeSec}
          progress={progress}
          style={{fontSize: 20, fontWeight: 600, lineHeight: 1.35}}
        />
      </div>
    </AbsoluteFill>
  );
};
