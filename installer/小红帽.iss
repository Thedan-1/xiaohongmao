#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef OutputName
  #define OutputName "小红帽-Windows-x64-v0.6-普通版-安装"
#endif
#define AppName "小红帽"
#ifndef AppVersion
  #define AppVersion "0.7.0"
#endif
#ifndef AppIdentity
  #define AppIdentity "{{6EB34361-9F1F-44D8-9E75-AC7EF691D739}"
#endif
#ifndef ClientMutex
  #define ClientMutex "Local\XiaohongmaoDesktop_v05"
#endif

[Setup]
AppId={#AppIdentity}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=小红帽
DefaultDirName={localappdata}\Programs\Xiaohongmao
DefaultGroupName=小红帽
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
WizardSizePercent=110,110
LicenseFile=小红帽使用协议.txt
InfoBeforeFile=小红帽隐私与数据说明.txt
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
#if FileExists(SourceDir + "\小红帽.ico")
SetupIconFile={#SourceDir}\小红帽.ico
#endif
Compression=lzma2
SolidCompression=yes
SetupLogging=yes
UninstallDisplayIcon={app}\小红帽.exe
UninstallDisplayName=小红帽
AppMutex={#ClientMutex}
CloseApplications=no
RestartApplications=no
AllowCancelDuringInstall=no
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Messages]
chinesesimp.BeveledLabel=小红帽 · 本机工作台
chinesesimp.FinishedLabelNoIcons=小红帽安装完成。首次启动会初始化本机工作台。项目和登录信息保存在当前 Windows 用户的数据目录中。
chinesesimp.SetupAppRunningError=小红帽仍在运行。为保护正在执行的任务，请先在客户端正常退出，然后重新安装。安装程序不会自动结束您的任务。
chinesesimp.UninstallAppRunningError=小红帽仍在运行。请先在客户端正常退出，然后重新卸载，以免中断任务。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "小红帽使用协议.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "小红帽隐私与数据说明.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\小红帽"; Filename: "{app}\小红帽.exe"; WorkingDir: "{app}"
Name: "{group}\卸载小红帽"; Filename: "{uninstallexe}"
Name: "{userdesktop}\小红帽"; Filename: "{app}\小红帽.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\小红帽.exe"; Description: "启动小红帽"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if CheckForMutexes('{#ClientMutex}') then
    Result := '小红帽正在运行，请先退出客户端后再安装。现有项目和登录数据将保留。';
end;

function InitializeUninstall(): Boolean;
begin
  Result := not CheckForMutexes('{#ClientMutex}');
  if not Result then
    SuppressibleMsgBox('小红帽正在运行，请先退出客户端后再卸载。', mbInformation, MB_OK, IDOK);
end;
