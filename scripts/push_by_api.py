# -*- coding: utf-8 -*-
"""API 推送：github.com:443 被墙时走 api.github.com 只上传改动文件。

用法：python push_by_api.py <上一个已推送的提交 sha> <PAT 文件路径>
（PAT 路径走参数，不要写进任何会提交的文件。密钥本身只存本机。）
"""
import base64
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER, REPO = "ya-shua", "shenglai-voice-studio"
API = "https://api.github.com"

if len(sys.argv) < 3:
    sys.exit("用法：python push_by_api.py <上一个已推送提交 sha> <PAT 文件路径>")
TOKEN = Path(sys.argv[2]).read_text(encoding="utf-8").strip()
PREV = sys.argv[1]


def api(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body else None)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or b"{}")


def git(*a):
    return subprocess.check_output(["git", *a], cwd=str(ROOT)).decode("utf-8", "replace").strip()


head = api("GET", "/repos/%s/%s/git/ref/heads/main" % (OWNER, REPO))["object"]["sha"]
base_tree = api("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, head))["tree"]["sha"]
message = git("log", "-1", "--pretty=%B")

entries = []
for rel in git("diff", "--name-only", PREV).splitlines():
    fp = ROOT / rel
    if not fp.is_file():
        continue
    blob = api("POST", "/repos/%s/%s/git/blobs" % (OWNER, REPO),
               {"content": base64.b64encode(fp.read_bytes()).decode(), "encoding": "base64"})
    entries.append({"path": rel.replace("\\", "/"), "mode": "100644",
                    "type": "blob", "sha": blob["sha"]})

tree = api("POST", "/repos/%s/%s/git/trees" % (OWNER, REPO),
           {"base_tree": base_tree, "tree": entries})
commit = api("POST", "/repos/%s/%s/git/commits" % (OWNER, REPO),
             {"message": message, "tree": tree["sha"], "parents": [head]})
api("PATCH", "/repos/%s/%s/git/refs/heads/main" % (OWNER, REPO),
    {"sha": commit["sha"], "force": False})
print("已推送:", commit["sha"])
print("改动文件数:", len(entries))
