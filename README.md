# VRC Transf

Windows 版 VRChat 实时翻译工具。游戏音频的译文显示在桌面窗口，麦克风译文可以通过 OSC 发到 VRChat Chatbox。

## Windows 安装包

打开 [GitHub Releases](https://github.com/zengxhzz/vrc_transf/releases/latest)，在 **Assets** 中下载名称以 `windows-x64.msi` 结尾的文件。双击安装后，从开始菜单打开 **VRC Transf**。安装包自带 Python、图形界面和音频运行库，安装和演示均可离线完成。

首次体验可在 **设置 → 翻译** 选择 **演示（无需 Key）**，点 **完成** 后运行演示。使用实时翻译时需要联网并填写自己的 API Key。卸载可通过 Windows 的 **设置 → 应用** 完成。

## 从源码启动

需要 Windows x64 和 64 位 Python 3.12 至 3.14。按进程采集需要 Windows 构建号 20348 或更高，例如 Windows 11。构建号更低时，游戏音频使用界面中选定的播放设备。

双击 `start.cmd`。首次运行会在项目内创建 `.venv` 并安装依赖。打开 **设置 → 翻译**，选择 **演示（无需 Key）**，点 **完成** 后在主窗口运行演示。演示使用示例文本，不采集音频，也不会自动发到 Chatbox。

## 迷你字幕

点主窗口的 **迷你字幕** 可以打开桌面置顶窗，查看最近两条游戏字幕。按 Esc 或点 **返回双栏** 即可切回。

默认启用 **设置 → 显示 → VRChat 全屏时自动打开迷你字幕**。桌面版 VRChat 在前台全屏时，迷你窗会出现在游戏所在显示器上。退出全屏、关闭游戏或 Alt+Tab 切走时，应用会恢复之前的主窗口状态。手动打开的迷你窗由你关闭。此功能面向 Windows 桌面，推荐使用无边框全屏。

## 接入翻译 API

1. 打开 VRChat，在 Action Menu 的 **Options → OSC → Enabled** 启用 OSC。从应用的 **设置 → Chatbox** 点 **测试 Chatbox**，确认游戏内能看到测试消息。
2. 在 **设置 → 翻译** 选择 **Qwen3.8 LiveTranslate** 和密钥对应的接入方式。**千问 AI 平台 · 中国内地**只需 API Key。选择百炼时，填写匹配地域的 API Key 和 Workspace ID。也可以用环境变量 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_WORKSPACE_ID` 预填。应用不会保存密钥或对话。
3. 在 **设置 → 音频** 选择游戏音频、麦克风和两路目标语言。两路输入可独立启用。关闭 **设置 → Chatbox → 麦克风译文发到 Chatbox** 可以只在本机预览。配置完成后回到主窗口点 **开始翻译**。

游戏音频也可以选指定的 Windows 播放设备。该选项会采集同一设备上的所有播放声音。按进程采集仍会包含 VRChat 的世界音乐和音效。启用云端翻译时，所选音频会发送给选定的千问或百炼服务。

**设置 → 翻译 → 快速断句** 默认开启。两路翻译都按约 350 毫秒的停顿判断句尾，适合轮流聊天。说话时习惯长停顿，或多人经常同时开口，可关闭它，恢复模型默认的说话人分离模式。

Chatbox 使用 `127.0.0.1:9000`，只发送已定稿的麦克风译文。发送间隔为 1.6 秒。间隔内已经排队的相邻短句会按原顺序合并，放不下的另发一条。单条超长译文沿用截断显示，完整内容可以在桌面窗口查看。

## 扩展

`vrc_transf/translation.py` 中的 `Translator` 定义了翻译后端接口。后端接收独立的音频源和目标语言，输出临时或定稿译文。目前有千问实时 WebSocket 适配器和演示后端。界面保留了暂不可用的本地模型选项。

- [千问 AI 平台实时语音翻译文档](https://platform.qianwenai.com/docs/developer-guides/speech/realtime-translation)
- [百炼实时语音翻译文档](https://docs.qwencloud.com/developer-guides/speech/realtime-translation)
- [VRChat Chatbox OSC 文档](https://docs.vrchat.com/docs/osc-as-input-controller#chatbox)

## 开发验证

要重新构建 Windows x64 安装包，使用 64 位 Python 3.13 创建并激活虚拟环境，在仓库根目录执行以下命令。生成的 MSI 位于 `dist` 目录。

```powershell
python -m pip install -r requirements.txt cx-Freeze==8.7.4
python setup.py bdist_msi
```

在项目目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
