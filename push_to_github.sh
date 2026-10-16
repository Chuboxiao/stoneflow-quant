#!/usr/bin/env bash
# Only create/push the homework repository. Does not post the issue comment.
set -euo pipefail
cd "$(dirname "$0")"

command -v gh >/dev/null || { echo '请先安装 GitHub CLI：brew install gh'; exit 1; }
if ! gh auth status --hostname github.com >/dev/null 2>&1; then
  gh auth login --hostname github.com --git-protocol https --web
fi
github_login="$(gh api user --jq .login)"
if [ "$(printf '%s' "$github_login" | tr '[:upper:]' '[:lower:]')" != 'chuboxiao' ]; then
  echo "当前登录账号是 $github_login，需要 Chuboxiao。"
  echo '请执行 gh auth login --hostname github.com --git-protocol https --web 登录正确账号后重试。'
  exit 1
fi
gh auth setup-git --hostname github.com
repository='Chuboxiao/stoneflow-quant'
if ! gh repo view "$repository" --json name >/dev/null 2>&1; then
  gh repo create "$repository" --public --description '穿石 Stoneflow：量化回测系统与趋势突破研究'
fi
expected_remote="https://github.com/$repository.git"
if git remote get-url origin >/dev/null 2>&1; then
  existing_remote="$(git remote get-url origin)"
  if [ "$existing_remote" != "$expected_remote" ]; then
    echo "origin 指向 $existing_remote，与 $expected_remote 不符；请检查后再推送。"
    exit 1
  fi
else
  git remote add origin "$expected_remote"
fi
git push -u origin main
echo "推送完成：https://github.com/$repository"
echo '评论文件已准备：SUBMISSION_COMMENT.md（含网页截图）。'
