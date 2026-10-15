#!/usr/bin/env python3
"""Lab Tools 本地一键启动与测试脚本（Win/Linux）。

支持通过参数分模块启动或同时启动前端、后端、OCR节点：

    python run_local_servers.py --all            # 启动全部（后端 + 前端开发服务 + OCR 节点）
    python run_local_servers.py --backend        # 仅启动后端服务
    python run_local_servers.py --frontend       # 仅启动前端 Vite 开发服务
    python run_local_servers.py --ocr            # 仅启动 OCR 节点服务
    python run_local_servers.py --backend --frontend --port 8000

按 Ctrl+C 停止全部子进程。
"""
import argparse
import os
import signal
import subprocess
import sys
import shutil
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
    ap = argparse.ArgumentParser(description="Lab Tools 本地模块化启动器")
    ap.add_argument("--backend", action="store_true", help="启动后端 FastAPI 服务")
    ap.add_argument("--frontend", action="store_true", help="启动前端 Vite 开发服务")
    ap.add_argument("--ocr", action="store_true", help="启动 OCR 节点服务")
    ap.add_argument("--all", action="store_true", help="启动全部模块（后端 + 前端 + OCR）")
    ap.add_argument("--port", type=int, default=8000, help="后端监听端口（默认 8000）")
    ap.add_argument("--host", default="0.0.0.0", help="后端监听地址（默认 0.0.0.0）")
    args = ap.parse_args()

    # 如果没有任何模块参数，默认启动后端
    if not (args.backend or args.frontend or args.ocr or args.all):
        args.backend = True

    want_backend = args.backend or args.all
    want_frontend = args.frontend or args.all
    want_ocr = args.ocr or args.all

    procs: list[tuple[subprocess.Popen, str]] = []

    # 1. 启动后端
    if want_backend:
        py = ensure_venv("backend", "requirements.txt")
        env = os.environ.copy()
        env["LAB_TOOLS_OCR_NODE_URL"] = f"http://127.0.0.1:{OCR_PORT}"
        cmd = [py, "run.py", "--host", args.host, "--port", str(args.port)]
        print(f"[backend] 启动: {' '.join(cmd)}")
        procs.append((subprocess.Popen(cmd, cwd=os.path.join(ROOT, "backend"), env=env), "backend"))

    # 2. 启动前端
    if want_frontend:
        frontend_dir = os.path.join(ROOT, "frontend")
        if os.path.isdir(frontend_dir):
            npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
            if not shutil.which(npm_cmd):
                print("[frontend] 错误: 未找到 npm，请先安装 Node.js")
            else:
                node_modules = os.path.join(frontend_dir, "node_modules")
                if not os.path.exists(node_modules):
                    print("[frontend] 正在安装前端依赖 (npm install)...")
                    subprocess.run([npm_cmd, "install"], cwd=frontend_dir, check=True)

                cmd = [npm_cmd, "run", "dev"]
                print(f"[frontend] 启动: {' '.join(cmd)}")
                procs.append((subprocess.Popen(cmd, cwd=frontend_dir), "frontend"))
        else:
            print("[frontend] 未找到 frontend/ 目录，跳过")

    # 3. 启动 OCR 节点
    if want_ocr:
        ocr_dir = os.path.join(ROOT, "ocr_server")
        if os.path.isdir(ocr_dir):
            py = ensure_venv("ocr_server", "requirements.txt")
            cmd = [py, "ocr_server.py", "--port", str(OCR_PORT)]
            print(f"[ocr] 启动: {' '.join(cmd)}")
            procs.append((subprocess.Popen(cmd, cwd=ocr_dir), "ocr"))
        else:
            print("[ocr] 未找到 ocr_server/ 目录，跳过")

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
