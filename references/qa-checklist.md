# 渲染与验收清单

## 1. 环境与静态审计

依次运行：

```text
python <skill>/scripts/doctor.py --project <project>
python <skill>/scripts/pipeline_state.py <project> status
python <skill>/scripts/validate_story.py <project> --stage pre-render --no-state
pnpm exec tsc --noEmit
python <skill>/scripts/static_audit.py <project> --skill <skill>
```

搜索 Skill 与项目源码，确认不存在：

- 3:2 插画、`markerYForWidescreen`、`objectFit: 'cover'` 或其他裁切/坐标重映射。
- 非等比拉伸、自动补边、黑白阶段、彩色 wipe、文生视频、图生视频或 GIF。
- 圆圈高亮、正文场景编号、画外信息区或持续显示的标题。

## 2. 图片与连续性

- 所有最终场景图像必须为1280×720；`image-sources.json` 必须记录每张原图、哈希、实际尺寸、比例偏差和缩放因子。
- 源图比例偏差不超过1.0%时允许自动稳定规格化；超过阈值的源图不得进入成片。
- 角色参考图是本故事新生成的，不含固定模板角色和图片内文字。
- 按 `visualBible` 和联系表检查主要角色的体型、脸部、毛发或发型、服装、颜色和标志性配件。
- 每幕查看最终图片后确认 marker 落在正确对象上，没有遮挡字幕或离开画面。`accepted-minor` 只允许在首图加两次重试都失败后使用，必须写明偏差且不影响目标词识别、核心动作与连续性。

## 3. 关键帧与时间

先运行 `scripts/qa_keyframes.py <project>` 生成 `qa/manifest.json`、增量进度、状态帧和 `qa/target-contact-sheet.png`，再逐张目检。脚本使用单次打包和单浏览器批量出图；中断后重跑只补缺帧。它不能替代对目标对象和角色连续性的视觉判断。

- 片头中段：第一幕插画全屏、全中文标题存在，能听到标题中文读音，没有正文字幕。
- `introAudioDurationSec` 后的正文首帧：标题已消失，正文画面、旁白和字幕立即开始，没有固定等待或音频重叠。
- 每幕第一个目标词：按 `targetHighlights[0].start` 和累计场景帧渲染联系表，逐一核对词标与对象。
- 任选一个词标检查读词中段和事件结束后一帧：前者显示，后者消失。仅当 `targetPauseSec > 0` 时再检查停顿中段，词标应继续显示。
- 字幕位于画内底部、字号克制、没有越界；词标使用默认 36px 字号和半透明背景，不完全遮挡目标物。

场景全局起始帧：

```text
ceil(introAudioDurationSec * fps)
+ 前面所有场景 ceil(audioDurationSec * fps) 的总和
```

## 4. 音效验收

- 每幕 0–2 个音效，没有为了凑数破坏安静或情绪段落。
- 默认全片平均约 1 个；对应目标词时自然，不给 `face`、`dad` 等词硬配声音。
- 所有素材文件存在，`sfxCatalog` 记录许可证和来源；没有未知版权素材。
- 音效不覆盖目标词发音；目标词发音重叠区自动压低，普通音量不超过 0.28。
- 实际听取至少四段：片头、普通叙事、含目标词匹配音效的场景和高潮。确认旁白清晰、没有爆音、硬切或音效堆叠。

## 5. 最终渲染与对抗式复核

使用 `render_story.py` 渲染后确认；脚本已经执行完整 `validate_mp4` 验收，正常流程不要重复运行独立验证：

- 正常5–6分钟项目应走单次渲染；仅总帧数超过9000时按预定3000帧分段，分段清单和完成状态必须写入 `build/`。
- 恰好一路 H.264 视频和一路 AAC 音频，20fps、1280×720。
- `ffmpeg -v error -i story.mp4 -f null -` 完整解码无输出且退出码为 0。
- 从最终编码后的 MP4 抽取片头、正文首帧、目标词时刻和中段画面复核。
- 确认实际帧数等于故事时间线计算帧数，音视频时长误差不超过1帧；记录文件字节数和 SHA-256。
- 无音频理解工具时，把主观试听标为待人工确认，不得用响度检测冒充实际听取。

交付前从失败角度检查：是否有非目标英文、英文标题、词频不足、事件数量不匹配、错误 marker、音频假停顿、词标提前消失、角色漂移、图片裁切/拉伸/补边、音效抢旁白、标题残留，或只检查预览而未完整解码最终 MP4。
