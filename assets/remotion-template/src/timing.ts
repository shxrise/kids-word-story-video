import type {Scene, StoryMeta, TargetHighlight} from './types';

export const spokenTargetDuration = (event: TargetHighlight): number => {
  return Math.max(0, event.spokenDurationSec);
};

export const visualTargetDuration = (event: TargetHighlight, meta: StoryMeta): number => {
  return Math.max(meta.targetVisualDurationSec, spokenTargetDuration(event), event.visualDurationSec);
};

export const introDuration = (meta: StoryMeta, fps: number): number => {
  const audioSeconds = meta.introAudioDurationSec ?? 0;
  const seconds = audioSeconds + (meta.introTailSec ?? 0);
  // Never cut off the final syllable; retain the configured visual tail before body narration.
  return Math.max(0, Math.ceil(seconds * fps));
};

/** Full-color artwork and narration both begin on scene frame 0. */
export const sceneDuration = (scene: Scene, meta: StoryMeta, fps: number): number => {
  const audioSeconds = scene.audioDurationSec ?? 3;
  const visualEnd = (scene.targetHighlights ?? []).reduce(
    (latest, event) => Math.max(latest, event.start + visualTargetDuration(event, meta)),
    0,
  );
  return Math.max(1, Math.ceil(Math.max(audioSeconds, visualEnd) * fps));
};
