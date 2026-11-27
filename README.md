# VRC Transf

Windows 版 VRChat 实时翻译工具。游戏音频的译文显示在桌面窗口，麦克风译文可以通过 OSC 发到 VRChat Chatbox。

## 启动

需要 Windows x64 和 64 位 Python 3.12 至 3.14。按进程采集需要 Windows 构建号 20348 或更高，例如 Windows 11。构建号更低时，游戏音频使用界面中选定的播放设备。

双击 `start.cmd`。首次运行会在项目内创建 `.venv` 并安装依赖。打开 **设置 → 翻译**，选择 **演示（无需 Key）**，点 **完成** 后在主窗口运行演示。演示使用示例文本，不采集音频，也不会自动发到 Chatbox。

## 接入翻译 API

1. 打开 VRChat，在 Action Menu 的 **Options → OSC → Enabled** 启用 OSC。从应用的 **设置 → Chatbox** 点 **测试 Chatbox**，确认游戏内能看到测试消息。
2. 在 **设置 → 翻译** 选择 **Qwen3.8 LiveTranslate** 和密钥对应的接入方式。**千问 AI 平台 · 中国内地**只需 API Key。选择百炼时，填写匹配地域的 API Key 和 Workspace ID。也可以用环境变量 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_WORKSPACE_ID` 预填。应用不会保存密钥或对话。
3. 在 **设置 → 音频** 选择游戏音频、麦克风和两路目标语言。两路输入可独立启用。关闭 **设置 → Chatbox → 麦克风译文发到 Chatbox** 可以只在本机预览。配置完成后回到主窗口点 **开始翻译**。

游戏音频也可以选指定的 Windows 播放设备。该选项会采集同一设备上的所有播放声音。按进程采集仍会包含 VRChat 的世界音乐和音效。启用云端翻译时，所选音频会发送给选定的千问或百炼服务。

Chatbox 使用 `127.0.0.1:9000`，只发送已定稿的译文。长句在 Chatbox 内会截断，完整译文可以在桌面窗口查看。

## 扩展

`vrc_transf/translation.py` 中的 `Translator` 定义了翻译后端接口。后端接收独立的音频源和目标语言，输出临时或定稿译文。目前有千问实时 WebSocket 适配器和演示后端。界面保留了暂不可用的本地模型选项。

- [千问 AI 平台实时语音翻译文档](https://platform.qianwenai.com/docs/developer-guides/speech/realtime-translation)
- [百炼实时语音翻译文档](https://docs.qwencloud.com/developer-guides/speech/realtime-translation)
- [VRChat Chatbox OSC 文档](https://docs.vrchat.com/docs/osc-as-input-controller#chatbox)

## 开发验证

在项目目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
