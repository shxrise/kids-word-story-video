# 故事、视觉与数据合同

## 1. 故事创作

- 接受数量灵活的英文目标词和可选偏好或大纲。保留用户拼写，不擅自复数化或改变时态。
- 只有目标词时，先寻找适合整组词的主角、愿望或任务和核心趣味，再创作故事；不要按单词列表逐项安排场景。
- 默认适合 4～7 岁儿童，轻松、温暖、有趣。要求是创作方向而非僵硬评分表，高能力模型应保留充分自由。
- 有大纲时把它视为故事素材，只修正词频不足、非目标英文、因果断裂、单幕动作过多和目标物不可见等问题。

故事遵循五项软原则：

1. 故事优先，不做单词展示幻灯片。
2. 起因推动发展，包含儿童能理解的小问题、小高潮、解决和完整收尾。
3. 目标词在不同动作或关系中自然重复，不机械复读。
4. 目标词出现时对应对象、人物、部位或动作清楚可见，不进行课堂式中文释义。
5. 角色、道具、地点和事件连续，普通叙事、发现、高潮与结尾有节奏变化。

## 2. 语言和分镜

- `scene.zh` 同时是字幕和 TTS 文本；主体必须是中文，英文正则词元只能来自 `meta.pauseTargets`。
- 禁止完整英文句子和非目标英文专名。使用自然混合句，例如：`爸爸打开 bag，发现一个圆圆的 apple。`
- 每个目标词至少出现 2 次，通常自然出现 3～5 次；每次必须能在该幕画面中定位。
- `meta.introTitle` 必须是自然的全中文标题，不含英文字母、目标词或数字。
- 通常 18～25 幕，推荐约 21 幕；不为凑数破坏故事。每幕通常 45～75 个中文字符，只承载一个主要动作、地点或视觉结论。
- 旁白顺序必须与画面内容一致；地点、主体或主要动作明显变化时拆幕。
- 总时长由故事、旁白和目标词停顿自然决定，不机械平均每幕长度。

## 3. 每个项目动态生成视觉设定

故事确定后创建本项目自己的 `visualBible`，不得从 Skill 模板继承任何具体角色；不同视频的角色设定彼此独立。

只记录反复出现的主角、主要配角和关键固定特征：

```json
{
  "visualBible": {
    "stylePrompt": "全片统一的画风、光线和质感",
    "palette": "本故事专属主色与环境色",
    "referenceImage": "reference/characters.png",
    "characters": [
      {
        "id": "hero",
        "name": "本故事角色名",
        "role": "主角",
        "appearance": "物种或年龄感、体型、脸部、毛发或发型、服装、配色",
        "mustKeep": ["跨幕绝不能变化的特征", "标志性配件"]
      }
    ]
  }
}
```

生成一张本项目专属、无文字的角色参考图。每幕通过 `characterIds` 声明出现的主要角色；场景提示词重复必要外观，并在主要角色出现时使用参考图。一次性路人无需建立完整设定。

## 4. 稳定16:9插画

- 插画和成片固定为 `1280×720`、`20fps`，不提供其他规格。
- 每幕提示词必须明确写 `native 16:9`，并说明角色位置、动作、道具、环境和目标物位置。
- 图片内禁止文字、字母、数字、Logo 和水印。
- 生成后读取真实尺寸。源图纵横比相对16:9偏差不超过1.0%时，使用 Lanczos 自动规格化为1280×720，不询问用户；首次超过阈值时运行 `image_retry.py`，只按它生成的宽银幕纠偏提示再试一次。第二次仍超标时停止并报告。
- 保存原图、哈希、实际尺寸、比例偏差和缩放因子；禁止裁切、补边和接收明显错误比例。
- `targetMarkers.x/y` 是最终1280×720图片的百分比坐标，必须看图后填写。

## 5. story.json 核心字段

新项目的 `story.json` 必须引用同目录 `story.schema.json`。Schema 供 IDE 和外部工具做基础结构检查；`validate_story.py` 继续负责词频、跨文件、图片哈希、语义审核、音频和时间线等无法只靠 JSON Schema 表达的规则。

核心元数据（停顿时长可配置）：

```json
{
  "$schema": "story.schema.json",
  "meta": {
    "category": "儿童英语",
    "series": "故事标题",
    "width": 1280,
    "height": 720,
    "imageWidth": 1280,
    "imageHeight": 720,
    "fps": 20,
    "imageNormalization": "stable-lanczos",
    "imageAspectTolerancePct": 1.0,
    "schemaVersion": 2,
    "ttsProvider": "edge",
    "voice": "zh-CN-XiaoxiaoNeural",
    "rate": "-15%",
    "targetPauseSec": 0.0,
    "highlightSec": 1.0,
    "highlightThroughPause": true,
    "sfxDensity": "standard",
    "introTitle": "全中文故事标题",
    "pauseTargets": ["数量灵活的目标词"]
  }
}
```

不要手写 `introDurationSec`；TTS 脚本根据标题音频写入。

每幕在 TTS 前至少包含：

```json
{
  "id": "01",
  "title": "内部场景名，不在成片显示",
  "zh": "中文主体混合旁白",
  "en": "",
  "image": "assets/scene-01.png",
  "imagePrompt": "native 16:9 全彩绘本插画提示词",
  "characterIds": ["hero"],
  "visualRequirements": {
    "mustShow": ["必须清楚出现的角色、目标物和位置"],
    "mustNotShow": ["本幕禁止出现的角色、物体、文字和动作"],
    "action": "本幕唯一主要动作",
    "continuity": ["跨幕必须保持的外观和道具状态"]
  },
  "targetMarkers": {
    "apple": {"x": 55, "y": 62, "size": 140, "source": "visual-review", "confidence": 1.0, "reviewer": "审核者"}
  },
  "sfx": []
}
```

`size` 是兼容字段，词标不绘制圆圈。半透明词标默认用 36px 英文字号，比旧默认 28px 放大两个 4px 级别。音效和 `sfxCatalog` 格式见 [sound-design.md](sound-design.md)。TTS 脚本负责写入标题音频与实际时长，以及各幕 `audio`、`audioDurationSec`、`zhChars`、`enChars` 和 `targetHighlights`。

## 6. 内容审计

生成图片前确认：

- `pauseTargets` 非空、无重复，恰好是用户给定的目标词；不限定总数。
- 标题全中文；正文所有英文词元都属于目标词。
- 每个目标词至少出现 2 次，每幕目标词均能被当前画面定位。
- 场景数和节奏服务故事，画面不长期滞后于旁白。
- `visualBible` 完全来自本故事，角色 ID 唯一，每个角色有明确固定特征。
- 所有提示词要求原生 16:9；所有最终插画为1280×720，原图规格化过程可追溯。
- 每幕都有 `visualRequirements`；最终图片的语义审核记录仍匹配当前图片与当前要求。首图失败后最多重试两次；三张都偏差时比较后采用偏差最小者，以 `accepted-minor` 记录不影响大局的具体偏差，或仅对该幕做受约束的小幅调整并重新验证。不得改变目标词序列、主要角色、故事主线、因果结果或多幕连续性。
- 每幕音效不超过 2 个，素材来源和许可证可追溯。

`targetPauseSec` 必须是非负数。默认 `0.0` 表示不插入静音；`0.3`、`1.0` 等正值继续插入真实静音，词标覆盖读词和该停顿。可用 `storyctl.py <项目> set-meta targetPauseSec 0.3` 修改。

三张候选都偏差时，优先选择最接近原合同的图片。若轻微调整单幕更自然，使用：

```text
<项目Python> scripts/storyctl.py <项目> adjust-scene <幕ID> --zh <微调旁白> --prompt <微调提示词> --action <微调动作> --replace-must-show <旧要求> <新要求> --reason <原因>
```

只传需要改变的字段。`--replace-must-show`、`--replace-must-not-show` 和 `--replace-continuity` 都只允许把一条现有要求替换成措辞接近的新要求，不接受整组重写。命令要求该幕已经用尽两次语义重试，限制旁白改动幅度并保持英文目标词序列；之后重新运行 `validate_story.py --stage content`、`visual_review.py init` 和该幕审核。若 TTS 已生成，按输入哈希正常重跑 `tts_generate.py`，不要用 `--force`。
