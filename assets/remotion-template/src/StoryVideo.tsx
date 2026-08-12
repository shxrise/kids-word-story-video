import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  Sequence,
  staticFile,
  useVideoConfig,
} from 'remotion';
import {SceneView} from './Scene';
import {introDuration, sceneDuration} from './timing';
import type {Scene, SfxAsset, SfxCue, Story} from './types';

const Intro: React.FC<{story: Story}> = ({story}) => {
  const firstImage = story.scenes[0]?.image;
  return (
    <AbsoluteFill style={{backgroundColor: '#151510'}}>
      {firstImage ? (
        <Img
          src={staticFile(firstImage)}
          style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain'}}
        />
      ) : null}
      <AbsoluteFill style={{backgroundColor: 'rgba(24, 20, 12, 0.36)'}} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
        <div
          className="font-title"
          style={{
            padding: '13px 29px 17px',
            borderRadius: 12,
            backgroundColor: 'rgba(255, 255, 255, 0.66)',
            color: 'rgba(35, 32, 24, 0.88)',
            fontSize: 61,
            lineHeight: 1.1,
            fontWeight: 900,
            letterSpacing: 2,
            boxShadow: '0 7px 24px rgba(0, 0, 0, 0.22)',
          }}
        >
          {story.meta.introTitle ?? story.meta.series}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const SfxTrack: React.FC<{
  cue: SfxCue;
  asset: SfxAsset;
  scene: Scene;
  fps: number;
  sceneFrames: number;
  targetPauseSec: number;
}> = ({cue, asset, scene, fps, sceneFrames, targetPauseSec}) => {
  const from = Math.max(0, Math.round(cue.startSec * fps));
  const requested = Math.max(1, Math.ceil(cue.durationSec * fps));
  const durationInFrames = Math.max(1, Math.min(requested, sceneFrames - from));
  const fadeIn = Math.max(0.10, cue.fadeInSec ?? 0.10);
  const fadeOut = Math.max(0.15, cue.fadeOutSec ?? 0.15);

  if (from >= sceneFrames) return null;

  return (
    <Sequence from={from} durationInFrames={durationInFrames} premountFor={Math.min(fps, from)}>
      <Audio
        src={staticFile(asset.src)}
        volume={(frame) => {
          const localSec = frame / fps;
          const sceneSec = cue.startSec + localSec;
          const fadeInGain = fadeIn > 0 ? interpolate(localSec, [0, fadeIn], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }) : 1;
          const fadeOutStart = Math.max(0, cue.durationSec - fadeOut);
          const fadeOutGain = fadeOut > 0 ? interpolate(localSec, [fadeOutStart, cue.durationSec], [1, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }) : 1;
          const overlapsSpokenTarget = (scene.targetHighlights ?? []).some((event) => {
            const spokenEnd = event.start + Math.max(0, event.duration - targetPauseSec);
            return sceneSec >= event.start && sceneSec < spokenEnd;
          });
          const narrationAttenuation = overlapsSpokenTarget ? 0.3 : 1;
          return cue.volume * fadeInGain * fadeOutGain * narrationAttenuation;
        }}
      />
    </Sequence>
  );
};

export const StoryVideo: React.FC<{story: Story}> = ({story}) => {
  const {fps} = useVideoConfig();
  const introFrames = introDuration(story.meta, fps);
  let offset = introFrames;

  return (
    <AbsoluteFill style={{backgroundColor: '#111'}}>
      {introFrames > 0 ? (
        <Sequence durationInFrames={introFrames} premountFor={fps}>
          <>
            <Intro story={story} />
            {story.meta.introAudio ? <Audio src={staticFile(story.meta.introAudio)} /> : null}
          </>
        </Sequence>
      ) : null}

      {story.scenes.map((scene, i) => {
        const dur = sceneDuration(scene, fps);
        const from = offset;
        offset += dur;

        return (
          <Sequence key={scene.id} from={from} durationInFrames={dur} premountFor={fps}>
            <SceneView scene={scene} meta={story.meta} index={i} total={story.scenes.length} />
            {scene.audio ? <Audio src={staticFile(scene.audio)} /> : null}
            {(scene.sfx ?? []).map((cue, cueIndex) => {
              const asset = story.sfxCatalog?.[cue.assetId];
              return asset ? (
                <SfxTrack
                  key={`${cue.assetId}-${cue.startSec}-${cueIndex}`}
                  cue={cue}
                  asset={asset}
                  scene={scene}
                  fps={fps}
                  sceneFrames={dur}
                  targetPauseSec={story.meta.targetPauseSec ?? 1}
                />
              ) : null;
            })}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
