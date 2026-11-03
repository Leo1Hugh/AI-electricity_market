# 把本地"契约引导提交"嫁接到远端 main 上，并推送 tag/分支。
# 用法（在仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts/publish_to_github.ps1
# 需要：本机可访问 github.com，且已登录 GitHub（浏览器/GCM 会弹一次）。
#
# 原理：本地是 ZIP 下载、没有 .git 历史；直接 push 会与远端分叉。
# 这里先 fetch 远端 main，再用 reset --mixed 把索引对齐远端（不动工作区），
# 最后只把"引导提交"里的新文件重新 add 上去，形成远端历史的子提交。

param(
    [string]$Remote = "https://github.com/Leo1Hugh/AI-electricity_market.git",
    [string]$SetupRef = "HEAD"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Fail($msg) {
    Write-Host ""
    Write-Host "FAILED: $msg" -ForegroundColor Red
    exit 1
}

Write-Host "== 1. 检查 git ==" -ForegroundColor Cyan
git rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) { Fail "当前目录不是 git 仓库" }

git config core.quotepath false
$setup = (git rev-parse $SetupRef).Trim()
if ($LASTEXITCODE -ne 0 -or -not $setup) { Fail "找不到 SetupRef=$SetupRef" }
Write-Host "setup commit: $setup"

$files = @(git diff-tree --root --no-commit-id --name-only -r $setup)
if ($LASTEXITCODE -ne 0 -or $files.Count -eq 0) { Fail "setup 提交里没有文件" }
Write-Host "setup files: $($files.Count)"

git branch -f setup/contract-v1.0.0 $setup *> $null
if ($LASTEXITCODE -ne 0) { Fail "无法创建 setup/contract-v1.0.0 分支" }

Write-Host "== 2. 配置 remote ==" -ForegroundColor Cyan
git remote get-url origin *> $null
if ($LASTEXITCODE -eq 0) {
    git remote set-url origin $Remote
} else {
    git remote add origin $Remote
}
if ($LASTEXITCODE -ne 0) { Fail "配置 remote 失败" }
Write-Host "origin: $Remote"

Write-Host "== 3. 拉取远端 main ==" -ForegroundColor Cyan
# 网络卡住时 20 秒内低速就放弃，避免窗口一直转圈
$env:GIT_HTTP_LOW_SPEED_LIMIT = "1000"
$env:GIT_HTTP_LOW_SPEED_TIME = "20"
git fetch origin main
if ($LASTEXITCODE -ne 0) { Fail "拉取失败：检查网络/代理，或先在浏览器登录 GitHub" }

Write-Host "== 4. 对齐远端索引（不改变工作区） ==" -ForegroundColor Cyan
git reset --mixed origin/main
if ($LASTEXITCODE -ne 0) { Fail "reset --mixed origin/main 失败" }

$deleted = @(git status --porcelain | Where-Object { $_ -match '^( D|D )' })
if ($deleted.Count -gt 0) {
    Write-Host "检测到远端有、本机缺失的文件：" -ForegroundColor Yellow
    $deleted | Select-Object -First 10 | ForEach-Object { Write-Host "  $_" }
    Fail "先补齐这些文件，再运行本脚本；不要提交删除"
}

Write-Host "== 5. 只重新加入 setup 里的新文件 ==" -ForegroundColor Cyan
git add -- $files
if ($LASTEXITCODE -ne 0) { Fail "git add 失败" }

$staged = @(git diff --cached --name-only)
if ($staged.Count -eq 0) {
    Write-Host "没有需要提交的新文件；可能已经推送过。" -ForegroundColor Yellow
} else {
    git commit -m "chore: freeze modeling contract v1.0.0 and bootstrap GitHub workflow"
    if ($LASTEXITCODE -ne 0) { Fail "commit 失败" }
}

Write-Host "== 6. 打 tag / 建工作分支 ==" -ForegroundColor Cyan
git tag -fa contract-v1.0.0 -m "freeze modeling contract v1.0.0"
if ($LASTEXITCODE -ne 0) { Fail "打 tag 失败" }

git branch -f w1/r1-panel contract-v1.0.0
git branch -f w2/r1-harness contract-v1.0.0
if ($LASTEXITCODE -ne 0) { Fail "建工作分支失败" }

Write-Host "== 7. push ==" -ForegroundColor Cyan
git push -u origin main
if ($LASTEXITCODE -ne 0) { Fail "push main 失败：检查 GitHub 登录/权限" }

git push origin refs/tags/contract-v1.0.0 w1/r1-panel w2/r1-harness
if ($LASTEXITCODE -ne 0) { Fail "push tag/分支失败" }

Write-Host ""
Write-Host "OK. 仓库已更新：" -ForegroundColor Green
Write-Host "  https://github.com/Leo1Hugh/AI-electricity_market"
Write-Host ""
Write-Host "下一步：" -ForegroundColor Cyan
Write-Host "  1) Settings -> Branches -> 保护 main（Require PR + contract-ci）"
Write-Host "  2) 把 prompts/generated/W1-R1.md 粘给账号 A"
Write-Host "  3) 把 prompts/generated/W2-R1.md 粘给账号 B"
