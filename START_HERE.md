# 先看这里：把仓库推上 GitHub（3 步）

> 你不需要懂 Git。按下面做，全程 5 分钟。

## 第 1 步：双击 publish.cmd

1. 打开文件夹：**E:\Desktop\AI-electricity_market-main**
2. 找到 **publish.cmd**，双击。
3. 如果 Windows 弹出“已保护你的电脑”：点 **更多信息** → **仍要运行**。
4. 会弹 GitHub 登录窗口：登录 **Leo1Hugh** 的账号。
5. 看到 **OK. 仓库已更新** 就成功了；窗口会停住，按任意键关闭。

> 不要从 C:\Users\lhx12 运行；publish.cmd 会自动切到仓库目录。
> 不要手打 powershell 命令；双击就够了。

## 第 2 步：保护 main 分支

打开 https://github.com/Leo1Hugh/AI-electricity_market/settings/branches

- Add branch protection rule
- Branch name pattern: **main**
- 勾选 **Require a pull request before merging**
- 勾选 **Require status checks to pass before merging**
- 搜索并选中 **contract-ci**
- Save

## 第 3 步：把两份 prompt 粘给两个 ChatGPT 账号

- 账号 A：把 **prompts/generated/W1-R1.md** 全文复制，粘贴，发送。
- 账号 B：把 **prompts/generated/W2-R1.md** 全文复制，粘贴，发送。

然后让它们：
- 能连 GitHub：直接开分支、开 PR，把 PR 链接发给你；
- 不能连 GitHub：回复开头写 MODE=B，输出 bundle；你把回复保存成 **inbox/W1-R1.md** 和 **inbox/W2-R1.md**。

## 失败了怎么办

不要关窗口。把窗口最后 20 行复制/截图，发回给 Lead。

| 错误 | 原因 | 解决 |
|---|---|---|
| 找不到 scripts/publish_to_github.ps1 | 在 C:\\Users\\lhx12 运行，不在仓库目录 | 双击 publish.cmd，不要手打 |
| 无法将 Bypass 转换为 ExecutionPolicyScope | 少打了 powershell | 双击 publish.cmd |
| fetch 失败 / Connection was reset | 网络连不上 GitHub | 开代理/VPN，或换网络；再双击一次 |
| push 需要登录 | 没登录 GitHub | 弹窗里登录 Leo1Hugh |
