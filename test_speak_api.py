# -*- coding: utf-8 -*-
"""对外语音接口端到端测试"""
import json
import urllib.request
import urllib.parse

BASE = "http://127.0.0.1:17878"


def get(path):
    req = urllib.request.Request(BASE + path)
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {}


print("① /api/speak（测试御姐 = MiMo，免费）:")
status, audio, _ = get("/api/speak?" + urllib.parse.urlencode({
    "voice": "测试御姐",
    "text": "你好，我是通过对外语音接口生成的，环形的心也能用。",
    "rate": "1.0"}))
print(f"   HTTP {status} | {len(audio)//1024} KB | 头部: {audio[:3]}")

print("② /api/speak?json=1（JSON 元信息）:")
status, body, _ = get("/api/speak?" + urllib.parse.urlencode({
    "voice": "测试御姐", "text": "第二条测试。", "json": "1"}))
meta = json.loads(body)
print(f"   HTTP {status} | file: {meta.get('file')} | url: {meta.get('url', '')[:50]}")

print("③ /api/speak（不存在的音色 → 应返回 400 错误说明）:")
status, body, _ = get("/api/speak?" + urllib.parse.urlencode({
    "voice": "不存在的音色", "text": "测试"}))
print(f"   HTTP {status} | {body.decode('utf-8')[:100]}")

print("④ /api/speak/voices:")
status, body, _ = get("/api/speak/voices")
voices = json.loads(body)["voices"]
print(f"   HTTP {status} | {len(voices)} 个音色: {[v['name'] for v in voices]}")
