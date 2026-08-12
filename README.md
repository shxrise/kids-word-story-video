# Kids Word Story Video

[中文](#中文) · [English](#english)

## 中文

这是一个面向中文用户的 Codex 技能：把数量灵活的英语目标词编入一段连贯、有趣的儿童故事，并制作成完整的 720p 宽屏 MP4 视频。它将故事创作、插画生成与审核、中文旁白、目标词标、少量音效、Remotion 渲染和成片验收整合为一套可重复执行的工作流。

### 主要能力

- 先展示确认单，确认目标词和偏好后再开始制作。
- 围绕目标词原创完整故事，避免把单词机械排列成句子。
- 为每个项目建立专属角色和视觉设定，生成稳定的 16:9 儿童绘本插画。
- 对插画进行比例检查和语义审核；不符合故事情景时最多额外重试两次，再选择偏差最小的候选图，并只允许轻微调整单幕故事或旁白。
- 默认使用温和中文女声，让英语目标词自然保留在中文旁白中。
- 使用大号半透明目标词标；目标词停顿默认是 `0` 秒，也可配置为 `0.3`、`1.0` 秒等跟读时间。
- 添加克制的场景音效，不使用持续背景音乐干扰旁白。
- 使用 Remotion 输出固定 `1280×720`、`20fps`、H.264 + AAC 的 MP4。
- 保存流程状态、输入指纹和 QA 证据，支持中断恢复，并在交付前进行技术验收和主观审查。

### 安装

将仓库克隆到 Codex 的技能目录：

```powershell
git clone https://github.com/shxrise/kids-word-story-video.git "$env:USERPROFILE\.codex\skills\kids-word-story-video"
```

重新打开 Codex 任务后，该技能即可被自动发现。技能目录名应保持为 `kids-word-story-video`。

### 使用

在 Codex 中直接提出视频需求，例如：

```text
使用 kids-word-story-video，把 apple、ant、book、bird 做成一个儿童单词故事视频。
```

技能会先给出确认单。在你确认之前，它不会创建项目、生成插画、合成语音或渲染视频。确认后，Codex 会按照 `SKILL.md` 中的完整流程执行制作和验收。

### 仓库结构

```text
SKILL.md                    技能入口和核心工作流
agents/openai.yaml          Codex 界面元数据
scripts/                    项目创建、语音、审核、渲染和验收脚本
references/                 故事、确认单、音效和 QA 规则
assets/remotion-template/   可复用的 Remotion 视频项目模板
```

### 说明

- 这是社区创作的个人项目，不是 OpenAI 官方技能。
- 插画生成、语音服务和本地渲染能力取决于当前 Codex 环境及可用工具。
- 请只使用你有权处理和分享的单词、图片、声音及其他素材。

## English

Kids Word Story Video is a Codex skill designed primarily for Chinese-speaking users. It turns a flexible list of English target words into a coherent, playful children's story and produces a complete 720p widescreen MP4. The skill combines story writing, illustration generation and review, Chinese narration, target-word overlays, light sound design, Remotion rendering, and final QA in one repeatable workflow.

### Key features

- Shows a confirmation card before any production work begins.
- Writes an original story around the target words instead of mechanically listing them.
- Creates a project-specific cast and visual bible for consistent 16:9 children's-book illustrations.
- Checks image aspect ratios and semantics. If an image misses the story context, it allows up to two additional attempts, then selects the closest candidate and permits only a small scene-level narration adjustment.
- Uses a gentle Chinese female voice by default while keeping English target words in the narration.
- Displays large translucent target-word overlays. The default word pause is `0` seconds, with configurable read-along pauses such as `0.3` or `1.0` seconds.
- Adds restrained scene sound effects without continuous background music competing with narration.
- Renders a fixed `1280×720`, `20fps`, H.264 + AAC MP4 with Remotion.
- Records pipeline state, input fingerprints, and QA evidence for resumable, verifiable delivery.

### Installation

Clone the repository into the Codex skills directory:

```powershell
git clone https://github.com/shxrise/kids-word-story-video.git "$env:USERPROFILE\.codex\skills\kids-word-story-video"
```

Start a new Codex task so the skill can be discovered. Keep the folder name as `kids-word-story-video`.

### Usage

Ask Codex for a word-story video, for example:

```text
Use kids-word-story-video to make a children's story video with apple, ant, book, and bird.
```

The skill first presents a confirmation card. It does not create a project, generate illustrations, synthesize speech, or render video until you confirm. After confirmation, Codex follows the complete production and QA workflow in `SKILL.md`.

### Repository layout

```text
SKILL.md                    Skill entry point and core workflow
agents/openai.yaml          Codex UI metadata
scripts/                    Project, speech, review, render, and QA tools
references/                 Story, confirmation, sound, and QA rules
assets/remotion-template/   Reusable Remotion video project template
```

### Notes

- This is a community-built personal project, not an official OpenAI skill.
- Image generation, speech services, and local rendering depend on the tools available in the current Codex environment.
- Only use words, images, voices, and other materials that you are authorized to process and share.

## License

MIT License. See [LICENSE](LICENSE).
