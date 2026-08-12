import {
  AbsoluteFill,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {RollingCaption} from './RollingCaption';
import {sceneDuration} from './timing';
import type {Scene, StoryMeta, TargetHighlight} from './types';

const TargetWordLabel: React.FC<{
  event: TargetHighlight;
  scene: Scene;
  currentTimeSec: number;
}> = ({event, scene, currentTimeSec}) => {
  const marker = scene.targetMarkers?.[event.word];
  if (!marker) return null;

  const progress = (currentTimeSec - event.start) / event.duration;
  const scale = interpolate(progress, [0, 0.08, 1], [0.96, 1, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      className="font-en"
      style={{
        position: 'absolute',
        left: `${marker.x}%`,
        top: `${marker.y}%`,
        transform: `translate(-50%, -50%) scale(${scale})`,
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
      {event.word}
    </div>
  );
};

export const SceneView: React.FC<{
  scene: Scene;
  meta: StoryMeta;
  index: number;
  total: number;
}> = ({scene}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const dur = sceneDuration(scene, fps);
  const currentTimeSec = frame / fps;
  const progress = dur <= 1 ? 1 : frame / (dur - 1);
  const activeHighlights = (scene.targetHighlights ?? []).filter(
    (event) => currentTimeSec >= event.start && currentTimeSec < event.start + event.duration,
  );

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
          currentTimeSec={currentTimeSec}
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
