#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "로컬 PDF"
#define AppExe "LocalPDF.exe"
#define AppProgID "LocalPDF.Document"
#define Capabilities "Software\LocalPDF\Capabilities"

[Setup]
AppId={{4E7E0C0F-C6AE-48D2-9DE4-1F602F481952}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} 설치
DefaultDirName={localappdata}\Programs\LocalPDF
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir=..\dist
OutputBaseFilename=LocalPDF-Setup-{#AppVersion}-x64
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
ChangesAssociations=yes
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "..\dist\LocalPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\*.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\build.ps1"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\source\assets"; Flags: ignoreversion
Source: "*.iss"; DestDir: "{app}\source\installer"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; Flags: unchecked

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "{#Capabilities}"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\LocalPDF"; Flags: uninsdeletekeyifempty
Root: HKA; Subkey: "{#Capabilities}"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "{#Capabilities}"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "PDF를 열고 편집하는 Windows 데스크톱 프로그램"
Root: HKA; Subkey: "{#Capabilities}"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "{#Capabilities}\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#AppProgID}"
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: none; ValueName: "{#AppProgID}"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\{#AppProgID}"; ValueType: string; ValueData: "PDF 문서"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#AppProgID}\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\{#AppProgID}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: none; ValueName: ".pdf"
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 열기"; Flags: postinstall nowait skipifsilent unchecked
Filename: "ms-settings:defaultapps"; Description: "기본 PDF 앱을 선택할 Windows 설정 열기"; Flags: shellexec postinstall nowait skipifsilent unchecked
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: IsLocalPDFUpdate

[Code]
function IsLocalPDFUpdate: Boolean;
begin
  Result := ExpandConstant('{param:LOCALPDFUPDATE|0}') = '1';
end;
