# Contributing

感谢你为 Glowfish Reader 贡献代码。本项目以 AGPL-3.0 开源，欢迎社区协作。

## 仓库组织

Glowfish Reader 由四个独立 Git 子模块组装而成：

| 目录 | 仓库职责 |
|---|---|
| `host/` | Windows 桌面集成、打包、校对/文档/导出服务 |
| `ui/` | 阅读器前端 |
| `ocr/` | OCR 服务与公共 API |
| `contracts/` | 跨仓库共享契约 |

模块级改动请提交到对应子模块仓库，再在本仓库通过评审过的 Pull Request 更新对应的 gitlink 与 `workspace-manifest.json` 中的完整 commit SHA。

## 开发流程

1. 从 `main` 拉取最新代码，新建功能分支。
2. 做出改动并编写 / 更新测试。
3. 运行完整验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify.ps1 -Full
```

4. 提交并推送，发起 Pull Request。

## 提交规范

- 请勿提交 OCR 模型、安装器、数据库、凭据、用户文件、构建产物或本地环境。
- 保持 `contracts/` 中的契约在 major 版本内**只增不改**；变更字段语义需新 major 版本与迁移工具。
- 遵循现有代码风格与注释语言（中文注释 + 英文标识符）。

## 测试

- 后端（host / ocr / contracts）：`pytest`
- 前端（ui）：`npm run check`、`npm test`、`npm run build`

## 安全

若发现安全相关问题，请参考 [SECURITY.md](SECURITY.md)。
