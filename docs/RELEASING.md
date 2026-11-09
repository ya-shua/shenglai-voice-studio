# 声来 · 更新与发布说明

本文件写给维护者：怎么改版本、怎么提交、怎么推到 GitHub、以及网络不通时怎么办。

---

## 仓库信息

| 项 | 值 |
|---|---|
| 远端仓库 | https://github.com/ya-shua/shenglai-voice-studio |
| 默认分支 | `main` |
| 许可证 | MIT |
| 本地仓库根 | `插件目录（本地仓库根）`（和插件源在一起，改完直接提交） |
| 插件市场清单 | `D:\AI\插件\plugins\marketplace.json`（与本插件同仓储外的一级目录） |

> 只提交**插件本体**（代码 / 面板 / 文档 / 清单）。设计稿、实验数据、截图素材不要进仓库。

---

## 一、改版本号（3 处必须一致）

```
lib/config.py                       VERSION = "x.y.z"
.zcode-plugin/plugin.json           "version": "x.y.z"
D:\AI\插件\plugins\marketplace.json "version": "x.y.z"
```

版本号不一致会出现这类症状：

- 面板一直提示「已更新到新版本」（服务端与客户端版本对不上）
- 插件市场显示旧版本，装了不生效
- `?v={VERSION}` 缓存串没变，浏览器还跑旧 JS（改完前端记得 Ctrl+F5）

同时更新 `docs/CHANGELOG.md`：在最上方加 `## [x.y.z] - YYYY-MM-DD`，写清新增 / 修复 / 变更。

---

## 二、提交（本地 git）

```powershell
cd 插件目录（本地仓库根）
git status --short          # 先看清楚改了什么
git add -A
git commit -m "feat: 一句话说清改了什么；vx.y.z"
```

### 隐私门禁（pre-push 钩子）

仓库里装了一个 **仅对本仓库生效** 的钩子：`.git/hooks/pre-push`。

| 级别 | 拦截内容 |
|---|---|
| 硬拦 | 以 `sk-` / `ghp_` / `github_pat_` 开头的密钥串、邮箱地址、11 位手机号 |
| 软警告 | 出现 `C:\Users\`、`D:\AI\` 这类本机绝对路径（只提示，不阻止） |

- 命中硬拦会直接拒绝推送，按提示把那行改成占位符再提交
- 确实要跳过：`git push --no-verify`
- 彻底移除：删掉 `.git/hooks/pre-push` 文件即可（不影响别人）

---

## 三、推送（HTTPS + PAT）

本机不能用 SSH（token 没有 `admin:public_key` 权限），统一走 HTTPS + Personal Access Token。

令牌位置：**只存本机，不要把路径或值写进任何会提交的文件**（本文件 v1.4.1 曾误写路径，后已移除——历史无法改写，介意请轮换 PAT）。`<PAT 文件路径（勿写进仓库）>`（只含 40 位 token，账号 `ya-shua`，scope = `repo`）。

**不要把 token 写进 `.git/config` 或任何文件**，用一次性环境变量传：

```powershell
cd 插件目录（本地仓库根）
$pat = (Get-Content "<PAT 文件路径（勿写进仓库）>" -Raw).Trim()
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$pat"))
$env:GIT_CONFIG_COUNT = "1"
$env:GIT_CONFIG_KEY_0 = "http.extraHeader"
$env:GIT_CONFIG_VALUE_0 = "Authorization: Basic $b64"
git push origin main
Remove-Item Env:\GIT_CONFIG_COUNT,Env:\GIT_CONFIG_KEY_0,Env:\GIT_CONFIG_VALUE_0
```

---

## 四、github.com 连不上时（常见）

症状：`Failed to connect to github.com port 443` / `Recv failure: Connection was reset`。

原因通常是本机 hosts 里绑定的 GitHub IP 失效（`C:\Windows\System32\drivers\etc\hosts`，需要管理员才能改）。

**先确认是哪一层挂了：**

```powershell
curl.exe -s -o NUL -w "github %{http_code}\n" --max-time 10 https://github.com
curl.exe -s -o NUL -w "api    %{http_code}\n" --max-time 10 https://api.github.com
```

- `api.github.com` 返回 200、`github.com` 不通 → 用下面的 **API 推送方案**
- 两个都不通 → 网络问题，换网络或稍后重试

### API 推送方案（不依赖 github.com:443）

`api.github.com` 走的是另一条线路，通常仍然可用。流程是：创建 blob → 创建 tree → 创建 commit → 移动分支引用，只上传**本次改动的那几个文件**。

```python
# 用法：python push_by_api.py <上一个本地提交 sha>
import base64, json, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(r"插件目录（本地仓库根）")
TOKEN = Path(r"<PAT 文件路径（勿写进仓库）>").read_text(encoding="utf-8").strip()
OWNER, REPO = "ya-shua", "shenglai-voice-studio"
API = "https://api.github.com"

def api(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body else None)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read() or b"{}")

def git(*a):
    return subprocess.check_output(["git", *a], cwd=str(ROOT)).decode().strip()

prev = sys.argv[1]                                    # 上一个已推送的提交
head = api("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/main")["object"]["sha"]
base_tree = api("GET", f"/repos/{OWNER}/{REPO}/git/commits/{head}")["tree"]["sha"]
message = git("log", "-1", "--pretty=%B")             # 用本地最新提交的信息

entries = []
for rel in git("diff", "--name-only", prev).splitlines():
    fp = ROOT / rel
    if not fp.is_file():
        continue
    blob = api("POST", f"/repos/{OWNER}/{REPO}/git/blobs",
               {"content": base64.b64encode(fp.read_bytes()).decode(), "encoding": "base64"})
    entries.append({"path": rel.replace("\\", "/"), "mode": "100644",
                    "type": "blob", "sha": blob["sha"]})

tree = api("POST", f"/repos/{OWNER}/{REPO}/git/trees",
           {"base_tree": base_tree, "tree": entries})
commit = api("POST", f"/repos/{OWNER}/{REPO}/git/commits",
             {"message": message, "tree": tree["sha"], "parents": [head]})
api("PATCH", f"/repos/{OWNER}/{REPO}/git/refs/heads/main",
    {"sha": commit["sha"], "force": False})
print("已推送:", commit["sha"])
```

> 注意：API 推送**绕过了 pre-push 钩子**。推之前自己先 `git diff --cached` 扫一眼，别把密钥带上去。

---

## 五、发版检查清单

- [ ] `lib/config.py` / `plugin.json` / `marketplace.json` 版本号一致
- [ ] `docs/CHANGELOG.md` 有对应条目
- [ ] 前端改动后刷新面板验证（`Ctrl+F5` 清缓存）
- [ ] 面板能起（双击桌面「声来」）且右上角「⏻ 关闭」能正常停掉
- [ ] `git push` 成功（或 API 推送成功），远端 commit 与本地一致
- [ ] 需要时重打分发包：`https://github.com/ya-shua/shenglai-voice-studio/archive/refs/heads/main.zip`