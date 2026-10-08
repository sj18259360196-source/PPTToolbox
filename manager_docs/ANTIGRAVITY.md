# Antigravity 接入

在工具箱的设置中打开 Agent 接入，客户端选择 Antigravity。预览并写入配置后，在 Antigravity 的 Settings → Customizations → Installed MCP Servers 中刷新工具箱服务。旧版 IDE 可从 MCP Servers → Manage MCP Servers → View raw config 查看配置。

默认读取用户目录下的 .gemini/config/mcp_config.json。仅存在旧版 .gemini/antigravity/mcp_config.json 时，继续使用旧位置。界面允许指定其他配置文件。已有 ppt-toolbox-manager 条目会被识别并沿用名称，避免另建重复服务。

程序使用正式安装中的独立 Python 和 agent_bridge.py，继续读取已有管理数据。写入配置时会备份原文件并保留其他 MCP 服务。

先运行本机自检，再复制验证提示词到 Antigravity 对话中发送，完成后返回工具箱检查配置。本机自检只能确认进程、工具发现和实例目录；外部验证必须由 Antigravity 实际调用完成。

已有条目指向其他程序或失效的旧源码位置时，工具箱会阻止自动覆盖。核对后可通过客户端的原始配置入口替换该条目，不应同时保留新旧两条工具箱服务。连接不自动扩大项目权限。

MCP 工具上下文提供当前规则和 Skill 覆盖，本适配不向 Antigravity 的全局规则目录写入静态副本。

配置格式和当前入口依据 https://antigravity.google/docs/mcp 核对。
