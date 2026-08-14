import {Composition, staticFile} from 'remotion';
import {StoryVideo} from './StoryVideo';
import {introDuration, sceneDuration} from './timing';
import type {Story} from './types';
import './index.css';

const FALLBACK: Story = {
  meta: {
    schemaVersion: 2,
    category: '主题',
    series: '副标题',
    width: 1280,
    height: 720,
    imageWidth: 1280,
    imageHeight: 720,
    fps: 20,
    imageNormalization: 'stable-lanczos',
    imageAspectTolerancePct: 1.0,
    ttsProvider: 'edge',
    voice: 'zh-CN-XiaoxiaoNeural',
    rate: '-15%',
    targetPauseSec: 0,
    targetVisualDurationSec: 1.2,
    introTailSec: 0.6,
    introTitle: '儿童故事',
    pauseTargets: [],
    durationTarget: {
      targetSec: 330,
      idealMinSec: 300,
      idealMaxSec: 360,
      acceptableMinSec: 285,
      acceptableMaxSec: 375,
      maxCreativeAdjustments: 2,
    },
    theme: {
      bg: '#F7F1E3',
      card: '#FDFBF4',
      ink: '#26241F',
      muted: '#8C8878',
      accent: '#E4B23A',
      badge: '#2C4A3B',
    },
  },
  visualBible: {
    stylePrompt: '',
    palette: '',
    characters: [],
    referenceImage: '',
  },
  scenes: [],
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="StoryVideo"
      component={StoryVideo}
      durationInFrames={100}
      fps={20}
      width={1280}
      height={720}
      defaultProps={{story: FALLBACK}}
      calculateMetadata={async () => {
        const res = await fetch(staticFile('story/story.json'));
        const story = (await res.json()) as Story;
        const {fps, width, height} = story.meta;
        const durationInFrames = Math.max(
          1,
          introDuration(story.meta, fps)
            + story.scenes.reduce((sum, s) => sum + sceneDuration(s, story.meta, fps), 0),
        );
        return {durationInFrames, fps, width, height, props: {story}};
      }}
    />
  );
};
