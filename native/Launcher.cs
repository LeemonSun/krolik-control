using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("Krolik Control")]
[assembly: AssemblyDescription("Display, audio and PC profiles")]
[assembly: AssemblyCompany("LeemonSun")]
[assembly: AssemblyProduct("Krolik Control")]
[assembly: AssemblyVersion("0.11.0.0")]
[assembly: AssemblyFileVersion("0.11.0.0")]

internal static class Launcher {
    static string Quote(string value) {
        var result=new StringBuilder("\"");int slash=0;
        foreach(char c in value) {
            if(c=='\\'){slash++;continue;}
            if(c=='\"'){result.Append('\\',slash*2+1);result.Append(c);slash=0;continue;}
            result.Append('\\',slash);slash=0;result.Append(c);
        }
        result.Append('\\',slash*2);result.Append('"');return result.ToString();
    }
    static void CheckPath(string root,string file) {
        if(!file.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("Недопустимый путь в сборке");
        for(string part=file;part.Length>root.Length;part=Path.GetDirectoryName(part))
            if((File.GetAttributes(part)&FileAttributes.ReparsePoint)!=0)throw new IOException("Файлы сборки не должны быть ссылками");
    }
    static void Verify(string root) {
        string manifest=Path.Combine(root,"data","release-manifest.json");CheckPath(root,manifest);
        if(new FileInfo(manifest).Length>4194304)throw new IOException("Повреждён список файлов сборки");
        var serializer=new JavaScriptSerializer();serializer.MaxJsonLength=4194304;
        var document=serializer.Deserialize<Dictionary<string,object>>(File.ReadAllText(manifest,Encoding.UTF8));
        var rows=document["files"] as IList;if(rows==null||rows.Count>5000)throw new IOException("Повреждён список файлов сборки");
        var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(Dictionary<string,object> row in rows) {
            string relative=(string)row["path"],expected=(string)row["sha256"];
            string file=Path.GetFullPath(Path.Combine(root,relative.Replace('/',Path.DirectorySeparatorChar)));
            CheckPath(root,file);if(!seen.Add(relative))throw new IOException("Повтор файла в сборке");
            using(var hash=SHA256.Create())using(var stream=File.OpenRead(file)) {
                string actual=BitConverter.ToString(hash.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
                if(actual!=expected)throw new IOException("Файл изменён или повреждён: "+relative+". Распакуйте сборку заново.");
            }
        }
        foreach(string required in new[]{"data/python.exe","data/main.py","data/winpilot/server.py","data/ui/index.html"})
            if(!seen.Contains(required))throw new IOException("В сборке отсутствует обязательный файл: "+required);
    }
    [STAThread] static int Main(string[] args) {
        bool verifyOnly=args.Length==1&&args[0]=="--verify-only";
        try {
            string root=Path.GetDirectoryName(Application.ExecutablePath);Verify(root);
            if(verifyOnly)return 0;
            string data=Path.Combine(root,"data"),directory=null;
            for(int i=0;i+1<args.Length;i++)if(args[i]=="--data-dir")directory=args[i+1];
            if(directory==null)directory=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"WinPilot","sessions");
            string logs=Path.Combine(Path.GetFullPath(directory),"launcher-logs");Directory.CreateDirectory(logs);
            string log=Path.Combine(logs,DateTime.Now.ToString("yyyyMMdd-HHmmss-fff")+"-"+Process.GetCurrentProcess().Id+".txt");
            var command=new StringBuilder("-I -B -c ");
            command.Append(Quote("import runpy,sys;root=sys.argv.pop(1);sys.path.insert(0,root);runpy.run_path(root+'/main.py',run_name='__main__')"));command.Append(" "+Quote(data));
            foreach(string arg in args)command.Append(" "+Quote(arg));
            var start=new ProcessStartInfo(Path.Combine(data,"python.exe"),command.ToString());
            start.WorkingDirectory=data;start.UseShellExecute=false;start.CreateNoWindow=true;start.RedirectStandardOutput=true;start.RedirectStandardError=true;
            start.StandardOutputEncoding=Encoding.UTF8;start.StandardErrorEncoding=Encoding.UTF8;
            start.EnvironmentVariables["WINPILOT_EXECUTABLE"]=Application.ExecutablePath;start.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
            using(var writer=new StreamWriter(log,false,new UTF8Encoding(false)))using(var child=new Process()) {
                var gate=new object();long written=0;
                DataReceivedEventHandler write=delegate(object sender,DataReceivedEventArgs e){if(e.Data==null)return;lock(gate){if(written>2097152)return;string line=Regex.Replace(e.Data,@"(http://127\.0\.0\.1:\d+/)#\S+","$1#[hidden]");writer.WriteLine(line);writer.Flush();written+=line.Length;}};
                child.StartInfo=start;child.OutputDataReceived+=write;child.ErrorDataReceived+=write;child.Start();child.BeginOutputReadLine();child.BeginErrorReadLine();child.WaitForExit();
                return child.ExitCode;
            }
        } catch(Exception error) {
            if(verifyOnly)return 2;
            MessageBox.Show(error.Message,"Krolik Control — не удалось запустить",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;
        }
    }
}
