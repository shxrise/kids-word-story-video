import type {Scene, StoryMeta} from './types';

export const introDuration = (meta: StoryMeta, fps: number): number => {
  const seconds = meta.introAudioDurationSec ?? meta.introDurationSec ?? 0;
  // Never cut off the final syllable; the body starts on the first frame after the audio ends.
  return Math.max(0, Math.ceil(seconds * fps));
};

/** Full-color artwork and narration both begin on scene frame 0. */
export const sceneDuration = (scene: Scene, fps: number): number => {
  return Math.max(1, Math.ceil((scene.audioDurationSec ?? 3) * fps));
};
