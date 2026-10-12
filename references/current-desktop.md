# 当前桌面入口

正式使用从开始菜单启动 PPT Toolbox。程序、管理数据和 PPT 项目分别保存，具体位置以当前 toolbox_context 返回的 instance 与 storage 为准。新电脑需要自行配置 Agent 和 API。

概况页可切换精简版与专业版。精简版不超过 1500 字符，详细要求通过 toolbox_manual 读取 references/agent-production-guide.md。该手册按读取时的用户修改和设置生成；项目进度从 rebuild_status、HANDOFF.md 与 ppttool.md 接续。专业版直接展示完整要求。

MCP 未加载时，先核对开始菜单快捷方式指向的正式安装目录和 location.json 中的数据目录，再用随包解释器读取当前上下文。

```powershell
& "<安装目录>/runtime/python.exe" -B "<安装目录>/app/manager.py" --data-dir "<管理数据目录>" context --profile full
```

读取返回的 Skill、startup_prompt、instance 和 storage。后续调用先 describe 对应工具，按返回的 managed_argv_prefix 执行，保留授权与当前项目范围。不要直接执行原始制作脚本。

软件更新和安装位置见 [桌面安装](../manager_docs/DESKTOP_INSTALLATION.md)。
