# BTC永续 · 每日盘面日报机器人（手动发布版）

每天定时抓取 **BTCUSDT 永续合约**实时公开行情，纯规则算出**支撑位 / 压力位 / 量能 / 资金费率 / 持仓 / 盘口挂单墙**，生成一篇"交易员周报"风格的中文日报——**发布这一步由你完成**：机器人把文案送到你手上，你复制、粘贴到 X、点发送。

和全自动版的区别就一条：**不需要 X 开发者账号、不需要充值、不需要配置任何密钥**。整套东西只用 GitHub 免费额度就能跑。

- 主数据源 = **Bitget**（v2 合约公开行情），**币安**做辅助验证（价格交叉校验、主动买盘、持仓 24h 变化）。
- 算法与你的 PWA 完全同源：支撑/压力 v2（分形枢轴 × HVN × 挂单墙三源共振 + 触碰验证 + ATR 聚类 + 强度评分）、Wilder RSI/ATR、$100 万鲸鱼墙——从 `btc-perp-signal-pwa/src/lib` 逐行移植，**日报里的位和 PWA 面板是同一套数字**。

> 输出为基于公开行情的算法播报，非投资建议。

---

## 每天怎么用（核心动线）

部署好之后，每天早上 **08:35（北京时间）**：

1. 手机上的 **GitHub App** 弹一条通知：`📋 BTC日报 7月13日 · 现价63625（24h+0.4%）`——标题就是当天速览。
2. 点开这条 Issue，正文里是**整篇版**日报代码块（网页版右上角有复制按钮，App 内长按全选复制）。
3. 打开 X，粘贴，发送。有长文权限（Premium）就一条发完；没有的话点开 Issue 里折叠的**分条版**，先发第 1 条，再对它逐条"回复"串成楼。

全程 30 秒。两个备用入口：仓库里的 `reports/latest.txt`（收藏这个页面每天打开也行，历史日报按日期归档在同目录）；以及 Actions 运行页的构件下载。

盘中想临时加一期最新数据？Actions 页点一下 **Run workflow**，一分钟后新 Issue 就到。

---

## 部署（一次性，约 10 分钟，零密钥）

1. github.com 新建仓库 → 勾 **Private** → Create。
2. 上传代码：**Add file → Upload files**，把 `bot.py、analysis.py、exchanges.py、report.py、mock_data.py、requirements.txt、README.md、.gitignore、.env.example` 全部拖进去提交。
3. 工作流单独建（网页拖拽经常漏掉隐藏文件夹）：**Add file → Create new file**，文件名输入 `.github/workflows/daily-report.yml`，把 zip 里同名文件内容原样粘贴，提交。
4. **不需要配置任何 Secrets。** 工作流用 GitHub 内置令牌完成"存档进仓库 + 开 Issue"两件事，权限已在文件里声明。
5. 顶部 **Actions** → 启用工作流 → 点 **Run workflow** 跑一次验证：一分钟后应看到 ① Issues 页多了一条当天日报（自动带"日报"标签，旧一期会被自动关闭，列表永远只有最新一条）；② 仓库多了 `reports/latest.txt` 和当天日期的存档。
6. 手机装 **GitHub App** 并登录（或确保邮件通知打开），确认你 Watch 了这个仓库（自己建的默认就是）。之后每天 UTC 00:35（北京 08:35，UTC 日K刚收线）自动生成。

想改时间：编辑 workflow 的 `cron: "35 0 * * *"`（**UTC 时间**，北京时间减 8）；一天两报就再加一行 `- cron: "35 12 * * *"`。

---

## 本地运行（可选）

```bash
pip install -r requirements.txt
python bot.py            # 抓真实行情, 打印文案并存 last_report.txt
python bot.py --mock     # 离线演练 (文案带"请勿发布"水印)
python bot.py --compact  # 单条速报模式
```

---

## 配置项一览（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `SYMBOL` | `BTCUSDT` | 标的，可换任意 Bitget U 本位永续（如 `ETHUSDT`） |
| `TZ_OFFSET` | `8` | 文案时间戳时区（北京=8） |
| `COMPACT` | `0` | `1` = 单条速报模式 |
| `REPORT_FILE` | `last_report.txt` | 文案包落盘路径 |
| `ARCHIVE_DIR` | 空 | 设为 `reports` 时额外写 latest + 按日期归档（Actions 已配） |
| `WRITE_ISSUE` | `0` | `1` = 额外产出 Issue 标题/正文素材（Actions 已配） |

---

## 常见问题

- **没收到手机通知**：装 GitHub App 并登录；仓库右上角 Watch 设为 All activity；GitHub 个人设置 → Notifications 里确认 Issues 通知打开。就算不开通知，收藏 `reports/latest.txt` 页面每天点开也一样用。
- **Actions 报 push/Issue 权限 403**：仓库 Settings → Actions → General → Workflow permissions 选 **Read and write permissions** 后重跑（工作流已声明权限，个别账号策略下仍需这一步）。
- **定时任务停了**：GitHub 对长期无人活动的仓库会暂停 schedule 并发邮件，点邮件里的恢复按钮即可；建议每一两个月随手改点东西提交一次（机器人自己的存档提交不一定被算作"人的活动"）。
- **币安校验经常不可用**：GitHub 机房在美国，币安对美区 IP 返回 451，属预期——日报会自动降级为 Bitget 单源并如实标注，支撑/压力/量能不受影响。想保双源，用亚太 VPS 本地 cron 跑。
- **以后想升级全自动发布**：申请到 X API 后换用全自动版（`btc-daily-tweet-bot.zip`），分析引擎完全相同，无缝切换。

## 免责声明

本项目仅对公开行情做确定性规则计算与文本生成，不构成任何投资建议。
