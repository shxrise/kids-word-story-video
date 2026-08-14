# 参与贡献 / Contributing

感谢你愿意改进 Kids Word Story Video。这个项目优先保持稳定、简单和可复现。

## 提交问题

- 功能异常请使用 Bug 模板，并附上操作系统、Python/Node 版本、复现步骤和已脱敏的错误信息。
- 新想法请使用功能建议模板，说明实际使用场景和预期结果。
- 安全问题不要公开提交 Issue，请按 [SECURITY.md](SECURITY.md) 私下报告。

## 提交代码

1. 从 `main` 创建短期分支。
2. 保持改动聚焦，不提交密钥、生成视频、依赖目录、缓存或临时产物。
3. Python 代码至少运行 `python -B scripts/self_test.py`。
4. 修改 Remotion 模板时，在 `assets/remotion-template` 安装锁定依赖并运行 `node node_modules/typescript/bin/tsc --noEmit`。
5. 提交 Pull Request，清楚说明动机、改动、验证结果和兼容性影响。

含非 ASCII 字符的 PowerShell 脚本必须使用 UTF-8 BOM，并兼容 Windows PowerShell 5.1。

---

Thank you for improving Kids Word Story Video. The project favors stability, simplicity, and reproducibility.

- Use the issue templates for bugs and feature requests.
- Never include secrets, generated videos, dependency folders, caches, or temporary artifacts.
- Run `python -B scripts/self_test.py`; for Remotion changes, also run the TypeScript check described above.
- Open a focused pull request that explains the motivation, changes, validation, and compatibility impact.
- Report security issues privately as described in [SECURITY.md](SECURITY.md).
