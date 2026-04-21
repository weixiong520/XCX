# 小程序工具

这个项目名为“小程序工具”，用于管理微信小游戏后台账号，保存登录态，并抓取“未成年人支付退款”页面中的处理截止时间。当前仓库以 Python 桌面版为唯一抓取实现。

## 功能

- 多账号配置管理
- 每个账号单独保存登录态
- 支持在微信后台页面内自动切换账号后抓取
- 支持配置共享浏览器资料目录，复用本机浏览器账号池
- 支持读取“切换账号”弹窗中的账号列表并导入
- 支持自动识别抓取时的当前实际账号名
- 支持单账号抓取、批量抓取、飞书汇总发送
- 支持每日自动抓取并推送

## 依赖

```powershell
python -m pip install -r requirements.txt
```

说明：

- 首次启动桌面程序时，如果缺少 Playwright 浏览器资源，程序会自动联网下载安装 Chromium
- 打包后的安装版默认不再内置 Chromium，以减小包体
- 当前抓取逻辑已按职责拆分为 `fetcher.py` 兼容入口层、`fetcher_switching.py`、`fetcher_session.py`、`fetcher_pipeline.py`、`fetcher_support.py` 与 `fetcher_page_strategy.py`

## 浏览器运行时交付策略

- **默认策略**：安装版不内置 Chromium，首次启动时在线下载到项目运行目录下的 `ms-playwright/`
- **离线策略**：若目标环境无法联网，需要在交付前预置完整的 Playwright Chromium 运行时，确保程序首次启动时不再触发下载
- **适用建议**：
  - 办公网或普通开发环境：使用默认在线安装策略，减小安装包体积
  - 内网、弱网或离线终端：使用离线预置策略，避免首次启动失败

### 离线预置建议

如果目标环境不能联网，建议按以下方式准备离线运行时：

1. 在可联网环境执行 `playwright install chromium`
2. 将生成的 `ms-playwright/` 完整目录与应用一起交付
3. 确保运行目录中存在：
   - `chromium-*`
   - `chromium_headless_shell-*`
   - `ffmpeg-*`
4. 首次启动前确认程序运行目录具备这些资源，避免再触发在线下载

### 标准版与离线版选择建议

- **标准版**：适合办公网络或常规开发环境，优点是安装包更小
- **离线版**：适合内网、弱网、无法联网终端，优点是交付更稳定

## 安装包构建依赖

先安装构建依赖：

```powershell
python -m pip install -r requirements-build.txt
```

项目打安装包时只使用项目目录内的便携版 Inno Setup 编译器，不依赖系统安装版。

固定路径：

- `tools/inno/ISCC.exe`

当前仓库已经准备好项目内 Inno Setup 目录；如果后续重新部署环境，请把完整的 Inno Setup 目录内容放到 `tools/inno/`，不要只复制单个 `ISCC.exe`。

### 构建安装包

```powershell
pwsh ./scripts/build_installer.ps1 -Clean
```

如果本机缺少 `PyInstaller`，构建脚本会直接报错并提示安装 `requirements-build.txt`。

### 构建离线版安装包

如果需要离线版，请先在项目根目录准备完整的 `ms-playwright/`，然后执行：

```powershell
pwsh ./scripts/build_installer.ps1 -Clean -IncludeOfflineChromium
```

说明：

- **标准版**：不内置 Chromium，首次启动在线下载
- **离线版**：安装包内预置 `ms-playwright/`，首次启动不再依赖联网下载

## 启动桌面程序

```powershell
python desktop_main.py
```

## 开发模式启动

如果你在修改 PySide6 界面，希望保存代码后自动重启桌面应用，可以使用：

```powershell
python desktop_dev.py
```

说明：

- 会监听 `desktop_main.py` 和 `desktop_py/**/*.py`
- 检测到文件变化后会自动关闭旧进程并重新启动
- 按 `Ctrl+C` 可停止开发模式

## 桌面版命令行辅助

### 指定账号重新登录

```powershell
python desktop_py_cli.py login --account "账号名称"
```

### 批量抓取全部启用账号

```powershell
python desktop_py_cli.py fetch-all
```

### 抓取并发送飞书汇总

```powershell
python desktop_py_cli.py notify
```

## 桌面版使用方式

1. 打开桌面程序，点击“新增账号”
2. 只填写账号名称；登录态文件路径可以留空，程序会自动生成
3. 选中账号后点击“保存登录态”
4. 在弹出的浏览器里手动登录微信后台
5. 登录完成后等待程序自动保存登录态
6. 如果你希望稳定使用页面内“切换账号”，建议先在“全局设置”中选择共享浏览器资料父目录
7. 程序会在你选择的父目录下自动创建 `browser_profile/`，并把共享浏览器资料统一放在该专用目录内
8. 若资料目录或登录态里已包含多个可切换账号，后续新增其他账号名称时可复用同一份资料
9. 也可以选中一个已登录账号后点击“导入账号列表”，自动读取切换账号弹窗中的账号名
10. 点击“抓取选中账号”或“抓取全部账号”
11. 配置飞书 Webhook 后点击“发送飞书汇总”

## 数据文件

- `data/accounts.json`：账号配置
- `data/settings.json`：全局设置
- `storage/*.json`：各账号登录态
- `output/desktop_py/<账号>/`：抓取产物
- `ms-playwright/`：首次运行后下载的浏览器运行时

## 存储边界

当前版本的配置和抓取结果存储以本地 JSON 文件为主，这个方案只针对当前单机桌面工具场景。

- **适用范围**：
  - 单机使用
  - 单进程写入
  - 轻量配置与抓取结果留存
- **当前不覆盖的能力**：
  - 多人协同
  - 并发写入协调
  - 审计级历史追踪
  - 集中调度与任务队列
- **后续升级触发条件**：
  - 多人共用同一套账号数据
  - 需要集中查看历史抓取记录
  - 需要更强的调度、审计或状态管理能力

## 抓取说明

- 当前版本优先从 iframe 详情页中提取“处理截止时间”
- 会先进入微信后台首页，再自动读取当前 `token` 并拼接反馈页地址
- 会优先尝试从微信后台页面内切换到目标账号
- 若配置了共享浏览器资料目录，会优先复用该目录内的多账号池
- 抓取结果会记录“当前实际账号名”，用于校验切换是否成功
- 如果详情页提取失败，会降级读取 `getuserrefundchecklist` 接口中的候选时间字段
- 若微信页面结构变化，需要同步调整 `desktop_py/core/fetcher.py`

## 本地验证

```powershell
python -m unittest discover -s py_tests -v
```

### 安装包链路最小验证

```powershell
python -m unittest py_tests.test_browser_runtime py_tests.test_build_installer -v
```

## 工程检查

项目根目录已提供 `pyproject.toml`，当前统一使用 `ruff` 承担格式检查与静态检查。

### 格式检查

```powershell
ruff format --check .
```

### 静态检查

```powershell
ruff check .
```

### 类型检查试点

```powershell
python -m mypy
```

### 单元测试与 pytest 校验

```powershell
python -m unittest discover -s py_tests -v
python -m pytest py_tests -q
```

## 推荐本地交付流程

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt
ruff format --check .
ruff check .
python -m mypy
python -m unittest discover -s py_tests -v
python -m pytest py_tests -q
pwsh ./scripts/build_installer.ps1 -Clean
```
