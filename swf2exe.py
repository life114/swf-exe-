#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
swf2exe.py —— 把 SWF 游戏打包成单个可双击运行的 EXE

原理:
    不修改 Flash 播放器的二进制（风险高、版本相关），而是生成一个「自解压启动器」:
      ① 内嵌 Flash 播放器 + 内嵌 SWF（都可 gzip 压缩）
      ② 运行时释放到临时目录，用播放器打开 SWF
      ③ 退出后自动清理临时文件
    生成的是标准 Win32 EXE，无需安装任何运行库（.NET 4.x 是 Windows 自带的）。

依赖:
    只用 Windows 自带的 C# 编译器 csc.exe（.NET Framework 4.x），
    不需要 pip、不需要联网、不需要 Visual Studio。

用法:
    python swf2exe.py 游戏.swf
    python swf2exe.py 游戏.swf --out-dir D:\输出目录
    python swf2exe.py 游戏.swf --player "C:\...\flash播放器.exe"
    python swf2exe.py 游戏.swf --icon 图标.ico --name "超级游戏"
    python swf2exe.py 游戏.swf --no-compress      # 不压缩（体积大但启动略快）

输出:
    默认在 SWF 同目录生成 <游戏名>.exe
"""
import argparse
import gzip
import os
import shutil
import subprocess
import sys
import tempfile
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
LAUNCHER_CS = HERE / "launcher.cs"

# csc.exe 常见位置（从新到旧）
CSC_CANDIDATES = [
    r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
    r"C:\Windows\Microsoft.NET\Framework64\v3.5\csc.exe",
    r"C:\Windows\Microsoft.NET\Framework\v3.5\csc.exe",
]

# 播放器默认位置
PLAYER_CANDIDATES = [
    pathlib.Path(os.path.expanduser("~")) / "Desktop" / "flash播放器.exe",
    pathlib.Path(r"E:\falsh小游戏\SWF文件\flash播放器.exe"),
    pathlib.Path(os.path.expanduser("~")) / "Desktop" / "flashplayer.exe",
]


def find_csc():
    for p in CSC_CANDIDATES:
        if os.path.isfile(p):
            return p
    # 兜底：搜索 Framework64
    for base in (r"C:\Windows\Microsoft.NET",):
        for root, dirs, files in os.walk(base):
            if "csc.exe" in files and "v4.0.30319" in root:
                return os.path.join(root, "csc.exe")
    return None


def find_player(explicit=None):
    if explicit:
        p = pathlib.Path(explicit)
        if p.is_file():
            return p
        raise SystemExit("指定的播放器不存在: %s" % explicit)
    for p in PLAYER_CANDIDATES:
        if p.is_file():
            return p
    raise SystemExit(
        "找不到 Flash 播放器。请用 --player 指定，例如:\n"
        '  --player "C:\\Users\\你\\Desktop\\flash播放器.exe"'
    )


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0


def build(swf_path, player_path, out_path, icon=None, compress=True, name=None):
    csc = find_csc()
    if not csc:
        raise SystemExit("找不到 csc.exe（.NET Framework 4.x 应随 Windows 自带）")
    if not LAUNCHER_CS.is_file():
        raise SystemExit("缺少 launcher.cs，请确认它和本脚本在同一目录")

    swf_path = pathlib.Path(swf_path)
    player_path = pathlib.Path(player_path)
    out_path = pathlib.Path(out_path)

    print("  播放器 : %s  (%s)" % (player_path.name, human(player_path.stat().st_size)))
    print("  SWF    : %s  (%s)" % (swf_path.name, human(swf_path.stat().st_size)))
    print("  编译器 : %s" % csc)

    # 构建目录放在脚本旁边（避免系统临时目录被沙箱/权限拦住）
    work = HERE / "_build"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        # ---- 1. 准备资源 ----
        res_player = work / "player.bin"
        res_game = work / "game.bin"

        if compress:
            print("  压缩中 …")
            with open(player_path, "rb") as f_in, gzip.open(res_player, "wb", 6) as f_out:
                shutil.copyfileobj(f_in, f_out, 1 << 20)
            with open(swf_path, "rb") as f_in, gzip.open(res_game, "wb", 6) as f_out:
                shutil.copyfileobj(f_in, f_out, 1 << 20)
        else:
            shutil.copyfile(player_path, res_player)
            shutil.copyfile(swf_path, res_game)

        print("  压缩后 : 播放器 %s / 游戏 %s"
              % (human(res_player.stat().st_size), human(res_game.stat().st_size)))

        # ---- 2. 生成程序集信息（标题、版本） ----
        title = name or swf_path.stem
        info_cs = work / "AssemblyInfo.cs"
        info_cs.write_text(
            'using System.Reflection;\n'
            '[assembly: AssemblyTitle("%s")]\n'
            '[assembly: AssemblyProduct("SWF2EXE")]\n'
            '[assembly: AssemblyCopyright("")]\n'
            '[assembly: AssemblyVersion("1.0.0.0")]\n'
            '[assembly: AssemblyFileVersion("1.0.0.0")]\n' % title.replace('"', "'"),
            encoding="utf-8-sig",
        )

        # ---- 3. 调 csc ----
        target = work / "out.exe"
        cmd = [
            csc, "/nologo", "/target:winexe", "/optimize+", "/platform:anycpu",
            "/out:" + str(target),
            "/resource:%s,RES_PLAYER" % res_player,
            "/resource:%s,RES_GAME" % res_game,
        ]
        if icon:
            cmd.append("/win32icon:" + str(icon))
        cmd += [str(LAUNCHER_CS), str(info_cs)]

        print("  编译中 …")
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode != 0 or not target.is_file():
            print("  ✗ 编译失败")
            print(r.stdout[-3000:])
            print(r.stderr[-3000:])
            return False

        # ---- 4. 输出 ----
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target, out_path)
        print("  ✓ 生成: %s  (%s)" % (out_path, human(out_path.stat().st_size)))
        return True

    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(
        description="把 SWF 游戏打包成单文件 EXE（用 Windows 自带 csc 编译，无需联网）")
    ap.add_argument("swf", help="要转换的 .swf 文件")
    ap.add_argument("--out-dir", help="输出目录（默认与 SWF 同目录）")
    ap.add_argument("--out-name", help="输出文件名（不含 .exe）")
    ap.add_argument("--player", help="Flash 播放器 exe 路径")
    ap.add_argument("--icon", help="图标文件 .ico（可选）")
    ap.add_argument("--name", help="程序显示的标题（可选）")
    ap.add_argument("--no-compress", action="store_true", help="不压缩资源")
    args = ap.parse_args()

    swf = pathlib.Path(args.swf)
    if not swf.is_file():
        raise SystemExit("找不到 SWF: %s" % swf)
    if swf.suffix.lower() != ".swf":
        print("  ! 注意：扩展名不是 .swf，仍然继续")
    if swf.stat().st_size < 64:
        raise SystemExit("SWF 文件太小，可能已损坏: %s" % swf)

    player = find_player(args.player)

    # 路径清洗：cmd 的 "%~dp1" 以反斜杠结尾，拼引号时会变成 "...\" 造成非法路径
    raw_out = args.out_dir
    if raw_out:
        raw_out = raw_out.strip().strip('"').strip("'").strip()
        while len(raw_out) > 1 and raw_out[-1] in '\\/':
            raw_out = raw_out[:-1]
    out_dir = pathlib.Path(raw_out) if raw_out else swf.parent
    out_name = args.out_name or swf.stem
    out_path = out_dir / (out_name + ".exe")

    if out_path.exists():
        print("  ! 已存在，将被覆盖: %s" % out_path)

    print("=" * 66)
    print("  转换: %s" % swf.name)
    print("=" * 66)
    ok = build(swf, player, out_path,
               icon=args.icon, compress=not args.no_compress, name=args.name)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
