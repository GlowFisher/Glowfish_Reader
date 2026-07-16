; Glowfish Reader 史料阅读器 —— Inno Setup 安装脚本（本地桌面 App）
; 编译： "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
; 前置： 先 pyinstaller 出 dist\glowfish_reader\（onedir）。产物 Output\glowfish_reader_setup.exe
; 说明：
;   · 按用户安装到 %LOCALAPPDATA%\Programs（PrivilegesRequired=lowest，免 UAC，对非技术用户友好）。
;   · 用户史料数据落 %APPDATA%\Glowfish Reader 史料阅读器\，安装/卸载都不碰，卸载只删程序本体。
;   · 首装检查 WebView2 运行时（Win11 一般自带；缺失则跑随包 bootstrapper 静默装）。
; 命名：产物/可执行名用 ASCII 代号 glowfish_reader（便于 glowfish 生态产品管理）；
;       用户可见显示名/快捷方式统一为「Glowfish Reader」；安装目录/数据目录仍用中文「Glowfish Reader 史料阅读器」，不影响已装用户数据。

#define AppBaseName "Glowfish Reader"
; AppVersion 单一真源 = proofread/_version.py；release.ps1 用 ISCC 命令行 /DAppVersion=<ver> 覆盖。
; 下面的字面量仅为「手动编译不带 /D」时的兜底默认，#ifndef 保证 /D 优先、不冲突。
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
#define AppDisplayName AppBaseName + " V" + AppVersion
#define AppExe AppDisplayName + ".exe"
#define AppPublisher "Glowfish Reader"
; OutputBase 由 release.ps1 经 /DOutputBase 覆盖（代码小包用 *_code）；默认=全量包名
#ifndef OutputBase
  #define OutputBase AppDisplayName + " Setup"
#endif
#ifndef OutputDir
  #define OutputDir "Output"
#endif

[Setup]
AppId={{8F3B2A10-7C4E-4D2A-9B6F-A1B2C3D4E5F6}
AppName={#AppDisplayName}
AppVerName={#AppDisplayName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppDisplayName}
DefaultGroupName={#AppDisplayName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
; 安装器/卸载向导图标 = 商标跃鱼标（与 exe 内嵌图标一致）
SetupIconFile=assets\glowfish.ico
Compression=lzma2/max
SolidCompression=no
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
; 应用内更新：同 AppId 自动就地升级。升级时用 Restart Manager 关掉正在运行的旧版再覆盖文件；
; 不让安装器自行重启（重启交给下方 [Run] 的静默专用项，避免重复拉起）。
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppDisplayName} Setup
VersionInfoProductName={#AppDisplayName}
VersionInfoProductVersion={#AppVersion}
UninstallDisplayName={#AppDisplayName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"; Flags: checkedonce

[Files]
; PyInstaller onedir 产物整目录打包
#ifndef SourceDir
  #define SourceDir "dist\glowfish_reader"
#endif
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; （可选）WebView2 引导安装器，若放在脚本同级则随包；缺失时 [Code] 会跳过静默安装、仅提示
; Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: WebView2Missing

[Icons]
Name: "{group}\{#AppDisplayName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppDisplayName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppDisplayName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; 缺 WebView2 时静默装随包 bootstrapper（存在才跑）
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; \
  Flags: waituntilterminated skipifdoesntexist; Check: WebView2Missing
; 交互安装：安装完给「立即运行」勾选项（静默更新时不显示也不触发）
Filename: "{app}\{#AppExe}"; Description: "立即运行 {#AppDisplayName}"; Flags: nowait postinstall skipifsilent
; 应用内更新走 /SILENT 静默安装：装完自动重启 app（仅静默模式触发，避免与上面的交互项重复拉起）
Filename: "{app}\{#AppExe}"; Flags: nowait runascurrentuser; Check: WizardSilent

[Code]
function WebView2Missing(): Boolean;
var
  pv: string;
begin
  // Evergreen WebView2 Runtime 客户端 GUID；HKLM 或 HKCU 任一存在版本号即视为已装
  Result := True;
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv) and (pv <> '') then
    Result := False
  else if RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv) and (pv <> '') then
    Result := False;
end;
