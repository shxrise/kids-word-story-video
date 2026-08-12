# 儿童故事音效设计

## 目标与密度

音效帮助理解动作和环境，不能抢旁白。每幕允许 0–2 个；安静、温暖或信息密集的场景可以为 0。默认 `standard` 全片平均约 1 个：

- `off`：不添加音效。
- `light`：全片约 8–15 个。
- `standard`：平均每幕约 1 个。
- `rich`：多数场景 1–2 个，但仍保留安静段落。

优先选择明确动作声和轻环境声，例如脚步、开门、拉链、车辆到站、动物叫声、苹果落地。目标词有自然声音时优先对应；`face`、`dad` 等没有自然声音的词不得硬配。

## 时间与混音

- 不让明显音效覆盖目标词发音。目标词发音结束时间为 `event.start + event.duration - meta.targetPauseSec`；匹配的轻音效可在其后的停顿中出现。
- `volume` 通常使用 0.12–0.22，硬上限 0.28。渲染器在目标词发音期间再乘以 0.3 自动压低。
- 20fps 成片使用至少 0.10 秒淡入和 0.15 秒淡出，短音效优先 0.15–0.25 秒，避免低帧率音量控制出现明显台阶、爆音或硬切。
- 同时最多两个音效；避免长时间持续的高频、低频轰鸣或循环环境音。
- 不添加背景音乐，除非用户明确要求。

## 素材与来源

优先使用许可清楚、可保存来源的短音效。不要从搜索结果页或视频中直接截取未知版权声音。每个素材在 `sfxCatalog` 记录文件路径、许可证或“本地生成”说明和来源页面；相同素材可跨场景复用。

本地生成音效必须把可复现配方写入 `public/story/sfx-recipes.json`，再运行 `scripts/generate_sfx.py <项目>`。配方至少包含资产ID、波形类型、时长、频率或噪声参数和固定随机种子；不得只保留最终WAV。

```json
{
  "sampleRate": 24000,
  "assets": [
    {
      "id": "soft-chime",
      "file": "sfx/soft-chime.wav",
      "kind": "tone",
      "durationSec": 0.7,
      "frequencies": [660, 880],
      "volume": 0.55,
      "attackSec": 0.03,
      "decay": 2.0,
      "seed": 20260811
    }
  ]
}
```

`kind` 只使用 `tone`、`sweep`、`noise` 或 `hybrid`；相同配方和种子必须生成相同PCM波形。

## 数据格式

```json
{
  "sfxCatalog": {
    "door-open": {
      "src": "sfx/door-open.mp3",
      "license": "CC0",
      "source": "素材原始页面"
    }
  },
  "scenes": [
    {
      "id": "01",
      "sfx": [
        {
          "assetId": "door-open",
          "startSec": 4.8,
          "durationSec": 0.9,
          "volume": 0.18,
          "fadeInSec": 0.12,
          "fadeOutSec": 0.18,
          "purpose": "角色轻轻推开房门"
        }
      ]
    }
  ]
}
```
