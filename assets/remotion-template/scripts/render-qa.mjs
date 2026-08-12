import {bundle} from '@remotion/bundler';
import {openBrowser, renderStill, selectComposition} from '@remotion/renderer';
import {createHash} from 'node:crypto';
import {existsSync, readFileSync, renameSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const [projectArg, workArg, progressArg] = process.argv.slice(2);
if (!projectArg || !workArg || !progressArg) {
  throw new Error('usage: node scripts/render-qa.mjs <project> <work.json> <progress.json>');
}
const project = path.resolve(projectArg);
const workPath = path.resolve(workArg);
const progressPath = path.resolve(progressArg);
const work = JSON.parse(readFileSync(workPath, 'utf8'));
let progress = existsSync(progressPath)
  ? JSON.parse(readFileSync(progressPath, 'utf8'))
  : {schemaVersion: 1, qaInputSha256: work.qaInputSha256, completed: {}};
if (progress.qaInputSha256 !== work.qaInputSha256) {
  progress = {schemaVersion: 1, qaInputSha256: work.qaInputSha256, completed: {}};
}

const atomicJson = (file, value) => {
  const temporary = `${file}.tmp`;
  writeFileSync(temporary, JSON.stringify(value, null, 2), 'utf8');
  renameSync(temporary, file);
};
const fileSha256 = (file) => createHash('sha256').update(readFileSync(file)).digest('hex').toUpperCase();

console.log('[qa] bundling once');
const serveUrl = await bundle({
  entryPoint: path.join(project, 'src', 'index.ts'),
  outDir: path.join(project, 'build', 'qa-bundle'),
  publicDir: path.join(project, 'public'),
  rootDir: project,
  enableCaching: true,
  onProgress: (value) => {
    const percent = Math.round(value);
    if (percent % 20 === 0) console.log(`[qa] bundle ${percent}%`);
  },
});
const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE || null;
const browser = await openBrowser('chrome', {
  browserExecutable,
  chromeMode: 'chrome-for-testing',
  logLevel: 'warn',
});
try {
  const composition = await selectComposition({
    serveUrl,
    id: 'StoryVideo',
    puppeteerInstance: browser,
    browserExecutable: browserExecutable || undefined,
    chromeMode: 'chrome-for-testing',
    logLevel: 'warn',
  });
  let rendered = 0;
  let reused = 0;
  for (const [index, job] of work.jobs.entries()) {
    const output = path.resolve(project, job.file);
    const saved = progress.completed[job.id];
    if (saved?.jobSha256 === job.jobSha256 && existsSync(output) && saved.fileSha256 === fileSha256(output)) {
      reused += 1;
      console.log(`[qa] reuse ${index + 1}/${work.jobs.length} ${job.id}`);
      continue;
    }
    await renderStill({
      serveUrl,
      composition,
      frame: job.frame,
      output,
      imageFormat: 'png',
      overwrite: true,
      puppeteerInstance: browser,
      browserExecutable: browserExecutable || undefined,
      chromeMode: 'chrome-for-testing',
      logLevel: 'warn',
    });
    progress.completed[job.id] = {
      jobSha256: job.jobSha256,
      file: job.file,
      fileSha256: fileSha256(output),
      frame: job.frame,
    };
    atomicJson(progressPath, progress);
    rendered += 1;
    console.log(`[qa] rendered ${index + 1}/${work.jobs.length} ${job.id}`);
  }
  console.log(`[qa] complete: rendered=${rendered}, reused=${reused}`);
} finally {
  await browser.close({silent: false});
}
