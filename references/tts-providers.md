# TTS 提供者

## 默认：edge

`edge` 使用 `edge-tts`，无需 API 密钥，适合个人学习、原型和教学。它依赖在线消费者服务，不保证稳定性、可用性或限流；公开项目必须如实说明这一点，不要把它描述成有商业 SLA 的官方接口。

默认配置：

```json
{"ttsProvider": "edge", "voice": "zh-CN-XiaoxiaoNeural", "rate": "-15%"}
```

## 可选：azure

`azure` 使用 Microsoft Azure Speech SDK，适合需要正式服务条款和商业支持的使用者。安装可选依赖：

```text
python scripts/doctor.py --project <项目> --repair --tts-provider azure
```

使用环境变量提供凭据，禁止写入项目、报告、故事 JSON 或 Git：

```text
AZURE_SPEECH_KEY=<secret>
AZURE_SPEECH_REGION=<region>
```

兼容 `SPEECH_KEY` 和 `SPEECH_REGION`。两个提供者都必须返回单词边界；没有边界就失败，禁止退化成手工估算目标词时间。

## 共同合同

- 提供者、声音、语速、文本、目标词和音频停顿进入音频输入哈希；视觉展示策略使用独立时间哈希，调整词标时可复用音频。
- 切换提供者或声音后自动重生成受影响音频。
- `targetPauseSec` 默认是 0，不插入静音；设为 0.3、1.0 等正值时由 FFmpeg 插入精确静音，不依赖标点或 TTS 服务的停顿习惯。
- `targetVisualDurationSec` 默认是 1.2 秒，只控制词标最短展示时间，不修改音频或 WordBoundary。
- 网络错误按有限退避重试，默认三次；仍失败时保留已完成场景供下次续跑。
