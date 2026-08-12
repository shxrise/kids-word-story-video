---
name: kids-word-story-video
description: 为数量灵活的英语目标词制作完整儿童故事视频：先强制展示确认单，确认后原创故事，生成并语义审核项目专属角色与稳定16:9插画，使用默认温和女声、可配置目标词停顿（默认0秒）、大号半透明词标、少量音效和计划式Remotion流水线，输出固定1280×720、20fps宽屏MP4并完整验收。用户提出儿童单词故事视频、把单词做成故事动画、沿用固定720p样式或批量复用该流程时使用。
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
- 插画为静态全彩儿童绘本，通常 18–25 幕。禁止文生视频、图生视频和 GIF 拼接。
- 中文主体旁白中仅目标词保留英文；每词至少自然出现两次，并对应可见对象、人物、部位或动作。
- 目标词停顿默认 `0` 秒，即不插入静音；保留可配置能力，用户可改为 `0.3`、`1.0` 等非负秒数。词标从读词开始显示到可选停顿结束。
- 半透明词标默认使用放大两级的 `36px` 英文字号，并同步放大背景内边距；不得遮挡字幕或关键动作。
- 原图比例偏差不超过 `1.0%` 时，以 Lanczos 轻微规格化，不询问用户；禁止裁切、补边和明显拉伸。

## 1. 建立项目与统一工具链

用户确认后加载 Codex 工作区依赖。把返回的 Python、Node、pnpm 路径一次性传给体检脚本；脚本把工具链保存到项目 `build/toolchain.json`，后续脚本自动复用，不再依赖临时 PATH。

```text
<Python> scripts/new_project.py --output <绝对项目路径>
<Python> scripts/doctor.py --project <项目> --repair --python <Python> --node <Node> --pnpm <pnpm>
<项目Python> scripts/pipeline_state.py <项目> status
```

`doctor.py --repair` 只能创建项目 `.venv`、安装锁定依赖和项目 `node_modules`；不得修改系统 PATH、安装系统软件或请求管理员权限。磁盘低于 2GB 时拒绝，低于 8GB 时警告。

## 2. 创作 v2 故事合同

完整阅读 [references/story-contract.md](references/story-contract.md)。先整体创作故事，再拆分镜；不得按词表机械排列。每个项目动态建立 `visualBible`，不得复用模板角色。

使用 `storyctl.py` 做重复结构修改，避免手工补丁大型 JSON：

```text
<项目Python> scripts/storyctl.py <项目> init-meta --title <中文标题> --targets <词...>
<项目Python> scripts/storyctl.py <项目> set-visual-bible --style <画风> --palette <配色>
<项目Python> scripts/storyctl.py <项目> add-character <ID> --name <名字> --role <角色> --appearance <外观> --must-keep <固定特征>
<项目Python> scripts/storyctl.py <项目> add-scene <幕ID> --title <内部名> --zh <旁白> --image <路径> --prompt <提示词> --must-show <要求> --action <动作>
<项目Python> scripts/validate_story.py <项目> --stage content
```

内容验证成功后自动记录 `story_validated` 并保存输入指纹。修改上游合同后，下游阶段自动变为过期。

## 3. 生图、比例纠偏与语义审核

先生成无文字的项目角色参考图，再生成一张测试图。每个首次提示必须写清 `native 16:9`、左右展开的横屏构图、角色和目标物位置、必须出现项、禁止项以及无文字要求。

```text
<项目Python> scripts/image_probe.py <项目> <测试原图>
```

测试通过才批量生成。每张图立即运行：

```text
<项目Python> scripts/normalize_image.py <项目> <生成原图> assets/scene-01.png
```

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

## 4. 旁白与音效

运行项目 Python：

```text
<项目Python> scripts/tts_generate.py <项目>
```

脚本使用提供者返回的 WordBoundary；`targetPauseSec > 0` 时插入对应时长的真实静音，等于 `0` 时完全跳过静音插入。脚本原子写入逐字时间和词标事件，并按包含提供者、声音、语速、停顿和高亮策略的输入哈希续跑。普通重试禁止 `--force`。成功后自动记录 `narration_ready`。

完整阅读 [references/sound-design.md](references/sound-design.md)。每幕 0–2 个音效；旁白优先，无背景音乐。用 `storyctl.py add-sfx` 写时间线，本地音效先写可复现配方，再运行：

```text
<项目Python> scripts/generate_sfx.py <项目>
<项目Python> scripts/validate_story.py <项目> --stage pre-render
```

即使音效关闭，也保留空配方并运行生成脚本，使 `sfx_ready` 有明确证据。

## 5. 可恢复 QA 与计划式渲染

完整阅读 [references/qa-checklist.md](references/qa-checklist.md)，再运行：

```text
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

总帧数不超过 9000 时单段渲染；超过时按预定 3000 帧分段。计划绑定完整输入哈希，旧分段只有在输入和逐段解码都匹配时才能复用。控制台只显示阶段和节流进度，完整日志写入 `build/render.log`。

渲染脚本内部完整解码临时 MP4、验收、原子替换正式成片、写报告并记录 `rendered` 与 `mp4_validated`。正常流程不要再重复运行 `validate_mp4.py`。最终视频被外部修改后，先用 `--no-report` 只读复检；只有明确接纳这个外部文件时才加 `--accept-external-video` 更新正式状态。

## 6. 主观试听与交付

从最终 MP4 抽取片头、正文、目标词和中段画面复核，并试听片头、普通叙事、目标词音效场景与高潮。自动响度检测不能冒充实际听感。

```text
<项目Python> scripts/pipeline_state.py <项目> review-audio approved --detail reviewer=<审核者>
```

若当前工具不能理解音频，保持 `pending`，如实交付为“自动音频 QA 通过，待人工试听”。交付不依赖主观审核一定通过；它是独立状态：

```text
<项目Python> scripts/pipeline_state.py <项目> delivery completed --detail channel=local
```

最终回复必须读取 `build/report.json`，提供 MP4 绝对路径、时长、规格、编码、文件大小、场景与目标词统计、音效数、TTS 提供者和声音、SHA-256、图片规格化与语义审核摘要，以及技术验收和主观试听各自状态。
