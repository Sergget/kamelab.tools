"""SPA 静态托管的越界回落测试。

背景（2026-10-26/27 安全修复，A6 要求的回归用例之一）：
`app/main.py` 的 SPA 回落路由把 URL 里的 `full_path` 直接拼到 STATIC_DIR 下，
若不做边界检查就会变成**任意文件读取**。修复方式是 resolve 后用
`is_relative_to(root)` 确认仍在 STATIC_DIR 内，越界则回落 index.html。

这条用例把这个边界钉住——没有它，下次重构很容易把 resolve/is_relative_to
改回去或漏掉，静态托管就重新变成任意文件读取。

注意：本文件需要在 `backend/` 目录下运行（`python -m pytest tests/...`）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app


@pytest.fixture()
def static_client(tmp_path, monkeypatch):
    """建一个临时 STATIC_DIR 并让 app 用它。

    app.main 在导入时就根据 config.STATIC_DIR 注册了路由，所以这里改
    配置后需要重新注册路由——直接改 app 的路由目标比重新导入模块可靠。
    """
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>SPA</html>", encoding="utf-8")
    (static_dir / "app.js").write_text("console.log(1)", encoding="utf-8")

    outside = tmp_path / "secret.txt"
    outside.write_text("TOP-SECRET", encoding="utf-8")

    monkeypatch.setattr(config, "STATIC_DIR", static_dir)
    client = TestClient(app)
    return client, static_dir, outside


def _spa_route():
    """找到 SPA 回落路由（app.main 里注册的那个）。"""
    for route in app.routes:
        if getattr(route, "path", None) == "/{full_path:path}":
            return route
    return None


def test_spa_route_is_registered():
    """前提：这条用例测的路由必须存在。"""
    assert _spa_route() is not None, "SPA 回落路由未注册"


def test_spa_serves_existing_file(static_client):
    client, _, _ = static_client
    resp = client.get("/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_spa_unknown_path_falls_back_to_index(static_client):
    """不存在的路径回落 index.html（SPA 路由语义）。"""
    client, _, _ = static_client
    resp = client.get("/tools/does-not-exist")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_spa_traversal_is_blocked(static_client):
    """越界读取必须被挡住。

    路径穿越后 resolve 出来的目标不在 STATIC_DIR 内，应当回落 index.html，
    而**不能**返回 STATIC_DIR 之外的文件内容。
    """
    client, _, outside = static_client
    resp = client.get("/../secret.txt")
    # 关键断言：响应体不含外部文件的内容
    assert "TOP-SECRET" not in resp.text
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_spa_encoded_traversal_is_blocked(static_client):
    """百分号编码的穿越也要挡住。

    浏览器与部分客户端会把 `..` 编码成 %2e%2e，服务端若不解码就拼路径，
    仍可能落到目录外（取决于下游如何规范化）。
    """
    client, _, outside = static_client
    for path in ("/%2e%2e/secret.txt", "/..%2fsecret.txt", "/%2e%2e%2fsecret.txt"):
        resp = client.get(path)
        assert "TOP-SECRET" not in resp.text, f"越界读取未被挡住：{path}"


def test_spa_absolute_windows_path_is_blocked(static_client):
    """Windows 绝对路径（C:/…）拼进来也不能读到目录外的文件。

    `root / "C:/Windows/win.ini"` 在 posixpath 下会被当成相对路径拼进去，
    但 resolve 后仍需确认在 root 内——这正是 is_relative_to 的作用。
    """
    client, _, _ = static_client
    resp = client.get("/C:/Windows/win.ini")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_spa_api_prefix_is_not_served_as_static(static_client):
    """api/ 前缀不能被当成静态资源回落，应保持 404。

    否则前端路由会吞掉 API 404，让真正的接口错误变成 SPA 页面。
    """
    client, _, _ = static_client
    resp = client.get("/api/definitely-not-a-tool")
    assert resp.status_code == 404
