"""Build a standard per-user installer from an already verified release."""
import argparse,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from distribution.update_installed import verify

def build(bundle,compiler,scratch,output):
    language=Path(__file__).resolve().parent/'languages/ChineseSimplified.isl'
    if not language.is_file():raise ValueError('Bundled Chinese installer translation is missing')
    bundle=bundle.resolve();manifest=verify(bundle)
    version=json.loads((bundle/"app/PRODUCT.json").read_text(encoding="utf-8"))["version"]
    scratch.mkdir(parents=True,exist_ok=True)
    # Uninstall removes exactly the shipped files. Recovery metadata and all
    # user-created files are retained; never recursively delete the install root.
    deletes="\n".join('Type: files; Name: "{app}\\'+n.replace('/','\\')+'"' for n in manifest if n!="app/PRODUCT.json")
    script=r'''
[Setup]
AppId=PPTToolbox.Desktop
AppName=PPT Toolbox
AppVersion=__VERSION__
DefaultDirName={localappdata}\Programs\PPTToolbox
DefaultGroupName=PPT Toolbox
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=__OUTPUT__
OutputBaseFilename=PPTToolbox-__VERSION__-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\PPTToolbox.exe
SetupLogging=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "__CHINESE_LANGUAGE__"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "__BUNDLE__\*"; DestDir: "{tmp}\payload"; Flags: dontcopy recursesubdirs createallsubdirs noencryption

[Icons]
Name: "{group}\PPT Toolbox"; Filename: "{app}\PPTToolbox.exe"
Name: "{autodesktop}\PPT Toolbox"; Filename: "{app}\PPTToolbox.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PPTToolbox.exe"; Description: "打开 PPT 工具箱，在设置页配置 Agent"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
__DELETES__

[Code]
var
  PathsPage: TInputDirWizardPage;

function InstallationPath: String;
var
  Raw: AnsiString;
  Text: String;
  I, J: Integer;
begin
  Result := '';
  if not LoadStringFromFile(ExpandConstant('{localappdata}\PPTToolbox-installation.json'), Raw) then exit;
  Text := UTF8Decode(Raw);
  I := Pos('"installation"', Text);
  if I = 0 then exit;
  I := I + Length('"installation"');
  while (I <= Length(Text)) and (Text[I] <> ':') do I := I + 1;
  I := I + 1;
  while (I <= Length(Text)) and (Text[I] <> '"') do I := I + 1;
  I := I + 1;
  while I <= Length(Text) do begin
    if Text[I] = '"' then exit;
    if Text[I] = '\' then begin
      I := I + 1;
      if I > Length(Text) then break;
      if Text[I] = 'u' then begin
        J := StrToIntDef('$' + Copy(Text, I+1, 4), 0);
        Result := Result + Chr(J); I := I + 5; continue;
      end;
    end;
    Result := Result + Text[I]; I := I + 1;
  end;
  Result := '';
end;

procedure InitializeWizard;
var
  Previous: String;
begin
  Previous := InstallationPath;
  if (Previous <> '') and (ExpandConstant('{param:DIR|}') = '') then WizardForm.DirEdit.Text := Previous;
  PathsPage := CreateInputDirPage(wpSelectDir, '管理数据与 PPT 项目',
    '选择工作内容的保存位置',
    '程序、管理数据与 PPT 项目分别保存。升级已有安装时，继续使用已保存的位置。',
    False, '');
  PathsPage.Add('管理数据目录');
  PathsPage.Add('默认 PPT 项目目录');
  PathsPage.Values[0] := ExpandConstant('{param:DATA|{localappdata}\PPTToolbox}');
  PathsPage.Values[1] := ExpandConstant('{param:PROJECTS|{userdocs}\PPTToolbox\Projects}');
end;

function InstallPayload: String; forward;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Version: String;
  Release: Cardinal;
begin
  Result := '';
  if not RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release) or (Release < 394802) then
    Result := '需要 Microsoft .NET Framework 4.6.2 或更高版本。请安装系统更新后重试。';
  if not RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
    and not RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) then
    Result := '需要 Microsoft Edge WebView2 Runtime。请从 https://developer.microsoft.com/microsoft-edge/webview2 下载并安装 Evergreen Runtime 后重试。';
  if Result = '' then Result := InstallPayload;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PathsPage = nil then exit;
  if PageID <> PathsPage.ID then exit;
  { The app constant is unavailable while Setup searches the early pages. }
  Result := FileExists(AddBackslash(WizardDirValue) + 'location.json');
end;

function InstallPayload: String;
var
  Code: Integer;
  Params, Report: String;
  ErrorText: AnsiString;
begin
  Result := '';
  WizardForm.StatusLabel.Caption := '正在校验并安装程序，请稍候…';
  ExtractTemporaryFiles('{tmp}\payload\*');
  begin
    Report := ExpandConstant('{tmp}\ppt-install-report.txt');
    Params := '-B "' + ExpandConstant('{tmp}\payload\app\distribution\setup_helper.py') +
      '" --bundle "' + ExpandConstant('{tmp}\payload') + '" --destination "' +
      ExpandConstant('{app}') + '" --data "' + PathsPage.Values[0] +
      '" --projects "' + PathsPage.Values[1] + '" --report "' + Report + '"';
    if not Exec(ExpandConstant('{tmp}\payload\runtime\python.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, Code) then
    begin Result := '无法启动安装运行环境。'; exit; end;
    if Code <> 0 then begin
      LoadStringFromFile(Report, ErrorText);
      Result := '安装已停止。' + UTF8Decode(ErrorText);
    end;
  end;
end;

function InitializeUninstall: Boolean;
var
  Code: Integer;
  Report: String;
begin
  Report := ExpandConstant('{tmp}\ppt-uninstall-check.txt');
  Result := Exec(ExpandConstant('{app}\runtime\python.exe'),
    '-B "' + ExpandConstant('{app}\app\distribution\setup_helper.py') +
    '" --uninstall-check --destination "' + ExpandConstant('{app}') +
    '" --report "' + Report + '"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := Result and (Code = 0);
  if not Result then MsgBox('请退出工具箱和对应的 Agent MCP 服务后重试。有正在执行或未核对结果的任务时，先完成核对。管理数据和 PPT 项目会保留。', mbError, MB_OK);
end;
'''
    for key,value in {"VERSION":version,"OUTPUT":str(output.resolve()),"BUNDLE":str(bundle),"DELETES":deletes,"CHINESE_LANGUAGE":str(language)}.items():
        script=script.replace("__"+key+"__",value)
    source=scratch/"setup.iss";source.write_text(script,encoding="utf-8-sig")
    subprocess.run([str(compiler),"/Q",str(source)],check=True)
    return output/f"PPTToolbox-{version}-Setup.exe"

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--bundle",type=Path,required=True);p.add_argument("--compiler",type=Path,required=True)
    p.add_argument("--scratch",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();print(build(a.bundle,a.compiler,a.scratch,a.output))
