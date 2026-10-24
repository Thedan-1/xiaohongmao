# Windows 构建

要求：Windows x64、Python 3.11 x64、.NET Framework C# 编译器、Inno Setup 6、Edge。

```powershell
python bootstrap_build.py
python build_preview.py
python build_installer.py
```

`bootstrap_build.py` 从 Python、NuGet、微软官方地址获取构建依赖；内置 Python 和 WebView2 SDK 使用固定校验值，微软安装组件检查 Authenticode 签名。构建使用 `release-config.json` 中的版本号。

输出：`release/小红帽-版本-免安装公开版.zip` 和 `release/小红帽-Windows-x64-v版本-普通版-安装.exe`。普通版不需要本地密钥文件。

## 验证

```powershell
python -m unittest test_updater test_ai_settings test_ai_settings_http test_search_readiness -q
python -m unittest test_updates_ui test_settings_ui -q
python test_installer_v06.py
```

单元 / UI 测试使用临时数据库或拦截页面。安装测试使用单独的测试 AppId 和安装目录，不应覆盖正式安装。请勿把真实平台发送当作自动化 CI 测试。

`build_preview.py --internal` 为历史内部构建入口，包含默认 Key，不允许作为公开 Release 资产。发布脚本只接收明确不含密钥和用户数据的普通包。
