
## 4. 桌面环境开发

### 4.1 窗口管理器 (Compositor)
`ainos-desktop` 使用 `wlroots` 库。要添加新的窗口特效或管理逻辑，请修改 `desktop/ainos-desktop.c` 中的 `xdg_toplevel_map` 和渲染循环。

### 4.2 任务栏与面板
`ainos-panel` 使用 GTK3 开发。要添加新的系统托盘图标或小程序 (Applet)，请修改 `desktop/ainos-panel.c` 中的 `activate` 函数，使用 GTK 布局容器添加新组件。

## 5. AI 工具集成

### 5.1 使用代码生成器
Ainos 提供了强大的命令行代码生成工具：
