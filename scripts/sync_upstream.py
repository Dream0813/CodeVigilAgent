#!/usr/bin/env python3
"""同步项目组总仓库（上游）的更新到本地桌面程序副本。

为什么不用 git fetch / git pull
--------------------------------
本机网络下 github.com:443 不可达（代理只放行 api.github.com /
codeload.github.com / raw.githubusercontent.com），git 的 https 传输必然报
    schannel: failed to receive handshake
    CONNECT tunnel failed, response 502
所以绕开 git 传输层，只走实测可用的只读通道：

    api.github.com                  查分支最新 commit、算增量文件清单
    raw.githubusercontent.com       按 sha 下载单个文件（只下变动的）

判断「有没有更新」只看一件事：上游最新 sha 本地是否已经含有。
本地专门有一批未推送的提交，所以绝不能拿整包跟本地逐文件比 —— 那会把
自己的新代码当成「上游旧版本」误报。这里只取上游「新提交」涉及的文件，
再做三方比对（本地 / 上游基准版本 / 上游新版本）：

    本地 == 新版本   -> 已同步，跳过
    本地 == 基准版本 -> 本地没动过，可安全覆盖
    其它             -> 冲突，不覆盖，列出来等人工合并

用法
----
    python scripts/sync_upstream.py                 只检查，打印报告
    python scripts/sync_upstream.py --apply         同步（安全文件直接写）
    python scripts/sync_upstream.py --apply --force 冲突文件也覆盖（会丢本地改动）
    python scripts/sync_upstream.py --json          机器可读（给自动化用）

退出码  0 已最新 / 10 已同步 / 11 有冲突待人工 / 2 网络或其它错误
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = "enternalna-Koh/CodeVigilAgent"          # 项目组总仓库（只读，绝不写入）
BRANCH = "codex/desktop-agent-chat-review"      # 桌面程序所在分支
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
UA = "CodeVigilAgent-sync/3.0"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(HERE)
STATE_DIR = os.path.join(os.path.expanduser("~"), ".reviewagent")
STATE_FILE = os.path.join(STATE_DIR, "upstream_state.json")
REPORT_DIR = r"D:\ai创客大赛\03_产出"

SKIP_PREFIX = (".git/", "node_modules/", "__pycache__/", ".reviewagent/", ".venv/",
               "desktop-app/releases/")
SKIP_SUFFIX = (".pyc", ".pyo")


def out(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))


def http_get(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def api(path: str) -> dict:
    return json.loads(http_get(API + path).decode("utf-8"))


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout.strip()


def has_commit(sha: str) -> bool:
    return git("cat-file", "-e", sha + "^{commit}")[0] == 0


def is_ancestor(sha: str) -> bool:
    return git("merge-base", "--is-ancestor", sha, "HEAD")[0] == 0


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return {}


def save_state(remote_sha: str) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"upstream_sha": remote_sha, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=2)


def known_upstream_base() -> str | None:
    """找一个「上游也存在」的基准提交，用来算增量。"""
    for cand in (load_state().get("upstream_sha"), git("rev-parse", f"origin/{BRANCH}")[1]):
        if cand and has_commit(cand):
            return cand
    code, raw = git("log", "--format=%H", "-40")
    for sha in raw.splitlines():
        if has_commit(sha) and is_ancestor(sha):
            return sha
    return None


def diff_files(base: str, head: str) -> tuple[list[dict], list[dict]]:
    data = api(f"/repos/{REPO}/compare/{base}...{head}")
    commits = [{"sha": c["sha"], "message": c["commit"]["message"].splitlines()[0],
                "date": c["commit"]["author"]["date"],
                "author": c["commit"]["author"]["name"]}
               for c in data.get("commits", [])]
    files = [{"path": f["filename"], "status": f["status"]} for f in data.get("files", [])]
    return commits, files


def fetch_file(sha: str, path: str) -> bytes | None:
    """按 sha 取单个文件；文件在该版本不存在时返回 None。"""
    url = f"{RAW}/{REPO}/{sha}/{urllib.parse.quote(path)}"
    try:
        return http_get(url, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def plan(files: list[dict], base: str, head: str) -> dict:
    """三方比对，产出 安全写入 / 已同步 / 冲突 三组。"""
    safe: list[dict] = []          # {"path", "data"(None=删除), "kind"}
    skipped: list[str] = []
    conflicted: list[str] = []
    for f in files:
        path = f["path"]
        if any(path.startswith(p) for p in SKIP_PREFIX) or path.endswith(SKIP_SUFFIX):
            continue
        new = None if f["status"] == "removed" else fetch_file(head, path)
        old = fetch_file(base, path)
        dst = os.path.join(REPO_DIR, path)
        local = None
        if os.path.exists(dst):
            with open(dst, "rb") as fh:
                local = fh.read()

        if local is not None and new is not None and local == new:
            skipped.append(path)
        elif local == old:                      # 本地没动过（含新增/删除的对称情形）
            kind = "del" if new is None else ("add" if local is None else "mod")
            safe.append({"path": path, "data": new, "kind": kind})
        elif local is None and f["status"] == "added":
            safe.append({"path": path, "data": new, "kind": "add"})
        else:
            conflicted.append(path)
    return {"safe": safe, "skipped": skipped, "conflicted": conflicted}


def apply_plan(p: dict, force: bool, base: str, head: str) -> list[str]:
    written: list[str] = []
    todo = list(p["safe"])
    if force:
        for path in p["conflicted"]:
            todo.append({"path": path, "data": fetch_file(head, path), "kind": "mod"})
    for item in todo:
        path, data = item["path"], item["data"]
        dst = os.path.join(REPO_DIR, path)
        if data is None:
            if os.path.exists(dst):
                os.remove(dst)
                written.append(f"- {path}")
            continue
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        written.append(f"{item['kind']} {path}")
    return written


def write_report(head: dict, commits: list[dict], p: dict, written: list[str], local_sha: str) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"上游同步报告-{time.strftime('%Y-%m-%d')}.md")
    total = len(p["safe"]) + len(p["skipped"]) + len(p["conflicted"])
    lines = [
        f"# 上游同步报告 {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"- 总仓库：`{REPO}` 分支 `{BRANCH}`",
        f"- 上游最新：`{head['sha'][:8]}` {head['message']}（{head['date']}，{head['author']}）",
        f"- 本地 HEAD：`{local_sha[:8]}`",
        f"- 新提交 {len(commits)} 个，涉及文件 {total} 个",
        "",
        "## 新提交",
        "",
    ]
    lines += [f"- `{c['sha'][:8]}` {c['message']}（{c['author']}）" for c in commits] or ["- 无"]
    if written:
        lines += ["", "## 已写入", ""] + [f"- `{w}`" for w in written]
    if p["conflicted"]:
        lines += ["", "## 冲突（本地也改过，未覆盖，需人工合并）", ""] + \
                 [f"- `{p_}`" for p_ in p["conflicted"]]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="同步项目组总仓库到本地桌面程序副本")
    ap.add_argument("--apply", action="store_true", help="实际写入文件（默认只检查）")
    ap.add_argument("--force", action="store_true", help="冲突文件也强制覆盖")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    try:
        raw = api(f"/repos/{REPO}/branches/{BRANCH}")["commit"]
        head = {"sha": raw["sha"],
                "message": raw["commit"]["message"].splitlines()[0],
                "date": raw["commit"]["author"]["date"],
                "author": raw["commit"]["author"]["name"]}
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, KeyError) as exc:
        out(f"[网络错误] 无法访问 GitHub API：{exc}")
        out("  确认代理已开启（需要 https_proxy=http://127.0.0.1:9710）")
        return 2

    local_sha = git("rev-parse", "HEAD")[1]

    if not args.json:
        out(f"总仓库     {REPO} @ {BRANCH}")
        out(f"上游最新   {head['sha'][:8]}  {head['message']}  ({head['date']})")
        out(f"本地 HEAD  {local_sha[:8]}")
        out("")

    if head["sha"] == local_sha or (has_commit(head["sha"]) and is_ancestor(head["sha"])):
        if args.json:
            print(json.dumps({"status": "up-to-date", "upstream": head["sha"], "local": local_sha},
                             ensure_ascii=False))
        else:
            out("已是最新，无需更新。")
        save_state(head["sha"])
        return 0

    base = known_upstream_base()
    if not base:
        out("[错误] 找不到可比对的上游基准提交，已中止（请手动确认分支历史）。")
        return 2

    try:
        commits, files = diff_files(base, head["sha"])
        p = plan(files, base, head["sha"])
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        out(f"[错误] 计算增量失败：{exc}")
        return 2

    written = apply_plan(p, args.force, base, head["sha"]) if args.apply else []
    report = write_report(head, commits, p, written, local_sha)
    safe_paths = [i["path"] for i in p["safe"]]

    if args.json:
        print(json.dumps({"status": "updated" if written else ("conflict" if p["conflicted"] else "pending"),
                          "upstream": head["sha"], "local": local_sha, "base": base,
                          "commits": [c["message"] for c in commits],
                          "safe": safe_paths, "skipped": p["skipped"], "conflicted": p["conflicted"],
                          "written": written, "report": report}, ensure_ascii=False))
    else:
        out(f"上游新提交 {len(commits)} 个（基准 {base[:8]} → {head['sha'][:8]}）：")
        for c in commits[:15]:
            out(f"   * {c['sha'][:8]} {c['message']}  ({c['author']})")
        out("")
        out(f"可安全同步 {len(safe_paths)} / 已一致 {len(p['skipped'])} / 冲突 {len(p['conflicted'])}")
        for path in safe_paths[:20]:
            out(f"   ~ {path}")
        if p["conflicted"]:
            for path in p["conflicted"]:
                out(f"   ! {path}")
        out("")
        out(f"已写入 {len(written)} 个文件" if args.apply else "（未写入，加 --apply 才写）")
        out(f"报告：{report}")

    if args.apply:
        save_state(head["sha"])
    if p["conflicted"] and not args.force:
        return 11
    return 10 if written else 0


if __name__ == "__main__":
    sys.exit(main())
