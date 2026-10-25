using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Diagnostics;
using System.Threading;

// SWF2EXE 启动器
//
// 关键设计：把播放器和 SWF 释放在【EXE 所在目录】，而不是系统临时目录。
// 原因：不少 Flash 游戏会按相对路径加载外置素材（地图、BGM、关卡数据），
//       路径是相对于 SWF 自身位置的。放到 %TEMP% 会导致找不到这些文件。
// 退出后自动删除释放出来的两个文件。
//
// 调试：环境变量 SWF2EXE_DEBUG=1 时，在 EXE 同目录写 swf2exe_run.log
static class Swf2ExeLauncher
{
    static string _logPath;
    static bool _debug;

    static int Main(string[] args)
    {
        _debug = Environment.GetEnvironmentVariable("SWF2EXE_DEBUG") == "1";

        string baseDir;
        try
        {
            baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            if (string.IsNullOrEmpty(baseDir))
            {
                baseDir = Path.GetDirectoryName(Application_ExecutablePath());
            }
        }
        catch
        {
            baseDir = Path.GetDirectoryName(Application_ExecutablePath());
        }

        _logPath = Path.Combine(baseDir, "swf2exe_run.log");

        string stem = Path.GetFileNameWithoutExtension(Application_ExecutablePath());

        // 先清理上次被强杀留下的陈旧文件（名字形如 <stem>.<6位>._player.exe）
        CleanupStale(baseDir, stem, "._player.exe");
        CleanupStale(baseDir, stem, "._game.swf");

        // 每次运行用随机后缀，避免旧文件被占用导致无法写入
        string tag = Guid.NewGuid().ToString("N").Substring(0, 6);
        string player = Path.Combine(baseDir, stem + "." + tag + "._player.exe");
        string game = Path.Combine(baseDir, stem + "." + tag + "._game.swf");

        try
        {
            Log("EXE 目录: " + baseDir);
            Log("释放播放器 → " + player);
            Extract("RES_PLAYER", player);
            Log("  大小: " + new FileInfo(player).Length);

            Log("释放 SWF → " + game);
            Extract("RES_GAME", game);
            Log("  大小: " + new FileInfo(game).Length);

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = player;
            psi.Arguments = "\"" + game + "\"";
            psi.WorkingDirectory = baseDir;
            psi.UseShellExecute = false;

            Log("启动播放器 …");
            Process p = Process.Start(psi);
            if (p == null)
            {
                Log("Process.Start 返回 null");
                return 1;
            }
            Log("播放器 PID = " + p.Id + "，等待退出 …");
            p.WaitForExit();
            Log("播放器退出，退出码 = " + p.ExitCode);
            return p.ExitCode;
        }
        catch (Exception ex)
        {
            Log("异常: " + ex);

            // 目录不可写时，退回到临时目录再试一次
            Log("回退到临时目录重试 …");
            try
            {
                string tmp = Path.Combine(Path.GetTempPath(),
                                          "swf2exe_" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(tmp);
                string tplayer = Path.Combine(tmp, "player.exe");
                string tgame = Path.Combine(tmp, "game.swf");
                Extract("RES_PLAYER", tplayer);
                Extract("RES_GAME", tgame);
                ProcessStartInfo psi2 = new ProcessStartInfo();
                psi2.FileName = tplayer;
                psi2.Arguments = "\"" + tgame + "\"";
                psi2.WorkingDirectory = tmp;
                psi2.UseShellExecute = false;
                Process p2 = Process.Start(psi2);
                if (p2 == null)
                {
                    return 1;
                }
                p2.WaitForExit();
                try { Directory.Delete(tmp, true); } catch { }
                return p2.ExitCode;
            }
            catch (Exception ex2)
            {
                Log("回退也失败: " + ex2);
                return 2;
            }
        }
        finally
        {
            Cleanup(player);
            Cleanup(game);
        }
    }

    // 拿自身 EXE 路径（避免引用 System.Windows.Forms）
    static string Application_ExecutablePath()
    {
        try
        {
            Assembly a = Assembly.GetEntryAssembly();
            if (a != null && !string.IsNullOrEmpty(a.Location))
            {
                return a.Location;
            }
        }
        catch { }
        try
        {
            return Process.GetCurrentProcess().MainModule.FileName;
        }
        catch { }
        return "app.exe";
    }

    static void Cleanup(string path)
    {
        for (int i = 0; i < 20; i++)
        {
            try
            {
                if (File.Exists(path))
                {
                    File.Delete(path);
                }
                return;
            }
            catch
            {
                Thread.Sleep(150);
            }
        }
    }

    // 清理上次异常退出留下的文件：<stem>.<6位十六进制>._player.exe / ._game.swf
    static void CleanupStale(string dir, string stem, string suffix)
    {
        try
        {
            string[] files = Directory.GetFiles(dir, stem + ".*" + suffix);
            foreach (string f in files)
            {
                string name = Path.GetFileName(f);
                // 只匹配 <stem>.<6位>._xxx 这种模式，避免误删用户自己的文件
                string mid = name.Substring(stem.Length);
                int dot = mid.IndexOf('.');
                if (dot != 1)
                {
                    continue;
                }
                if (mid.Length < 7 || mid[6] != '.')
                {
                    continue;
                }
                try
                {
                    File.Delete(f);
                    Log("清理陈旧文件: " + name);
                }
                catch
                {
                    Log("陈旧文件正被占用，跳过: " + name);
                }
            }
        }
        catch { }
    }

    static void Log(string msg)
    {
        if (!_debug || string.IsNullOrEmpty(_logPath))
        {
            return;
        }
        try
        {
            File.AppendAllText(_logPath,
                DateTime.Now.ToString("HH:mm:ss.fff") + "  " + msg + Environment.NewLine);
        }
        catch { }
    }

    // 释放内嵌资源；内容以 gzip 压缩（1F 8B 开头）则自动解压
    static void Extract(string resName, string destPath)
    {
        Assembly asm = Assembly.GetExecutingAssembly();
        Stream raw = asm.GetManifestResourceStream(resName);
        if (raw == null)
        {
            throw new Exception("缺少内嵌资源: " + resName);
        }

        using (raw)
        {
            int b1 = raw.ReadByte();
            int b2 = raw.ReadByte();
            if (b1 < 0 || b2 < 0)
            {
                throw new Exception("内嵌资源为空: " + resName);
            }
            bool gz = (b1 == 0x1F && b2 == 0x8B);

            byte[] head = new byte[] { (byte)b1, (byte)b2 };
            using (Stream src = new ConcatStream(head, raw))
            {
                if (gz)
                {
                    using (GZipStream data = new GZipStream(src, CompressionMode.Decompress))
                    using (FileStream fs = File.Create(destPath))
                    {
                        Copy(data, fs);
                    }
                }
                else
                {
                    using (FileStream fs = File.Create(destPath))
                    {
                        Copy(src, fs);
                    }
                }
            }
        }
    }

    static void Copy(Stream src, Stream dst)
    {
        byte[] buf = new byte[81920];
        int n;
        while ((n = src.Read(buf, 0, buf.Length)) > 0)
        {
            dst.Write(buf, 0, n);
        }
    }
}

// 把「已读出的前两字节」和「剩余流」拼成一个流
sealed class ConcatStream : Stream
{
    private readonly byte[] _head;
    private int _pos;
    private readonly Stream _tail;

    public ConcatStream(byte[] head, Stream tail)
    {
        _head = head;
        _tail = tail;
    }

    public override bool CanRead { get { return true; } }
    public override bool CanSeek { get { return false; } }
    public override bool CanWrite { get { return false; } }
    public override long Length { get { throw new NotSupportedException(); } }
    public override long Position
    {
        get { throw new NotSupportedException(); }
        set { throw new NotSupportedException(); }
    }

    public override int Read(byte[] buffer, int offset, int count)
    {
        if (_pos < _head.Length)
        {
            int n = Math.Min(count, _head.Length - _pos);
            Array.Copy(_head, _pos, buffer, offset, n);
            _pos += n;
            return n;
        }
        return _tail.Read(buffer, offset, count);
    }

    public override void Flush() { }
    public override long Seek(long offset, SeekOrigin origin) { throw new NotSupportedException(); }
    public override void SetLength(long value) { throw new NotSupportedException(); }
    public override void Write(byte[] buffer, int offset, int count) { throw new NotSupportedException(); }
}
