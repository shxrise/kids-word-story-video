---
name: kids-word-story-video
description: 将自定义英语单词编成连贯的儿童绘本故事视频，配中英混合语音旁白。用户提出儿童单词故事视频、把单词做成故事动画或批量复用该流程时使用。
---

# Kids Word Story Video

以最终 MP4 完整解码、证据链有效和主观审核状态如实记录为完成标准。

## 0. 先确认，确认前禁止制作

每个新视频请求都先完整阅读 [references/confirmation-card.md](references/confirmation-card.md)，只解析目标词和用户已给偏好，展示“尚未开工”的确认单，然后结束回复等待明确确认。

确认前禁止创建项目、写完整故事、生图、TTS、安装依赖或渲染。即使用户首次说“直接开始”，也先显示一次确认单。

## 固定合同

- 只提供 `1280×720`、`20fps`、H.264 + AAC；不提供其他分辨率或帧率。
- 默认旁白为温和女声 `zh-CN-XiaoxiaoNeural`、语速 `-15%`。用户点名后才换声音。
- 默认 TTS 提供者为 `edge`；需要正式商业服务时可选择 `azure`。使用前阅读 [references/tts-providers.md](references/tts-providers.md)。
- 插画为静态全彩儿童绘本，场景按剧情规划，默认倾向 22–25 幕。禁止文生视频、图生视频和 GIF 拼接。
- 中文主体旁白中仅目标词保留英文；每词至少自然出现两次，并对应可见对象、人物、部位或动作。
- 目标词的真实发音、读词后音频停顿和视觉展示分别记录。`targetPauseSec` 默认 `0` 秒，不插入静音；`targetVisualDurationSec` 默认 `1.2` 秒。
- 半透明词标从目标词开始发音时出现，至少显示约 1.2 秒；真实发音更长时持续到发音结束。词标使用 `36px` 英文字号，在目标物附近做一次轻微、清楚的呼吸式强调，不得遮挡字幕或关键动作。
- 标题是自然、完整的全中文儿童故事名，优先包含人物、事件、行动或悬念，建议 6～10 个中文字符，不截断、不换行。标题音频结束后按 `introTailSec` 默认保留 `0.6` 秒画面再进入正文。
- 默认以 `330` 秒为创作中心，理想范围 `300–360` 秒，实际 TTS 可接受范围 `285–375` 秒。用户明确指定时长时按项目配置执行。
- 原图比例偏差不超过 `1.0%` 时，以 Lanczos 轻微规格化，不询问用户；禁止裁切、补边和明显拉伸。

## 1. 建立项目与统一工具链

用户确认后加载 Codex 工作区依赖。把返回的 Python、Node、pnpm 路径一次性传给体检脚本；脚本把工具链保存到项目 `build/toolchain.json`，后续脚本自动复用，不再依赖临时 PATH。

```text
<Python> scripts/new_project.py --output <绝对项目路径>
<Python> scripts/doctor.py --project <项目> --repair --python <Python> --node <Node> --pnpm <pnpm>
<项目Python> scripts/pipeline_state.py <项目> status
```

`doctor.py --repair` 只能创建项目 `.venv`、安装锁定依赖和项目 `node_modules`；不得修改系统 PATH、安装系统软件或请求管理员权限。磁盘低于 2GB 时拒绝，低于 8GB 时警告。

## 2. 创作 v2 故事合同与时长计划

完整阅读 [references/story-contract.md](references/story-contract.md)。先整体创作故事，再拆分镜；不得按词表机械排列。每个项目动态建立 `visualBible`，不得复用模板角色。

默认围绕完整故事安排约 22～25 幕，每幕通常 55～75 个中文字符，只承载一个主要动作、地点或视觉结论。通过线索、尝试、失败、角色互动、转折、高潮和结尾回顾形成自然的 5～6 分钟叙事；不得机械重复目标词、降低默认 `-15%` 语速、插入大段空白或用无意义静音凑时长。

使用 `storyctl.py` 做重复结构修改，避免手工补丁大型 JSON：

```text
<项目Python> scripts/storyctl.py <项目> init-meta --title <中文标题> --targets <词...>
<项目Python> scripts/storyctl.py <项目> set-visual-bible --style <画风> --palette <配色>
<项目Python> scripts/storyctl.py <项目> add-character <ID> --name <名字> --role <角色> --appearance <外观> --must-keep <固定特征>
<项目Python> scripts/storyctl.py <项目> add-scene <幕ID> --title <内部名> --zh <旁白> --image <路径> --prompt <提示词> --must-show <要求> --action <动作>
<项目Python> scripts/validate_story.py <项目> --stage content
```

只在动作影响剧情理解、目标词识别或角色/道具连续性时写 `visualRequirements.criticalAction`。用 `add-scene --critical-action` 同时提供动作主体、身体部位或工具、作用对象、接触方式、相对位置、运动方向和动作结果；仅在确有必要时用 `--forbid-alternative` 排除容易混淆的替代动作。工具会把这些信息写入结构化合同和提示词。普通背景、光线与装饰仍用自然语言概括，不要逐项锁死。

内容验证成功后自动记录 `story_validated` 并保存输入指纹。修改上游合同后，下游阶段自动变为过期。

## 3. 真实 TTS 时长闸门

在生成角色参考图、测试图和批量插画前，先生成真实 TTS 作为旁白草稿并执行时长预检：

```text
<项目Python> scripts/tts_generate.py <项目> --duration-preflight
```

脚本使用提供者返回的 WordBoundary，记录真实发音时长；`targetPauseSec > 0` 时才插入真实静音，等于 `0` 时完全不走静音插入路径。视觉事件独立使用 `targetVisualDurationSec`，不会为展示词标而修改音频。

预检把目标范围、真实 TTS 时间线和尝试记录原子写入 `build/duration-preflight.json`。低于可接受下限时先增加有意义的线索、尝试、互动或转折；高于上限时精简冗余内容。每次调整后重新运行内容验证和时长预检，最多进行 `durationTarget.maxCreativeAdjustments` 次创作调整。只有状态为 `duration_preflight_ready` 才进入插画阶段。

## 4. 生图、比例纠偏与语义审核

先生成无文字的项目角色参考图，再生成一张测试图。每个首次提示必须写清 `native 16:9`、左右展开的横屏构图、角色和目标物位置、必须出现项、禁止项以及无文字要求。

```text
<项目Python> scripts/image_probe.py <项目> <测试原图>
```

测试通过才批量生成。每张图立即运行：

```text
<项目Python> scripts/normalize_image.py <项目> <生成原图> <幕ID>
```

规格化脚本只以幕ID选择目标图片，文件名从 `story.json` 对应幕的 `image` 字段读取，避免调用方把合格图片写到错误幕。角色参考图使用保留ID `reference`，目标文件名来自 `visualBible.referenceImage`。资产验证会拒绝合同之外的最终图片、清单条目和未被清单引用的原图。

角色参考图和首张测试图始终串行。正式场景先运行 `<项目Python> scripts/image_batch_plan.py <项目>`；默认计划每批最多并行三个互不依赖的场景。前后连续动作、道具状态继承或后一幕参考前图时，在 `add-scene` 中用 `--depends-on` 和 `--serial-reason` 明确记录，计划会改为串行。比例或语义重试使用 `--retry-scene <幕ID>`；限流、报错、图片混淆或连续性/质量下降时使用 `--force-serial`。计划会读取语义审核记录并跳过已通过图片；降级时只把失败项、未完成项和受影响的后续幕列入执行。

若首次源图比例误差超过 1%，不要自行改写提示词；运行：

```text
<项目Python> scripts/image_retry.py <项目> <幕ID> <失败原图>
```

角色参考图或测试图使用自定义项目名并传 `--prompt <原始提示>`。只使用脚本返回的 `retryPrompt` 再生成一次。它会换成宽银幕构图角度，明确排除刚才的实际比例以及常见的 1:1、4:3、3:2、5:4、16:10、9:16、3:4、2:3。第二次仍超过 1% 时停止并报告，不再重试或伪装成16:9。

比例通过不代表内容正确。运行 `visual_review.py init` 建立语义审核清单；用视觉模型或人工逐项核对 `mustShow`、`mustNotShow`、主要动作和连续性，再以 `record` 留下审核者、方法、置信度、观察和问题。首次语义不合格后可重试两次，总共比较三张候选。前两次失败记录为 `retry-required`，第三次仍有偏差则记录 `rejected`，随后选择三张中偏差最小的一张：若偏差轻微且不影响目标词识别、主要角色、核心动作、因果或连续性，以 `accepted-minor` 留下具体偏差后继续；不要暂停询问用户。

只有在候选图与原合同的轻微不一致能通过单幕小改自然消除时，才可运行 `storyctl.py adjust-scene` 微调该幕旁白、提示词或视觉要求。必须保持原地点、角色、目标词序列、故事节拍与结果，不得删除目标词、改换主线或借机重写多幕。修改后重新运行内容验证、语义审核和受影响的 TTS；工具会拒绝在三张候选用尽前调整，也会拒绝幅度过大的旁白修改。

看规格化后的最终图片，再用 `storyctl.py set-marker` 写目标位置、来源、置信度和审核者。全部语义审核通过后运行：

```text
<项目Python> scripts/visual_review.py <项目> status
<项目Python> scripts/validate_story.py <项目> --stage assets
```

资产验证成功后自动记录 `images_ready`。

## 5. 旁白复用

运行项目 Python：

```text
<项目Python> scripts/tts_generate.py <项目>
```

时长预检生成的音频与当前故事输入哈希一致时会直接复用；故事、声音、语速、停顿或视觉策略变化时只重生成受影响内容。脚本原子写入逐字时间和独立的发音/视觉事件。普通重试禁止 `--force`。成功后自动记录 `narration_ready`。

视频音轨只包含标题朗读和中文主体的中英混合旁白；目标词发音属于旁白时间线。渲染前运行 `<项目Python> scripts/validate_story.py <项目> --stage pre-render`。

## 6. 可恢复 QA 与计划式渲染

完整阅读 [references/qa-checklist.md](references/qa-checklist.md)，再运行：

```text
<项目Python> scripts/qa_typecheck.py <项目>
<项目Python> scripts/static_audit.py <项目> --skill <技能目录>
<项目Python> scripts/qa_keyframes.py <项目>
```

QA 脚本只打包一次、只开一个浏览器，逐帧原子保存进度；中断后原命令重跑只补缺帧。它不能代替目检。完成联系表和最终图片审核后显式记录：

```text
<项目Python> scripts/pipeline_state.py <项目> complete visual_qa_ready --detail reviewer=<审核者> --detail method=human|vision-model
```

运行渲染：

```text
<项目Python> scripts/render_story.py <项目>
```

最终渲染通常持续数分钟。单段渲染的调用和等待上限至少设为 20 分钟；超过 9000 帧时，每个计划分段增加 20 分钟上限，并以 `build/render-plan.json` 的 `timeoutSec` 为准。20 分钟是运行上限：成功或明确报错立即返回；工具短暂 yield 或暂时无输出时继续等待真实进程结果；只有进程退出、中断或达到上限才记录失败。中断后保留诚实的失败状态，原命令可安全重跑。

总帧数不超过 9000 时单段渲染；超过时按预定 3000 帧分段。计划绑定完整输入哈希，已有分段只有在输入和逐段解码都匹配时才能复用。控制台只显示阶段和节流进度，完整日志写入 `build/render.log`。

渲染脚本内部完整解码临时 MP4、验收、原子替换正式成片、写报告并记录 `rendered` 与 `mp4_validated`。正常流程不要再重复运行 `validate_mp4.py`。最终视频被外部修改后，先用 `--no-report` 只读复检；只有明确接纳这个外部文件时才加 `--accept-external-video` 更新正式状态。

## 7. 主观试听与交付

从最终 MP4 抽取片头、正文、目标词和中段画面复核，并试听片头、普通叙事、目标词发音场景与高潮。自动响度检测不能冒充实际听感。

```text
<项目Python> scripts/pipeline_state.py <项目> review-audio approved --detail reviewer=<审核者>
```

若当前工具不能理解音频，主观试听保持 `pending`；不得声称真人试听或听感已经确认。交付不依赖主观审核一定通过；它是独立状态：

```text
<项目Python> scripts/pipeline_state.py <项目> delivery completed --detail channel=local
```

最终回复必须读取 `build/report.json`，提供 MP4 绝对路径、目标时长范围、TTS 预检时长、最终实际时长、规格、编码、文件大小、场景与目标词统计、TTS 提供者和声音、SHA-256、最终抽帧、图片规格化与语义审核摘要，并在通过时写“音频技术检查通过”。主观试听的 `pending` 状态只保留在内部数据中；未发生真人试听时不得声称真人试听通过或听感已经确认。
