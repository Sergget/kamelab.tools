#!/usr/bin/env python3
"""Lab Tools 本地一键启动器（Win/Linux）。

在项目根目录运行，按组件启动本地服务：

    python run_local_servers.py --all          # 后端 + OCR 节点（全部）
    python run_local_servers.py --backend      # 仅后端
    python run_local_servers.py --ocr          # 仅 OCR 节点
    python run_local_servers.py --backend --port 9000

约定：
    backend  -> backend/                 （venv: backend/.venv）
    ocr      -> ocr_server/              （venv: ocr_server/.venv；目录不存在时自动跳过）

按 Ctrl+C 停止全部子进程。
"""
import argparse
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
OCR_PORT = 8001


def venv_python(pkg_dir: str) -> str:
    """返回 pkg_dir 下 venv 的解释器路径（不存在则返回空）。"""
    if os.name == "nt":
        py = os.path.join(ROOT, pkg_dir, ".venv", "Scripts", "python.exe")
    else:
        py = os.path.join(ROOT, pkg_dir, ".venv", "bin", "python")
    return py if os.path.exists(py) else ""


def ensure_venv(pkg_dir: str, requirements: str) -> str:
    """确保 venv 存在并按 requirements.txt 安装依赖，返回解释器路径。"""
    py = venv_python(pkg_dir)
    if py:
        return py
    print(f"[{pkg_dir}] 未找到 .venv，正在创建...")
    subprocess.run([sys.executable, "-m", "venv", os.path.join(ROOT, pkg_dir, ".venv")], check=True)
    py = venv_python(pkg_dir)
    req = os.path.join(ROOT, pkg_dir, requirements)
    if os.path.exists(req):
        subprocess.run([py, "-m", "pip", "install", "-q", "-r", req], check=True)
    return py


def main() -> None:
    ap = argparse.ArgumentParser(description="Lab Tools 本地启动器")
    ap.add_argument("--backend", action="store_true", help="启动后端服务")
    ap.add_argument("--ocr", action="store_true", help="启动 OCR 节点服务")
    ap.add_argument("--all", action="store_true", help="启动全部（后端 + OCR）")
    ap.add_argument("--port", type=int, default=8000, help="后端监听端口（默认 8000）")
    ap.add_argument("--host", default="0.0.0.0", help="后端监听地址（默认 0.0.0.0）")
    args = ap.parse_args()

    want_backend = args.backend or args.all or not (args.backend or args.ocr)
    want_ocr = args.ocr or args.all

    procs: list[tuple[subprocess.Popen, str]] = []

    if want_backend:
        py = ensure_venv("backend", "requirements.txt")
        env = os.environ.copy()
        env["LAB_TOOLS_OCR_NODE_URL"] = f"http://127.0.0.1:{OCR_PORT}"
        cmd = [py, "run.py", "--host", args.host, "--port", str(args.port)]
        print(f"[backend] 启动: {' '.join(cmd)}")
        procs.append((subprocess.Popen(cmd, cwd=os.path.join(ROOT, "backend"), env=env), "backend"))

    if want_ocr:
        if os.path.isdir(os.path.join(ROOT, "ocr_server")):
            py = ensure_venv("ocr_server", "requirements.txt")
            cmd = [py, "ocr_server.py", "--port", str(OCR_PORT)]
            print(f"[ocr] 启动: {' '.join(cmd)}")
            procs.append((subprocess.Popen(cmd, cwd=os.path.join(ROOT, "ocr_server")), "ocr"))
        else:
            print("[ocr] 未找到 ocr_server/ 目录，跳过（OCR 节点部署后即可启用）")

    if not procs:
        ap.print_help()
        sys.exit(1)

    def stop(_sig=None, _frame=None) -> None:
        print("\n正在停止全部服务...")
        for p, _ in procs:
            p.terminate()
        for p, _ in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        while True:
            for p, name in procs:
                if p.poll() is not None:
                    print(f"[{name}] 进程退出（code={p.returncode}），停止全部")
                    stop()
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__":
    main()