# 项目说明

这是 `kids-word-story-video` Codex 技能的唯一正版目录。技能入口为 `SKILL.md`，可复用逻辑放在 `scripts/`，按需参考资料放在 `references/`，Remotion 模板放在 `assets/remotion-template/`。

## 维护规则

- 修改前先阅读 `SKILL.md` 及相关脚本或参考资料，保持改动聚焦。
- 不提交密钥、生成视频、依赖目录、缓存或临时测试产物。
- Python 代码至少进行无缓存语法检查；涉及流程行为时运行相关自测。
- 修改默认参数时同步检查 `SKILL.md`、项目生成脚本、模板和验证脚本，避免默认值不一致。
- PowerShell 脚本须兼容 Windows PowerShell 5.1；含非 ASCII 字符时使用 UTF-8 BOM。

## 当前状态

- 技能结构已建立并经过实际视频流程测试。
- Git 仓库以此目录为根，默认分支为 `main`。
- 已发布至 `https://github.com/shxrise/kids-word-story-video`，后续通过 Git 提交和推送持续维护。

## 近期 TODO

- 保持 `README.md` 的中英文说明与技能实际能力一致。
- 在后续真实使用中持续验证图片重试、词标显示和零停顿行为。
