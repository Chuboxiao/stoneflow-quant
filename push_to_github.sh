#!/usr/bin/env bash
# Only create/push the homework repository. Does not post the issue comment.
set -euo pipefail
cd "$(dirname "$0")"

# GitHub CLI / Git do not automatically inherit macOS System Settings proxies.
# Respect explicit terminal settings; otherwise read the existing HTTPS proxy.
if [ -z "${HTTPS_PROXY:-${https_proxy:-}}" ] && [ "$(uname -s)" = 'Darwin' ]; then
  task_proxy_config="$(scutil --proxy 2>/dev/null || true)"
  task_proxy_enabled="$(printf '%s\n' "$task_proxy_config" | awk '$1 == "HTTPSEnable" { print $3; exit }')"
  task_proxy_host="$(printf '%s\n' "$task_proxy_config" | awk '$1 == "HTTPSProxy" { print $3; exit }')"
  task_proxy_port="$(printf '%s\n' "$task_proxy_config" | awk '$1 == "HTTPSPort" { print $3; exit }')"
  if [ "$task_proxy_enabled" = '1' ] && [ -n "$task_proxy_host" ] && [[ "$task_proxy_port" =~ ^[0-9]+$ ]]; then
    export HTTPS_PROXY="http://$task_proxy_host:$task_proxy_port"
    export HTTP_PROXY="${HTTP_PROXY:-$HTTPS_PROXY}"
    export https_proxy="$HTTPS_PROXY"
    export http_proxy="$HTTP_PROXY"
    echo "已使用 macOS 系统代理：$task_proxy_host:$task_proxy_port"
  fi
fi

echo '检查 GitHub 连接…'
if ! curl --silent --show-error --connect-timeout 8 --max-time 15 \
    --output /dev/null https://github.com/login/device; then
  echo 'GitHub 连接失败。请确认代理软件正在运行，再重试；尚未推送。'
  exit 1
fi
if [ "${1:-}" = '--check-network' ]; then
  echo 'GitHub 网络检查通过；未执行登录、推送或评论。'
  exit 0
fi

command -v gh >/dev/null || { echo '请先安装 GitHub CLI：brew install gh'; exit 1; }
if ! gh auth status --hostname github.com >/dev/null 2>&1; then
  # workflow scope is needed to push the included GitHub Actions test workflow.
  if ! gh auth login --hostname github.com --git-protocol https --web --scopes workflow; then
    echo '登录未完成。重跑脚本后，请使用新生成的验证码。尚未推送。'
    exit 1
  fi
fi
github_login="$(gh api user --jq .login)"
if [ "$(printf '%s' "$github_login" | tr '[:upper:]' '[:lower:]')" != 'chuboxiao' ]; then
  echo "当前登录账号是 $github_login，需要 Chuboxiao。"
  echo '请执行 gh auth login --hostname github.com --git-protocol https --web --scopes workflow 登录正确账号后重试。'
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
