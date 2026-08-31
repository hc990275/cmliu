#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_cf_tools_stats.py - 定时把 json/best-cf-tools.json 中各项目的
GitHub star / fork 实时数同步回 JSON 文件。

设计要点：
  - 数据源：每个项目的 `url` 字段（形如 https://github.com/owner/repo），
    自动解析 owner/repo，无需额外维护仓库清单。
  - 通过 GitHub REST API 获取 stargazers_count / forks_count。
  - 仅当 star/fork 数值真的发生变化时才改写文件（并刷新 stats_updated_at），
    无变化时保持原文件字节不变，避免 CI 每天产生无意义的空提交。
  - 单个仓库 API 调用失败（限流 / 404 等）只跳过该项，不影响其余项目，
    也不会用旧值覆盖已有数据。

环境变量：
  JSON_FILE   目标 JSON 路径（默认 json/best-cf-tools.json）
  GH_TOKEN    GitHub 个人访问令牌（可选，用于提升 API 速率上限；公开仓库不传也可用）
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

JSON_FILE = os.environ.get("JSON_FILE", "json/best-cf-tools.json")
GITHUB_TOKEN = os.environ.get("GH_TOKEN", "")
API_BASE = "https://api.github.com"
REQUEST_TIMEOUT = 15

HEADERS = {"Accept": "application/vnd.github+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

URL_RE = re.compile(r"github\.com/([^/]+)/([^/?#]+)")


def parse_repo(url):
    """从 GitHub 链接解析出 (owner, repo)。无法解析时返回 (None, None)。"""
    m = URL_RE.search(url or "")
    if not m:
        return None, None
    owner, repo = m.group(1), m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def fetch_stats(owner, repo):
    """返回 (stars, forks)；非 200 或解析失败抛异常。"""
    resp = requests.get(
        f"{API_BASE}/repos/{owner}/{repo}", headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    if resp.status_code != 200:
        try:
            msg = resp.json().get("message", "")
        except Exception:
            msg = ""
        raise RuntimeError(f"HTTP {resp.status_code} {msg}".strip())
    data = resp.json()
    return data.get("stargazers_count"), data.get("forks_count")


def main():
    if not os.path.exists(JSON_FILE):
        print(f"❌ 未找到 JSON 文件: {JSON_FILE}")
        sys.exit(1)

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    projects = data.get("projects", [])
    if not isinstance(projects, list):
        print("❌ JSON 结构异常：缺少 projects 数组")
        sys.exit(1)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    changed_any = False
    ok, skipped = 0, 0

    for proj in projects:
        name = proj.get("name", proj.get("url", "?"))
        owner, repo = parse_repo(proj.get("url", ""))
        if not owner or not repo:
            print(f"⚠️  跳过（无法从 url 解析仓库）: {name}")
            skipped += 1
            continue
        try:
            stars, forks = fetch_stats(owner, repo)
        except Exception as e:
            print(f"⚠️  获取失败，保留原值并跳过: {owner}/{repo} -> {e}")
            skipped += 1
            continue

        if stars is None or forks is None:
            print(f"⚠️  返回数据缺失，保留原值并跳过: {owner}/{repo}")
            skipped += 1
            continue

        old_stars = proj.get("stars")
        old_forks = proj.get("forks")
        if old_stars == stars and old_forks == forks:
            print(f"ℹ️  {owner}/{repo}: 无变化 (stars={stars}, forks={forks})")
            ok += 1
            continue

        proj["stars"] = stars
        proj["forks"] = forks
        proj["stats_updated_at"] = now
        changed_any = True
        ok += 1
        print(
            f"✅ {owner}/{repo}: stars {old_stars} -> {stars}, "
            f"forks {old_forks} -> {forks}"
        )

    if changed_any:
        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, separators=(",", ": "))
            f.write("\n")
        print(f"\n已写入变更，更新时间戳: {now}")
    else:
        print("\n无数值变化，未改动文件（不产生提交）")

    print(f"成功 {ok} 项，跳过 {skipped} 项")
    sys.exit(0)


if __name__ == "__main__":
    main()
