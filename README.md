# 小程序工具

这个项目名为“小程序工具”，用于管理微信小游戏后台账号，保存登录态，并抓取“未成年人支付退款”页面中的处理截止时间。当前仓库以 Python 桌面版为主，同时保留了早期的 Node.js 命令行抓取脚本。

## 桌面版功能

- 多账号配置管理
- 每个账号单独保存登录态
- 支持在微信后台页面内自动切换账号后抓取
- 支持配置共享浏览器资料目录，复用本机浏览器账号池
- 支持读取“切换账号”弹窗中的账号列表并导入
- 支持自动识别抓取时的当前实际账号名
- 支持单账号抓取、批量抓取、飞书汇总发送
- 支持每日自动抓取并推送

## 桌面版依赖

```powershell
python -m pip install -r requirements.txt
```

说明：

- 首次启动桌面程序时，如果缺少 Playwright 浏览器资源，程序会自动联网下载安装 Chromium
- 打包后的安装版默认不再内置 Chromium，以减小包体

## 安装包构建依赖

项目打安装包时只使用项目目录内的便携版 Inno Setup 编译器，不依赖系统安装版。

固定路径：

- `tools/inno/ISCC.exe`

当前仓库已经准备好项目内 Inno Setup 目录；如果后续重新部署环境，请把完整的 Inno Setup 目录内容放到 `tools/inno/`，不要只复制单个 `ISCC.exe`。

### 构建安装包

```powershell
pwsh ./scripts/build_installer.ps1 -Clean
```

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
6. 如果你希望稳定使用页面内“切换账号”，建议先在“全局设置”中指定共享浏览器资料目录
7. 若资料目录或登录态里已包含多个可切换账号，后续新增其他账号名称时可复用同一份资料
8. 也可以选中一个已登录账号后点击“导入账号列表”，自动读取切换账号弹窗中的账号名
9. 点击“抓取选中账号”或“抓取全部账号”
10. 配置飞书 Webhook 后点击“发送飞书汇总”

## 数据文件

- `data/accounts.json`：账号配置
- `data/settings.json`：全局设置
- `storage/*.json`：各账号登录态
- `output/desktop_py/<账号>/`：抓取产物
- `ms-playwright/`：首次运行后下载的浏览器运行时

## Node.js 命令行脚本

仓库中仍保留早期的 Node.js 版 CLI，适合直接使用固定链接抓取单页数据。

### 依赖

```powershell
npm install
npx playwright install chromium
```

### 保存登录态

```powershell
npm run auth -- --url "https://mp.weixin.qq.com/"
```

### 抓取截止时间

```powershell
npm run fetch -- --url "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?action=plugin_redirect&plugin_uin=1010&selected=2&token=488439400&lang=zh_CN"
```

### Node 版输出目录

- `output/latest/page.html`
- `output/latest/page.txt`
- `output/latest/responses.json`
- `output/latest/result.json`

## 抓取说明

- 当前版本优先从 iframe 详情页中提取“处理截止时间”
- 会先进入微信后台首页，再自动读取当前 `token` 并拼接反馈页地址
- 会优先尝试从微信后台页面内切换到目标账号
- 若配置了共享浏览器资料目录，会优先复用该目录内的多账号池
- 抓取结果会记录“当前实际账号名”，用于校验切换是否成功
- 如果详情页提取失败，会降级读取 `getuserrefundchecklist` 接口中的候选时间字段
- 若微信页面结构变化，需要同步调整 `desktop_py/core/fetcher.py`

## 本地验证

### Python 测试

```powershell
python -m unittest discover -s py_tests -v
```

### Node 测试

```powershell
npm test
```
