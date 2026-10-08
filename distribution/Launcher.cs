using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("PPT Toolbox")]
// Build-generated assembly metadata uses the product release.json version.

class Launcher {
    static void Setup(string root, string sourceData) {
        var form = new Form { Text = "PPT 工具箱安装与迁移", Width = 740, Height = 490,
                              StartPosition = FormStartPosition.CenterScreen };
        var panel = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(16), ColumnCount = 3, RowCount = 7 };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 70));
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string docs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
        string[] labels = { "软件安装位置", "原管理数据", "新管理数据", "新项目保存位置" };
        string[] values = { Path.Combine(local,"Programs","PPTToolbox"), sourceData ?? Path.Combine(root,"data"),
                            Path.Combine(local,"PPTToolbox"), Path.Combine(docs,"PPTToolbox","Projects") };
        var boxes = new TextBox[4];
        for (int i=0;i<4;i++) {
            int n=i; panel.RowStyles.Add(new RowStyle(SizeType.Absolute, 50));
            panel.Controls.Add(new Label { Text=labels[i], AutoSize=true, Anchor=AnchorStyles.Left },0,i);
            boxes[i]=new TextBox { Text=values[i], Dock=DockStyle.Fill, Anchor=AnchorStyles.Left|AnchorStyles.Right };
            panel.Controls.Add(boxes[i],1,i);
            var choose=new Button { Text="选择", AutoSize=true };
            choose.Click += delegate { using (var folder=new FolderBrowserDialog()) {
                folder.Description=labels[n]; folder.SelectedPath=boxes[n].Text;
                if(folder.ShowDialog(form)==DialogResult.OK)boxes[n].Text=folder.SelectedPath;
            }};
            panel.Controls.Add(choose,2,i);
        }
        var note=new Label { Text="先暂停 Agent 并退出工具箱后台。迁移会保留原数据和备份，不移动已有 PPT 项目，也不会开启权限。新项目使用所选保存位置。目标软件与数据目录须为空的新目录。", Dock=DockStyle.Fill, AutoSize=true };
        panel.Controls.Add(note,0,4);panel.SetColumnSpan(note,3);
        var result=new TextBox { Multiline=true, ReadOnly=true, Dock=DockStyle.Fill, ScrollBars=ScrollBars.Vertical };
        panel.RowStyles.Add(new RowStyle(SizeType.Absolute,65));
        panel.RowStyles.Add(new RowStyle(SizeType.Percent,100));
        panel.Controls.Add(result,0,5);panel.SetColumnSpan(result,3);
        var run=new Button { Text="检查并安装或迁移", AutoSize=true };
        panel.Controls.Add(run,1,6);
        run.Click += delegate {
            string[] paths=Array.ConvertAll(boxes,b=>b.Text);
            if(MessageBox.Show(form,"按上述目录安装或迁移？已有项目文件保持原位。","确认目录",MessageBoxButtons.OKCancel)!=DialogResult.OK)return;
            run.Enabled=false;result.Text="正在核对文件和占用状态……";
            var worker=new System.ComponentModel.BackgroundWorker();
            worker.DoWork += delegate(object sender,System.ComponentModel.DoWorkEventArgs ev) {
                string argv="-B "+Quote(Path.Combine(root,"app","distribution","install_local.py"))+" --bundle "+Quote(root)+
                    " --destination "+Quote(paths[0])+" --source-data "+Quote(paths[1])+" --data "+Quote(paths[2])+" --projects "+Quote(paths[3]);
                if (!Directory.Exists(paths[1]) || Directory.GetFileSystemEntries(paths[1]).Length == 0)
                    argv+=" --first-install";
                string codex=Environment.GetEnvironmentVariable("CODEX_HOME");
                if(String.IsNullOrEmpty(codex))codex=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),".codex");
                string config=Path.Combine(codex,"config.toml");
                if(File.Exists(config))argv+=" --codex-config "+Quote(config);
                argv+=" --active-pointer "+Quote(Path.Combine(local,"PPTToolbox-installation.json"));
                var info=new ProcessStartInfo(Path.Combine(root,"runtime","python.exe"),argv) {
                    UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,
                    StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8 };
                info.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
                using(var p=Process.Start(info)) { string output=p.StandardOutput.ReadToEnd();string error=p.StandardError.ReadToEnd();p.WaitForExit();
                    ev.Result=p.ExitCode==0 ? "安装或迁移完成。请从新位置启动软件，并在 Agent 中刷新接入。\r\n"+output : "未完成，原数据保留。\r\n"+error; }
            };
            worker.RunWorkerCompleted += delegate(object sender,System.ComponentModel.RunWorkerCompletedEventArgs ev) {
                result.Text=ev.Error!=null?ev.Error.Message:(string)ev.Result;run.Enabled=true;
            };
            worker.RunWorkerAsync();
        };
        form.Controls.Add(panel);Application.Run(form);
    }
    // Windows command-line quoting, including embedded quotes and trailing slashes.
    static string Quote(string value) {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value) {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); }
            else { result.Append('\\', slashes); result.Append(c); }
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    [STAThread] static int Main(string[] args) {
        try {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "runtime", "pythonw.exe");
            string entry = Path.Combine(root, "portable.py");
            if (!File.Exists(python) || !File.Exists(entry))
                throw new FileNotFoundException("请完整解压软件包后再启动。");
            bool smoke = false, show = true, setup = false, portable = false;
            string data = null;
            for (int i = 0; i < args.Length; i++) {
                if (args[i] == "--smoke") { smoke = true; show = false; }
                else if (args[i] == "--setup") setup = true;
                else if (args[i] == "--portable") portable = true;
                else if (args[i] == "--background") show = false;
                else if (args[i] == "--show") show = true;
                else if (args[i] == "--data-dir" && i + 1 < args.Length) data = args[++i];
                else throw new ArgumentException("Unknown launcher argument: " + args[i]);
            }
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            bool installed = File.Exists(Path.Combine(root,"location.json"));
            bool existing = File.Exists(Path.Combine(local,"PPTToolbox-installation.json")) ||
                File.Exists(Path.Combine(local,"Programs","PPTToolbox","location.json"));
            if (setup || (!installed && !existing && !portable && data == null && !smoke)) {
                Application.EnableVisualStyles(); Setup(root,data); return 0;
            }
            string arguments = "-B " + Quote(entry) + " desktop --agent-start";
            if (portable) arguments += " --portable";
            if (data != null) arguments += " --data-dir " + Quote(data);
            if (show) arguments += " --show";
            if (smoke) arguments += " --smoke";
            var info = new ProcessStartInfo(python, arguments);
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.EnvironmentVariables.Remove("PYTHONHOME");
            info.EnvironmentVariables.Remove("PYTHONPATH");
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            using (var process = Process.Start(info)) {
                if (smoke) { process.WaitForExit(); return process.ExitCode; }
            }
            return 0;
        } catch (Exception error) {
            if (Array.IndexOf(args, "--smoke") < 0)
                MessageBox.Show(error.Message, "PPT 工具箱启动失败");
            return 1;
        }
    }
}
