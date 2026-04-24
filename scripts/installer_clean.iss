#ifndef MyAppName
  #define MyAppName "小程序工具"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef MyAppPublisher
  #define MyAppPublisher "本地构建"
#endif
#ifndef MyAppExeName
  #define MyAppExeName "小程序工具.exe"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\build\installer-source\小程序工具"
#endif
#ifndef MyOutputBaseFilename
  #define MyOutputBaseFilename "小程序工具"
#endif

[Setup]
AppId={{D2FF7E71-2A97-4F97-AB7B-4F1EA1A5B1F2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\dist\installer
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupWindowTitle=安装 - %1
SetupAppTitle=安装程序
SetupLdrStartupMessage=即将安装 %1。是否继续？
SetupFileMissing=安装目录中缺少文件 %1。请修复此问题，或重新获取完整安装包。
SetupFileCorrupt=安装文件已损坏。请重新获取完整安装包。
SetupFileCorruptOrWrongVer=安装文件已损坏，或与当前安装程序版本不兼容。请修复此问题，或重新获取完整安装包。
SetupAlreadyRunning=安装程序已在运行。
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonOK=确定
ButtonCancel=取消
ButtonYes=是(&Y)
ButtonYesToAll=全部是(&A)
ButtonNo=否(&N)
ButtonNoToAll=全部否(&O)
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&B)...
ButtonWizardBrowse=浏览(&R)...
ButtonNewFolder=新建文件夹(&M)
AboutSetupMenuItem=关于安装程序(&A)...
AboutSetupTitle=关于安装程序
AboutSetupMessage=%1 版本 %2%n%3%n%n%1 主页：%n%4
ExitSetupTitle=退出安装
ExitSetupMessage=安装尚未完成。如果现在退出，程序将不会被安装。%n%n以后可以重新运行安装程序完成安装。%n%n确定要退出安装吗？
SetupAppRunningError=安装程序检测到 %1 正在运行。%n%n请先关闭所有相关程序，然后点击“确定”继续，或点击“取消”退出安装。
UninstallAppRunningError=卸载程序检测到 %1 正在运行。%n%n请先关闭所有相关程序，然后点击“确定”继续，或点击“取消”退出卸载。
ClickNext=点击“下一步”继续，或点击“取消”退出安装。
WelcomeLabel1=欢迎使用 [name] 安装向导
WelcomeLabel2=此向导将在你的电脑上安装 [name/ver]。%n%n建议继续前关闭其他应用程序。
WizardSelectDir=选择安装位置
SelectDirDesc=[name] 要安装到哪里？
SelectDirLabel3=安装程序将把 [name] 安装到以下文件夹。
SelectDirBrowseLabel=点击“下一步”继续。如果要选择其他文件夹，请点击“浏览”。
DiskSpaceGBLabel=至少需要 [gb] GB 可用磁盘空间。
DiskSpaceMBLabel=至少需要 [mb] MB 可用磁盘空间。
DiskSpaceWarningTitle=磁盘空间不足
DiskSpaceWarning=安装至少需要 %1 KB 可用空间，但所选磁盘当前只有 %2 KB 可用。%n%n是否仍要继续？
WizardSelectTasks=选择附加任务
SelectTasksDesc=需要执行哪些附加任务？
SelectTasksLabel2=请选择安装 [name] 时要执行的附加任务，然后点击“下一步”。
WizardReady=准备安装
ReadyLabel1=安装程序已准备好开始将 [name] 安装到你的电脑。
ReadyLabel2a=点击“安装”开始安装；如需查看或修改设置，请点击“上一步”。
ReadyMemoTasks=附加任务：
WizardPreparing=正在准备安装
PreparingDesc=安装程序正在准备将 [name] 安装到你的电脑。
WizardInstalling=正在安装
InstallingLabel=请稍候，安装程序正在安装 [name]。
FinishedHeadingLabel=正在完成 [name] 安装向导
FinishedLabelNoIcons=[name] 已安装到你的电脑。
FinishedLabel=[name] 已安装到你的电脑。你可以通过已创建的快捷方式启动应用。
FinishedRestartLabel=要完成 [name] 的安装，需要重新启动电脑。是否现在重新启动？
FinishedRestartMessage=要完成 [name] 的安装，需要重新启动电脑。%n%n是否现在重新启动？
RunEntryExec=运行 %1
SetupAborted=安装未完成。%n%n请修复问题后重新运行安装程序。
ErrorFunctionFailedNoCode=%1 失败
ErrorFunctionFailed=%1 失败；代码 %2
ErrorFunctionFailedWithMessage=%1 失败；代码 %2。%n%3
ErrorExecutingProgram=无法执行文件：%n%1

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Dirs]
Name: "{app}\data"
Name: "{app}\storage"
Name: "{app}\browser_profile"
Name: "{app}\output"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "data\*,storage\*,browser_profile\*,output\*"
Source: "{#MySourceDir}\data\accounts.json"; DestDir: "{app}\data"; Flags: ignoreversion onlyifdoesntexist
Source: "{#MySourceDir}\data\settings.json"; DestDir: "{app}\data"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
