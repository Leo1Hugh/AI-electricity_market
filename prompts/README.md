# Prompt 使用说明

## 给两个 ChatGPT Plus 账号

1. 确认仓库已经推到 GitHub，且 tag **contract-v1.0.0** 存在。
2. 打开账号 A，把 **prompts/generated/W1-R1.md** 全文粘贴进去。
3. 打开账号 B，把 **prompts/generated/W2-R1.md** 全文粘贴进去。
4. 如果账号能连 GitHub：让它直接开分支、开 PR（MODE=G）。
   如果只能聊天：让它按 MODE=B 输出 bundle，你把回复保存为 **inbox/W1-R1.md** / **inbox/W2-R1.md**。
5. 把 PR 链接（或 bundle 文件）交给 Lead（本会话）。

## 原则

- **一个账号一次只做一个任务。** 不要把 W1 和 W2 的任务混在同一个对话里。
- **不要在聊天里补契约。** 契约在仓库；prompt 里已带全文快照。
- **不要让它们"顺便改一下"别的文件。** 越界就拒收。
- **每轮结束让它们写 HANDOFF**，下一轮新开对话也能接上。

## 重新生成

改了 docs/ 后，重新生成 prompt：

~~~powershell
python scripts/build_prompt.py --task W1-R1
python scripts/build_prompt.py --task W2-R1
~~~

生成物在 **prompts/generated/**，不要手改生成物。
