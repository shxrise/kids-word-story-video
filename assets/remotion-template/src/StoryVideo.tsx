import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  staticFile,
  useVideoConfig,
} from 'remotion';
import {SceneView} from './Scene';
import {introDuration, sceneDuration} from './timing';
import type {Story} from './types';

const Intro: React.FC<{story: Story}> = ({story}) => {
  const firstImage = story.scenes[0]?.image;
  const title = story.meta.introTitle ?? story.meta.series;
  const titleLength = Math.max(1, Array.from(title).length);
  const titleFontSize = Math.min(61, Math.max(22, 940 / titleLength));
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
            fontSize: titleFontSize,
            lineHeight: 1.1,
            fontWeight: 900,
            letterSpacing: 2,
            boxShadow: '0 7px 24px rgba(0, 0, 0, 0.22)',
            whiteSpace: 'nowrap',
          }}
        >
          {title}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
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

      {story.scenes.map((scene) => {
        const dur = sceneDuration(scene, story.meta, fps);
        const from = offset;
        offset += dur;

        return (
          <Sequence key={scene.id} from={from} durationInFrames={dur} premountFor={fps}>
            <SceneView scene={scene} meta={story.meta} />
            {scene.audio ? <Audio src={staticFile(scene.audio)} /> : null}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
