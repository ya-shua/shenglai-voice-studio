"""声来 → 环形的心 · 产出留痕

把「她说 / 唱了什么」的产出事件投进环形的心记忆库
（闲聊圈自动入库：ring_ingest，skipVault、speaker=user——
这是工具产出的留痕，不是她的表态，也不吃她自己话的 3 倍权重）。

零依赖：spawn 环形的心 mcp/server.mjs，一次性 JSON-RPC，说完就退。
任何失败都只打 stderr 一行（panel.log 可见），**永远不挡住合成主流程**。
SHENGLAI_RING_OFF=1 可整体关闭。环形的心路径按候选表自动找，搬家不用改代码。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

_CANDIDATES = [
    os.environ.get("RING_ROOT"),
    "D:/我的电脑/桌面/插件/环形的心",
    "D:/我的电脑/桌面/环形的心",
    os.path.expanduser("~/环形的心"),
]


def _server_path() -> str | None:
    for p in _CANDIDATES:
        if not p:
            continue
        p = str(p).replace("\\", "/").rstrip("/")
        if os.path.isfile(p + "/mcp/server.mjs"):
            return p + "/mcp/server.mjs"
    return None


def _node_exe() -> str:
    """node.exe：先用 SnowLuma 自带的（它不在全局 PATH），找不到再赌 PATH。"""
    for p in ("D:/AI/QQ大肥鱼/SnowLuma/node.exe", "D:/AI/QQ大肥鱼/SnowLuma/node.exe".replace("/", "\\")):
        if os.path.isfile(p):
            return p
    return "node"


def notify(content: str, points: list[str] | None = None,
           source: str = "private", speaker: str = "user") -> None:
    """投一条产出留痕（fire-and-forget：后台线程，调用方立刻返回）。"""
    if os.environ.get("SHENGLAI_RING_OFF") == "1":
        return
    text = (content or "").strip()
    if not text:
        return
    t = threading.Thread(target=_send, args=(text, points or [], source, speaker), daemon=True)
    t.start()


def _send(text: str, points: list[str], source: str, speaker: str) -> None:
    try:
        server = _server_path()
        if not server:
            print("[ring_ingest] 找不到环形的心（mcp/server.mjs），留痕跳过", file=sys.stderr)
            return
        req = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                   "clientInfo": {"name": "shenglai-voice", "version": "1.0"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "ring_ingest",
                                   "arguments": {"content": text[:600],
                                                 "points": [str(p) for p in points][:8],
                                                 "source": source, "speaker": speaker}}}),
        ]) + "\n"
        out = subprocess.run([_node_exe(), server], input=req, capture_output=True,
                             timeout=25, text=True, encoding="utf-8")
        reply = ""
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("id") == 2:
                reply = str((m.get("result") or {}).get("content", [{}])[0].get("text", ""))
                break
        print(f"[ring_ingest] {reply or '无响应'}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 —— 留痕永远不该抛
        print(f"[ring_ingest] 失败（不影响主流程）: {e}", file=sys.stderr)
