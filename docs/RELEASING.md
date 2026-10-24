# GitHub Releases 发布手册

仓库：`Thedan-1/xiaohongmao`。同一正式 Release 放置两种 Windows x64 包。

## 每次更新

1. 修改 `release-config.json` 的 `version`，例如 `0.7.1`；记录本轮改动和验证结果。
2. 运行回归检查并构建预览包、普通安装包。
3. 准备 Markdown 发布说明，运行：

```powershell
python publish_release.py --notes docs/release-notes.md
```

默认创建 **Draft**：先上传所有文件，再在 GitHub Releases 中审阅并发布。需要一次完成发布时显式加 `--publish`。已有同版本不会覆盖，修复应发布更高版本。

也可以在 Actions 的 **Release** 工作流中输入发布说明并构建；默认同样保留为草稿。首次线上版本发布之后，客户端才能通过 `/releases/latest` 获取更新。

## 资产约定

| 名称 | 用途 |
| --- | --- |
| `xiaohongmao-x.y.z-windows-x64-setup.exe` | 安装版升级 |
| `xiaohongmao-x.y.z-windows-x64-preview.zip` | 免安装预览升级 |
| `SHA256SUMS.txt` | 人工下载校验 |
| `setup.manifest.json` | 普通包审计清单 |

客户端使用 GitHub Releases API 返回的 SHA-256 digest，不把自填校验文件当成独立可信签名。不向用户分发 GitHub Token；公开仓库下载不需要每个人登录 GitHub。

## 版本与渠道

正式标签为 `vX.Y.Z`。当前客户端只检测正式版本，Draft 与 Prerelease 不作为更新。预览版在这里表示免安装交付形式，不表示自动接收测试版渠道。

建议在 GitHub 仓库设置中启用 Immutable Releases：资产完整上传到草稿后再发布。不要修改已发布版本的二进制；发现问题发布新版本。

## 数据与回退

安装版沿用 AppId、原安装路径与用户数据目录。预览版以新目录和最后切换指针的方式更新，保留上版程序。发布新版本不会替用户升级，也不会停止任务；需要用户选择下载和重启。

官方文档：[管理 Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)、[Releases API](https://docs.github.com/en/rest/releases/releases)。
