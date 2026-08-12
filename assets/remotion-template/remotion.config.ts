import {Config} from '@remotion/cli/config';
import {existsSync} from 'node:fs';

const installedChrome = [
  process.env.REMOTION_BROWSER_EXECUTABLE,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
].find((candidate): candidate is string => Boolean(candidate && existsSync(candidate)));

// Reuse a machine-wide browser when available instead of downloading a
// project-local Headless Chrome binary.
if (installedChrome) {
  Config.setBrowserExecutable(installedChrome);
  Config.setChromeMode('chrome-for-testing');
}
Config.setConcurrency(1);
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
