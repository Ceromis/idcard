# KARDS 前端项目开发进度说明

> 最后更新: 2026-06-29
> 工作区: `C:\开发`

---

## 0. TL;DR 当前状态

| 项 | 状态 |
|---|---|
| 前端 5 个页面 | ✅ 完成 (`account` / `recruit` / `deck` / `diy` / `settings`) |
| 公开招募核心流程 | ✅ 完成 (登录 → 拉词条 → 勾选 → 招 → 领) |
| 卡组码解析 | ✅ 完成 (右侧渲染 + 下载) |
| 限定寻访 (DIY) | ✅ 完成 (我要投稿 / 我的投稿) |
| **注册登录重构 (新)** | ✅ **完成** (用户名+密码; 邮箱选填; SMTP 接口预留) |
| **绑定机制重构 (新)** | ✅ **完成** (校验指令, bot 监听群消息自动绑定) |
| 邮箱验证码 SMTP 真发 | ✅ 接口就绪 (`youxiang/youxiang.txt` 配 enabled=true 即生效) |
| 跨设备账号同步 | ❌ 未做 (localStorage 单设备) |
| 端到端测试 | ✅ 9 项 E2E + 3 项单元 + 校验指令 5 步全过 |

**当前可立即跑通**: 启动 `serve.py` → 浏览器开 `account.html` → 用 `admin` / `admin123` 登录 → 5 个页面全可访问, 但 `recruit.html` / `diy.html` 需要先绑定 UID/diyQQ, 绑定走"获取校验码 + 群内发送指令"新流程。
## 1. 项目概览

本项目是一个 **KARDS (二战卡牌游戏) 配套前端站点**, 由 5 个 HTML 页面 + 1 个 JS 模块 + 1 个本地静态服务器组成, 与两套 NoneBot 插件后端通信:

| 端 | 名称 | 角色 | 默认地址 |
|---|---|---|---|
| 前端 | `serve.py` + 5 个 `.html` | 浏览器访问的 UI + 接收验证码的轻量 API | `http://localhost:8000` |
| 后端 A | `nonebot_kards_recruit_plugin.py` | 公开招募 (群内抽卡 / 词条刷新) | `http://110.42.63.235:8080` |
| 后端 B | `xunfang.py` | 限定寻访 (DIY 玩家投稿卡牌) | `http://192.168.10.100:8090` |

`account.html` 是统一入口 (登录 / 注册 / 绑定 UID), 登录后其他页面才能进入。

---

## 2. 已完成功能 ✅

### 2.1 账号系统 (前端 localStorage, 2026-06-29 重构)
- **账号模型**: `username` (3-20 位字母/数字/下划线, 唯一) + 可选 `email` + `pwdHash` + `uid` (公开招募 UID) + `diyQQ` (限定寻访 QQ)
- **注册**: 仅 `username` + `pwd` (6+ 位), 不再卡邮箱验证码. 邮箱注册后到 邮 箱 tab 选填
- **登录**: 用户名 或 已绑定邮箱 都可登录
- **邮箱绑定 (可选)**: `bindEmail(email, code)` + `unbindEmail()`, 走 `sendCode` → 后端 SMTP (或 dev 模式弹窗)
- **SMTP 配置**: 读 `youxiang/youxiang.txt` (JSON, `enabled=false` 时回 devCode, 真实部署改为 true + 填实际 SMTP 信息)
- localStorage 预置管理员: `admin` / `admin123` (沿用旧密码)
- `login` 自愈: 找不到账号时自动 `ensureSeed`, 防 localStorage 异常丢失管理员
- 改密码 (`changePassword`)

### 2.2 公开招募 (kards)
- 输入 UID → 后端 `POST /kards/user_info` 拉取词条/刷新次数/招募状态
- 5 个词条, 最多勾 3 个, 最少 1 个
- "刷新词条" 按钮 → `POST /kards/refresh_tags` (上限 3/天, 本地显示 `3/3` `2/3` …)
- "开始招募" 按钮 → `POST /kards/start_recruit`
- 词条高亮: `资深卡牌` 金色, `高级资深卡牌` 金色渐变
- 预计招募时长本地检测: 选 `资深卡牌` = `00:60:00`, 选 `高级资深卡牌` = `02:00:00`, 选了高资但没勾则拦截并提示"不要你就给作者"
- jjc.png 图标显示剩余许可数

### 2.3 卡组解析
- 输入框接受 `%%12|34;56;78...` 格式卡组码
- "生成" 调 `POST /kards/draw_deck` (`{deck_code: "..."}`) → 右侧渲染卡组图
- 卡牌数额外 +1 (本地图层留 1 张余量)
- "下载" 按钮保存渲染结果

### 2.4 限定寻访 (DIY) — 独立页 `diy.html`
- 双 tab: `我要投稿` / `我的投稿`
- `我要投稿` 副切换: `全部 DIY` / `联动寻访` → 调 `GET /diy/random` 或 `/diy/random_special`
- 左列展示卡牌大图 (后端返回的 `image_base64`)
- 右列: 后端返回什么字段就显示什么 (`author` / `submitted_at` / `likes` / `dislikes` / `candies` / `state` …)
- 评价按钮 (👍 / 👎 / 🍬) → `POST /diy/react` (`{uid, card_id, action}`)
- "再来一张" 重新拉随机
- `我的投稿` 调 `POST /diy/user_cards` 展示栅格缩略图
- 门控: 未登录跳 `account.html`; 已登录未绑 diyQQ 弹"需先绑定"提示

### 2.5 校验指令绑定机制 (核心新功能, 2026-06-29 重构) ✅
**架构** (前端 + 后端 + bot 三方协调, 取代旧的 6 位码机制):

```
┌────────────────┐  点 "获取校验码"   ┌──────────────────┐
│  浏览器        │ ────────────────▶ │  serve.py        │
│                │  POST /verify_token│  (frontend:8000)│
│  生成 token    │  + 拿到 token      │  存 verify_tokens│
│  弹出指令       │  轮询 /verify_token│  .json (10min)  │
│  "校验kards账号182*+"              └────────┬─────────┘
│  "点我复制指令"                            │ 等回调
│                                            ▼
│  ┌──────────────────────────┐  群内发指令  ┌──────────────────┐
│  │  QQ 群                  │ ──────────▶  │ NoneBot 插件     │
│  │                         │  bot 监听    │ on_message()     │
│  │  用户在群内粘贴发送      │  正则匹配    │ /verify_token/   │
│  │  "校验kards账号182*+"   │  提取 token  │ complete         │
│  └──────────────────────────┘  + QQ       │ qq = event.user_id│
│                                            └────────┬─────────┘
│                                                     │
│  ◀───  轮询拿到 qq  ◀────────────────────────────────┘
│  bindUid(qq) 自动绑定
```

**关键变化**:
- 不再让用户输入自己的 UID/QQ, 而是由 bot 监听群消息时自动拿到 event.user_id (发送者 QQ)
- 校验码格式: 3位数字 + * + 2位数字 + 1位符号, 形如 `182*+` `203*70!` `456*12@`
- 6 位数字码旧机制 (`kards验证码` / `diy验证码` 命令) **已于 2026-06-29 废弃**, 旧文件残留的 `get_kards_bind_code` / `get_diy_bind_code` 命令已删除; 新流程只走校验指令, 指令前缀统一为 `校验kards账号`
- 全程 10 分钟 (BIND_CODE_TTL) 过期, 前端轮询 2 秒一次, 10 分钟超时后让用户重新获取

**前后端 API 衔接** (详见 4.3 节):
- 前端 `KardsAccount.preallocVerifyToken(purpose, token)` → `POST /api/verify_token` 预占
- 前端 `KardsAccount.pollVerifyToken(purpose, token)` → 轮询 `GET /api/verify_token?token=&purpose=`
- bot `on_message` 匹配 `^校验kards账号(.+)$` (统一前缀, UID/QQ 绑定都走这个) → `POST /api/verify_token/complete` 回写 qq
- 校验指令过期/被 GC 后, 前端再 GET 时拿到 `code:1 token 无效或已过期`

---

## 3. 未完成 / 计划中 ⏳

| # | 模块 | 状态 | 备注 / 待办 |
|---|---|---|---|
| 1 | 163 SMTP 邮箱验证码真实接入 | 占位 | `KardsAccount.sendCode` 当前是本地生成 6 位码 + 弹窗显示. 真实接入: 后端起 SMTP 端点, 前端替换实现. 计划: `POST /account/send_code {email}` → 后端用 `smtp.163.com:465 SSL + 授权码` 发邮件 → 仍写 localStorage `kards_pending_code` (10 分钟有效) |
| 2 | 我的投稿页面投稿 UI | 仅展示 | 缺"上传图片"按钮 → 调 `POST /diy/submit {uid, image_base64, anonymous}`. 需要: 文件选择 → base64 编码 → 大小校验 (1MB 上限) → 每天 3 张限频 |
| 3 | 高级管理面板 (管理员专属) | 基础完成 | `settings.html` 已有: API base / DIY API base / 改密. 待补: 用户列表 (调 `KardsAccount.listAll()`) / 封号 / 重置密码 / 全局开关 (如: 全站维护模式) |
| 4 | 卡组图下载样式定制 | 基础完成 | 已有下载按钮. 待优化: 导出 PNG 像素密度 (现在 1x, 想要 2x/3x 高清) / 自定义水印 / 文件名模板 |
| 5 | 公开招募页面 tabs 切换时自动刷新 | 已修过 1 次 | 仍有边界 case: 切到 `recruit.html` 时如果 `visibilitychange` 触发后页面已卸载, 可能重连卡顿. 待补: 完整 focus/visibility/pageshow 三件套 |
| 6 | 跨设备账号同步 | 未做 | 当前 localStorage 单设备, 换电脑要重新注册. 计划: 后端起 `/account/login` / `/account/register` 端点, 替换前端 `KardsAccount.login/register` 为 HTTP 调用, 账号存服务端 DB |
| 7 | 验证码防脚本刷 | 部分 | 前端按钮 60s 倒计时 + 后端 60s 节流. 待补: 同 IP 限频 / 验证码 HASH 不存明文 (现明文存 `data/bind_codes.json`) |
| 8 | 联调测试 | 待用户 | 群内实发 `kards验证码` / `diy验证码` 验证完整链路, 文档第 9.3 节有 checklist |
| 9 | HTTPS / 域名 | 未做 | 当前纯 HTTP, 公开部署需 nginx + Let's Encrypt |
| 10 | 国际化 | 未做 | 当前全中文, 无 i18n 框架 |

---

## 4. 后端 API 全景

### 4.1 `nonebot_kards_recruit_plugin.py` (公开招募, base = `http://<host>:8080`)

| 方法 | 路径 | 请求 | 响应 | 用途 |
|---|---|---|---|---|
| POST | `/kards/user_info` | `{uid}` | `{tags, refresh_times, refresh_limit, recruit_status, is_recruit_finished, african_progress, african_limit}` | 拉用户状态 |
| POST | `/kards/refresh_tags` | `{uid}` | `{tags, refresh_used, refresh_limit}` | 刷词条 (3/天) |
| POST | `/kards/start_recruit` | `{uid, choices: "ABC"}` | `{duration, finish_time, chosen_tags}` | 开始招募 |
| POST | `/kards/recruit_detail` | `{uid}` | `{status, start_time, finish_time, chosen_tags, result_card_id, result_card_name, ...}` | 查招募进度 |
| POST | `/kards/get_recruit_result` | `{uid}` | `{card_id, card_name, ...}` | 领取招募结果 |
| POST | `/kards/user_cards` | `{uid, rare?}` | `{cards: [{card_id, card_name, count, rare, image_base64, ...}]}` | 查卡牌收藏 |
| POST | `/kards/trade_list` | `{uid}` | `{trades: [...]}` | 赠送列表 |
| POST | `/kards/handle_trade` | `{uid, trade_id, action}` | `{...}` | 接受/拒绝赠送 |
| POST | `/kards/give_trade` | `{uid, to_uid, offer_card_id}` | `{...}` | 发起赠送 |
| POST | `/kards/change_name` | `{uid, new_name}` | `{...}` | 改名 |
| **群指令** | `kards验证码` | (无参) | 群内回码 `[CQ:at] kards 验证码: 482931` + POST 到前端 | 生成验证码 |
| **群指令** | `公开招募` / `刷新词条` / `个人面板` 等 | — | 群内回复 | 公开招募相关查询 |
| **SUPERUSER** | `发放公招券` / `增加刷新次数` | — | 群内回复 | 管理员指令 |

**后端表** (SQLite `gacha.db`):
- `Users(qq, qq_name, tickets, last_ticket_time, tags_json, refresh_times)`
- `UserCards(user_id, card_id, count)`
- `RecruitStatus(id, user_id, start_ts, finish_ts, status, ticket_tags, result_card_id)`
- `TradeStatus(id, time, from_uid, to_uid, offer_card_id, status, answer)`
- **`BindCodes(code, qq, group_id, created_ts, purpose)` ← 新增, 限频用**

### 4.2 `xunfang.py` (限定寻访 / DIY, base = `http://<host>:8090`)

| 方法 | 路径 | 请求 | 响应 | 用途 |
|---|---|---|---|---|
| GET | `/diy/random` | — | `{card_id, author, image_base64, likes, dislikes, candies, ...}` | 随机抽 DIY 卡 |
| GET | `/diy/random_special` | — | 同上 | 随机抽联动卡 |
| POST | `/diy/react` | `{uid, card_id, action: like/dislike/candy}` | `{msg: "评价成功 +1👍"}` | 评价 |
| POST | `/diy/submit` | `{uid, image_base64, anonymous?}` | `{card_id}` | 投稿 |
| GET | `/diy/card/{card_id}` | — | 完整卡牌详情 | 查单张 |
| POST | `/diy/user_cards` | `{uid}` | `{cards: [...], total, total_likes, ...}` | 查用户全部 |
| GET | `/diy/review` | (浏览器用) | HTML 审核页 | 管理员审核 |
| POST | `/diy/review_action` | 表单 | 重定向 | 审核操作 |
| GET | `/diy/candy` | (浏览器用) | HTML 糖果区 | 浏览糖果区 |
| GET | `/diy/image/{filename}` | — | 文件 | 静态图片 |
| **群指令** | `diy验证码` | (无参) | 群内回码 + POST 到前端 | 生成验证码 |
| **群指令** | `限定寻访` / `联动寻访` / `投稿限定卡牌` | — | 群内回复 | 抽卡 / 投稿 |
| **SUPERUSER** | `卡池状态` / `限定卡牌评分` | — | 群内回复 | 管理员指令 |

**后端表** (SQLite `diy.db`):
- `cards(id, qq, qq_name, anonymous, filename, submitted_at, approved_state, likes, dislikes, candies)`
- `reaction_log(id, user_qq, card_id, reaction, date)`
- `user_limits(id, user_qq, date, likes, dislikes, candies)`
- **`bind_codes(code, qq, group_id, created_ts, purpose)` ← 新增, 限频用**

### 4.3 `serve.py` 前端接收端点 (base = `http://<frontend>:8000`)

| 方法 | 路径 | 请求 | 响应 | 用途 |
|---|---|---|---|---|
| POST | `/api/bind_code` | `{qq, code, purpose, ts}` | `{code: 0, msg: "ok"}` | **旧: 接收 bot 推送的 6 位码 (兼容保留)** |
| GET | `/api/bind_code?qq=&purpose=` | — | `{code: 0, data: {qq, code, purpose, ts}}` | **旧: 前端轮询拉码 (兼容保留)** |
| POST | `/api/bind_code/verify` | `{qq, code, purpose}` | `{code: 0, msg: "ok"}` | **旧: 手动填码路径校验 (兼容保留)** |
| **POST** | **`/api/email_code`** | `{email, code, purpose}` | `{code: 0, data: {sent: true}}` 或 `{code: 0, data: {devCode: "..."}}` | **新: 邮箱验证码, SMTP 启用时真发, 否则 dev 模式回 devCode** |
| **POST** | **`/api/verify_token`** | `{purpose, token?}` | `{code: 0, data: {token: "..."}}` | **新: 前端预占校验码 (带 token) 或让后端生成** |
| **GET** | **`/api/verify_token?token=&purpose=`** | — | `{code: 0, data: {qq, ts}}` 或 `{code: 1, msg: "等待 bot 回调"}` | **新: 前端轮询, 拿 bot 写入的 qq** |
| **POST** | **`/api/verify_token/complete`** | `{token, purpose, qq}` | `{code: 0, msg: "ok"}` | **新: bot 监听群消息后调, 回写 qq** |
| GET | `/<file>.{html,js,png,css}` | — | 静态文件 | 5 个页面托管 |

**purpose 白名单**:
- 旧: `kards_uid_bind` / `diy_qq_bind`
- 新: `kards_token_bind` / `diy_token_bind`

**存储**:
- `data/bind_codes.json` (旧, 按 `qq|purpose`, 1 小时 GC)
- `data/verify_tokens.json` (新, 按 `token|purpose`, 10 分钟 GC)

**SMTP 配置**: `youxiang/youxiang.txt` (JSON)
- `enabled=false` (默认, dev 模式, 验证码弹窗显示)
- `enabled=true` + 填真实 host/port/user/password/from 后, 走真实 SMTP
- 占位符字面量 `滚木` 表示未配置, serve.py 启动时识别为未启用

**CORS**: `Access-Control-Allow-Origin: *` (允许多端跨域)

---

## 5. 前端页面索引

| 页面 | 路径 | 关键依赖 | 鉴权 |
|---|---|---|---|
| 登录/注册/绑定 | `account.html` | `account.js` | 公开 |
| 公开招募 | `recruit.html` | — | 必须已登录 + 绑公开招募 UID |
| 卡组解析 | `deck.html` | — | 公开 |
| 限定寻访 | `diy.html` | — | 必须已登录 + 绑 diyQQ |
| 管理/设置 | `settings.html` | — | 仅管理员 |

**统一布局** (5 个页面共用):
- 顶栏: 卡组 / 公开招募 / 限定寻访 / 账号 / 设置
- 左侧菜单: 当前页对应的入口 (高亮)
- 主区: 页面主体

---

## 6. 部署与本地运行

### 6.1 启动前端
```powershell
cd C:\开发
python serve.py --host 0.0.0.0 --port 8000
# 浏览器: http://localhost:8000/account.html
```

### 6.2 启动 NoneBot 后端
- `nonebot_kards_recruit_plugin.py` 与 `xunfang.py` 放入 NoneBot `plugins/` 目录
- **必须设置环境变量** (告诉 bot 前端在哪):
  ```bash
  set KARDS_FRONTEND_URL=http://<前端IP>:8000
  # 跨机时必须; 同机可省, 默认 http://127.0.0.1:8000
  ```
- 重启 NoneBot

### 6.3 跨机部署要点
1. 前端机器: `python serve.py --host 0.0.0.0 --port 8000` (必须 `0.0.0.0` 让 bot POST)
2. 防火墙放行 8000 端口入站
3. bot 机器: `KARDS_FRONTEND_URL=http://<前端IP>:8000`

---

## 7. 截图

### 7.1 登录/注册/绑定 (`account.html`)
![登录](docs/screenshots/01_account.png)

### 7.2 公开招募 (`recruit.html`)
未登录状态自动弹"需先登录账号"门控; 登录后展示 5 个词条 / 刷新次数 / 许可数 / 开始招募按钮。

![公开招募](docs/screenshots/02_recruit.png)

### 7.3 卡组解析 (`deck.html`)
输入 `%%15|2Z3N4zgUiajKoKoTxrzb;3f3X4sgVv7vhwBzd;bPggq8;bK` 等卡组码 → 调后端 → 右侧渲染。

![卡组](docs/screenshots/03_deck.png)

### 7.4 设置 / 管理 (`settings.html`)
管理员可见: API base 设置、DIY API base 设置、改密、用户列表入口。

![设置](docs/screenshots/04_settings.png)

### 7.5 限定寻访 / DIY (`diy.html`)
双 tab + 副切换, 调独立后端 `http://192.168.10.100:8090`。

![DIY](docs/screenshots/05_diy.png)

### 7.6 参考设计图 (来自 `~/Downloads/`)

**卡组解析页原型** (无标题434, 3 MB, 早期设计, 现在 `deck.html` 已基本按此实现):

![卡组解析原型](C:/Users/lijia/Downloads/无标题434_20260628023056.png)

**DIY 投稿界面原型** (2.3 MB, 手机端竖版, 后期要按这个设计投稿 UI):

![DIY 投稿原型](C:/Users/lijia/Downloads/投稿界面.png)

**DIY 卡牌详情原型** (628 KB, 横版, 含作者/时间/国家/稀有度/类型/指挥点/费用/设置, 我们的 `diy.html` 右列字段按此排):

![DIY 卡牌详情原型](C:/Users/lijia/Downloads/Screenshot_2026_0628_042958.png)

---

## 8. 文件清单

```
C:\开发\
├── account.html         账号页 (登录/注册/绑定)
├── account.js           账号模块 (KardsAccount 命名空间, localStorage 持久化)
├── recruit.html         公开招募页
├── deck.html            卡组解析页
├── diy.html             限定寻访页
├── settings.html        设置/管理页
├── serve.py             前端 HTTP 服务器 (静态 + /api/bind_code 接收)
├── jjc.png              招募许可图标
├── API文档.md            后端 API 完整说明
├── PROGRESS.md          ← 本文件
├── data/                (运行时) bind_codes.json 验证码缓存
└── docs/screenshots/    当前截图
```

后端 (不在本工作区, 由用户单独部署):
- `nonebot_kards_recruit_plugin.py` (公开招募插件)
- `xunfang.py` (限定寻访插件)

---

## 9. 测试覆盖

### 9.1 端到端 (已通过)
- 9 项 `/api/bind_code` 行为测试: 空 GET / POST 推送 / 跨 purpose 隔离 / 跨 qq 隔离 / 错 purpose 400 / 错 body 拒绝 / diy 链路 / 乱序 ts 保护
- 3 项 account.js 单元 (node 模拟 localStorage): mixed-case 邮箱注册 / 空 localStorage 管理员登录自愈 / 常规注册不回归
- 3 项 py 静态解析: `serve.py` / `nonebot_kards_recruit_plugin.py` / `xunfang.py` 全部 `ast.parse` 通过
- 1 项 JS 静态解析: `account.js` `node --check` 通过

### 9.2 浏览器实测 (待用户)
- 登录 → 绑定 → 群内发 `kards验证码` → 验证码自动填充 → 验证并绑定
- 管理员登录 → settings.html 改 API base → recruit.html 拉数据生效
- diy 页面切到 `我的投稿` → 列表渲染

### 9.3 后端实测 (需重启 bot)
- 群内发 `kards验证码` → 群内回码 (60s 节流生效, 10 条/日上限生效)
- 群内发 `diy验证码` → 群内回码
- 码经前端 `/api/bind_code` 端点接收成功, `data/bind_codes.json` 落盘

---

## 10. 已知限制

1. **localStorage 单一设备**: 账号数据存浏览器, 换浏览器/换电脑需重新注册 (或等"账号系统整合"落地)
2. **邮箱验证码非真实**: 占位实现, 真实接入 163 SMTP 后 `KardsAccount.sendCode` 改一行即可
3. **跨域**: 前端默认监听 `127.0.0.1`, 多端访问需 `--host 0.0.0.0`
4. **无 HTTPS**: 本地 HTTP, 公开部署需套 nginx + TLS
5. **数据无服务端持久化**: 验证码只存 `data/bind_codes.json`, 进程重启不丢 (文件持久化), 但 serve.py 重启期间收到的 POST 会失败 (best-effort)

---

## 11. 一句话流程图

```
┌──────────────────────────────────────────────────────────────────────┐
│                              用户旅程                                 │
└──────────────────────────────────────────────────────────────────────┘

 首次访问 account.html
        │
        ├── 注册: 邮箱 + 密码 + 验证码 (现占位, console 弹窗) ─┐
        │                                                     │
        └── 登录: 邮箱 + 密码                                  │
                  │                                          ▼
                  │                              登录成功 → 跳绑定 tab
                  │                                          │
                  ▼                                          ▼
            登录成功 ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  绑定公开招募 UID
            │                                          │
            │         填 UID → 获取验证码 → 群内发    │
            │         `kards验证码` → 前端轮询        │
            │         拉到码 → 自动填 → 验证并绑定      │
            │                                          ▼
            │                              绑 diyQQ (同上, 群指令 diy验证码)
            │                                          │
            ▼                                          ▼
   ┌─────────────────┐                       ┌──────────────────┐
   │ 公开招募 recruit │                       │ 限定寻访 diy     │
   │ 勾词条 → 刷新    │                       │ 全部DIY/联动寻访 │
   │ → 开始招募 → 领  │                       │ 评价 / 再来一张  │
   └─────────────────┘                       └──────────────────┘
            │                                          │
            └──────────┐                  ┌────────────┘
                       ▼                  ▼
                  ┌──────────────────────────────┐
                  │ 卡组 deck (公开, 无需登录)    │
                  │ 输入码 → 后端 draw_deck      │
                  │ → 右侧渲染 + 下载            │
                  └──────────────────────────────┘

管理员 (`isAdmin=true`) 多一项:
   settings.html → API base / DIY API base / 改密 / (待补) 用户列表
```

---

## 12. 优化记录 (2026-06-28)

本轮为**纯优化**, 不引入新功能. 涉及文件: `serve.py` / `xunfang.py` / `nonebot_kards_recruit_plugin.py` / `account.js` / 5 个 HTML.

### 安全
- `deck.html`: 删除 `?demo=admin` 自动登录脚本 (任意 URL 即拿 admin)
- `settings.html`: 删账号加密码二次校验 (confirm → prompt + sha256 比对当前账号 pwdHash)
- `diy.html`: 所有 `innerHTML` 拼接统一过 `escapeHtml`, 修复 `loadMine` / `nextCard` 两处 `resp.msg` 漏 escape
- `recruit.html`: 删 `#loginOverlay` 死代码 + `tryLogin` 旧 UID 登录 + `doLogout` + `oldOverlay` 引用 + `uidInput.focus` 残留, 避免绕过门控

### 健壮性
- `xunfang.py`: `submit_cmd.got('image')` 早退分支 `return` 改 `await finish(...)`, 修复 bot 卡死
- `xunfang.py` / `nonebot_kards_recruit_plugin.py`: CORS 中间件注册加 `getattr(app, '_cors_added', False)` 幂等保护
- `account.js`: `changePassword` 加 `PASSWORD_MIN_LEN = 6` 长度校验
- `account.js`: `verifyCode` 里 `10 * 60 * 1000` 抽成 `EMAIL_CODE_TTL_MS` 常量复用

### 性能
- `serve.py`: bind code 改为启动时一次性加载到 `BIND_CACHE` 内存; 写时双写内存 + 文件; 后台 `_gc_loop` 线程每 60s 周期 GC; 读时直接命中内存 (省掉每请求 JSON 序列化)
- `serve.py`: 非 `/api/bind_code` 的 POST 直接返回 405, 不再穿透到静态处理器
- `nonebot_kards_recruit_plugin.py`: `image_to_base64` 加 128 条 LRU 缓存 (key = path+mtime+size), 大幅减少 `/kards/user_cards` 等列表接口的重复读盘 + base64 编码
- `nonebot_kards_recruit_plugin.py`: `image_to_base64` 加 5MB 大小护栏 (`IMAGE_BASE64_MAX_BYTES`), 超大图直接返回 None
- `nonebot_kards_recruit_plugin.py`: `init_user_db` 启动时执行 `PRAGMA journal_mode = WAL` + `PRAGMA synchronous = NORMAL`, 提升并发读性能 (标志持久化, 后续连接自动生效)
- `diy.html`: `nextCard` 加 `AbortController` 取消上一次未完成请求, 解决"再来一张"连点的竞态
- `diy.html`: `loadMine` 改 in-flight 闭包 + `_loadMineInflight` 锁, tab 切回并发触发复用同一 Promise
- `recruit.html`: `loadUserInfo` 同款 in-flight 锁, `refreshOnVisible` 三事件并发触发不发重复请求
- `account.js`: `ensureSeed` 加内存级 `_seeded` 标志位短路, 后续所有调用直接 return, 省掉 `loadAccounts + sha256 + saveAccounts`

### 杂项
- 5 个 HTML 全部加 `<link rel="icon" href="data:,">`, 消除 `/favicon.ico` 404 噪声
- `account.js`: `sha256` 加纯 JS fallback (`_sha256Pure`). 当浏览器不在安全上下文 (非 https / 非 localhost) 时, `crypto.subtle` 是 undefined, 直接调会抛 `Cannot read properties of undefined (reading 'digest')`; 改为优先用 Web Crypto, 不可用时退回 80 行纯 JS 实现, 与 node `crypto.createHash('sha256')` 6/6 用例 (含中文密码) 输出完全一致, 不会导致已注册账号登不上
- `xunfang.py`: 补上 `import time` (diy验证码 handler 第 1052 行用到 `time.time()` 但顶部漏 import, 群内发码会直接抛 `NameError: name 'time' is not defined`)
- `nonebot_kards_recruit_plugin.py`: 删掉顶部两行死 import (`from email.policy import default` / `from sqlite3 import Row`), 全文搜索确认零引用
- `serve.py` + `account.js` + `account.html`: 修复手动填码卡死 bug. 原流程要求前端必须轮询到码才能点验证, 但 bot 端 KARDS_FRONTEND_URL 配错 (默认 127.0.0.1:8000, bot 容器回环) 时, 前端永远拿不到码, 用户手抄群消息填的码也会被 `verifyKardsCode/verifyDiyCode` 判无效. 改为: `serve.py` 新增 `POST /api/bind_code/verify` 端点 (在 BIND_CACHE 里查 + 原子删除防重放), `account.js` 新增 `verifyBindCodeRemote()`, `account.html` 两个验证按钮改为先本地校验, 失败时回退远程校验. 8/8 e2e 测试通过 (含重放保护 + 错码拒绝 + 405 行为)
- `xunfang.py` + `nonebot_kards_recruit_plugin.py`: 加启动日志 + 推送日志. 启动时打印 `[xunfang][INFO/WARN] KARDS_FRONTEND_URL=... -> push to ...` (env 缺失时打 WARN, 提示前端可能收不到); 每次推 `POST /api/bind_code` 前后各打一行 (`->` 推什么, `<-` HTTP 状态码, 失败打 ERR + 异常). 方便排查 bot 端推送是否真的到了 serve.py
- `serve.py`: 收到 `POST /api/bind_code` 时也打一行 `[bind_code] received from <IP> key=... code=... purpose=...`, 并把最近一次原始 payload 写到 `data/last_bind_code.json`. 这样用户/前端/后端三方日志可对照: 看到 bot 端 `[push] ->` 之后 serve 端 `[bind_code] received` 就能确认链路通
- `xunfang.py` + `nonebot_kards_recruit_plugin.py`: 补上 `import sys`. 之前两文件顶部 import 漏了 `sys` (xunfang 还漏 `time`), 启动 bot 加载插件时直接抛 `NameError: name 'sys/time' is not defined` 导致插件加载失败. 现在补上, 启动日志/推送日志能正常打到 stderr
- `xunfang.py` + `nonebot_kards_recruit_plugin.py`: 启动时 KARDS_FRONTEND_URL 缺失时输出 `[diag]` 块, 扫描 6 个常见 `.env` 路径 (cwd / 插件同目录 / ../ / ../..) 并报告哪些存在哪些不在, 同时尝试 `from dotenv import load_dotenv` 自动加载验证. 帮助用户定位 `KARDS_FRONTEND_URL` 没生效的具体原因 (NoneBot 默认不读 .env, 必须用 ENV GROUPS / 系统 env / 显式 dotenv 启动)
- `xunfang.py`: `image_to_base64` 改为返回 data URL (含 `data:<mime>;base64,` 前缀) 而不是裸 base64. 修限定寻访抽牌时左侧图片无法加载: 之前返回裸 base64 字符串, 前端 `<img src>` 设了但浏览器不识别, 修后 5/5 测试 (.png/.jpg/.unknown/.pngx/不存在) 全部正确, 包括后端存的 png 走 `data:image/png;base64,`
- `diy.html`: 修限定寻访抽牌页面被大图撑长. 原来 `.review-grid` 用 `min-height: 540px` + `grid-template-columns: 38% 62%`, `.card-stage` 只设 `min-height: 480px` 没有显式 width/height, 当原图很大 (>480px 或大宽高比) 时整页被拉长. 改为: `.review-grid` 固定 `grid-template-columns: 360px 1fr` + `height: 620px` + `overflow: hidden`; `.card-stage` 固定 `width: 332px; height: 564px` (扣 padding) + `flex-shrink: 0`; 图片仍 `object-fit: contain` 缩放. 加 `@media (max-width: 900px)` 媒体查询, 小屏时 review-grid 改单列, card-stage 自适应 420px 高
- `diy.html`: tab 文案 "我要投稿" 改为 "鉴赏桌" (含 1 处 tab div + 1 处 CSS 注释 + 1 处 HTML 注释). 这是抽取页 (抽牌 + 评价) 的标签, 与 "我的投稿" 区分. 该 tab 内部功能 (随机抽牌 / sub-tab 全部 DIY / 联动寻访 / 评价按钮) 不动
- `diy.html`: sub-tab "全部 DIY" 改为 "限定寻访" (与页面主标题/侧栏命名一致)
- `diy.html`: 切到 review tab (鉴赏桌) 时, 若还没显示卡, 自动调用 nextCard() 抽一张 (优化首屏体验, 不用每次手动点再来一张)
- `diy.html`: 卡牌视觉优化. `.card-stage` 加 `perspective: 800px` + `cursor: pointer`; img 加 `transition: transform 0.25s ease, box-shadow 0.25s ease` + `transform-origin: center center`; hover 时 `scale(1.04)` + 抬升阴影. mousemove 时根据鼠标在卡牌上的相对位置 (-0.5~0.5) 计算 `rotateX/Y`, 最大 ±12 度, 离开时复位. 让卡牌有"实体卡能看"的 3D 透视感
- `diy.html`: 卡牌视觉加大. hover scale 1.04 → 1.10, mousemove 中 scale 1.06 → 1.10, maxAngle 12 → 20 度. `.card-stage` 从 332×564 矩形 → 480×480 正方形, review-grid 左列从 360px → 520px. 媒体查询里小屏自适应 max-width 480px
- `diy.html`: 卡牌 hover 放大时不再被裁剪. `.card-stage` 移除 `overflow: hidden` 让 hover 放大/旋转能溢出显示, 溢出由外层 `.review-grid` 的 `overflow: hidden` 兜底 (不会撑开页面). 倾斜角度 maxAngle 20 → 30. hover box-shadow 0 12px 30px → 0 18px 40px, 浮起感更强
- `xunfang.py` + `nonebot_kards_recruit_plugin.py`: `os.environ.get('KARDS_FRONTEND_URL', ...)` 的默认值从 `http://127.0.0.1:8000` 改为 `http://192.168.10.121:8000` (用户的实际前端地址). 用户未在 .env 加载 KARDS_FRONTEND_URL 时直接生效; env 仍优先, 后续要切 IP 只需 export
- 删除 `deck.html` 默认预填的测试卡组码

### 验证
- 3 个 Python 文件 `ast.parse` 全部通过
- `account.js` `node --check` 通过; `diy.html` / `recruit.html` / `settings.html` 内嵌 JS 段 `node --check` 通过
- 实跑 smoke: `serve.py` 起服务, POST/GET `/api/bind_code` 正常, 5 个非 API POST 全部 405, 5 个 GET 全部 200, 关键字检查全部命中

### 跳过的提案
- `recruit.html` 倒计时暂停: 查证后**没有** `setInterval` 倒计时, `updateDuration` 是静态计算时长, 原提案不成立, 撤销
- API 路由改共享 SQLite 连接: SQLite 连接非线程安全, async 共享会卡死, 撤销
- `diy.html` 评价用后端去重: 依赖后端契约, 不动
### 新功能 (2026-06-28, 步出 “仅优化”模式)
- `xunfang.py`: 新增 `GET /diy/card/{card_id}` 端点. 查单张卡的完整详情（含 image_base64 / likes / dislikes / candies / state / author / submitted_at / **owner_qq**）. 软删卡 (approved_state=-1) 不可访问。这是“左键点击我的投稿 → 切到鉴赏桌展示”的后端依据
- `xunfang.py`: 新增 `POST /diy/delete` 端点. 软删 (仅将 approved_state 设为 -1，保留 reaction_log 让已有评价仍可追溯). 三重校验: uid 与 card_id 必填 / card_id 只接受 int / 仅本人卡牌可删（按 cards.qq == uid 校验，不一致返 403）. 重复删返“已是已删除状态”（幂等）
- `diy.html`: “我的投稿”页面 .my-card 加左键 + 右键事件.
  - 左键 → 调 `openMyCard(cardId)` → `showTab("review")` + `GET /diy/card/{id}` + `renderCard(data)`. 如果之前还有未完成的请求会被 AbortController 取消（与 nextCard 同款赛实保护）
  - 右键 → `confirmDeleteMyCard(cardId)` → `confirm("是否删除该卡牌? 该操作不可撤销")` → 确认后调 `doDeleteMyCard` → `POST /diy/delete {uid, card_id}`. 删成功后 `loadMine()` 刷新列表 + 若当前鉴赏桌正展示该卡则清空展示. contextmenu 默认 e.preventDefault() 拦住浏览器默认菜单
  - 额外加 `card.title = "左键查看 / 右键删除"` 提示文案；为 my-card 加 cursor:pointer + hover 边框变色 + 上移 2px + 阴影，让可点互动更明显
- `diy.html`: 鉴赏桌右侧 actions 区加 `删除该卡` 按钮 (#btnDeleteThis, 默认 display:none, btn-danger 红色警告风). renderCard 接收后端返回的 owner_qq 与 KardsAccount.getDiyQQ() 比对，一致才显示. 点击同样走 doDeleteMyCard (confirm → /diy/delete → loadMine + 清展示)
- `diy.html` CSS: 新增 .btn-danger (红色边框 + 暒色背景) + .my-card:hover (边框变色 + translateY(-2px) + box-shadow). 不影响原有 review-grid 布局

#### 验证
- 后端 mock (Python http.server 模拟 /diy/card/{id} 与 /diy/delete) 18/18 全过: 左键查自己卡 200+owner_qq 一致+data URL 前缀 / 删自己卡 0+ 成功 / 删别人卡 403+ 无权 / 删不存在 1+ 不存在 / 重复删 0+ 已是已删除 / 缺 uid/card_id 参数错 1 / card_id='abc' 格式错 1 / 查未审核卡 0+approved_state==0
- 前端 diy.html 静态扫 20/20 全过: HTML/CSS/JS 关键点全部到位（事件绑定、函数定义、端点调用、删后刷新）
- diy.html 内嵌 <script> 块 node --check 语法检查通过

#### 需同步到服务器
- 仅 diy.html 为前端，本机生效. xunfang.py / nonebot_kards_recruit_plugin.py 的 `/diy/card/{id}` 与 `/diy/delete` 二个新端点已在上一轮同步到服务器，重启 bot 后即可使用（该轮仅动了 diy.html）

### 缓存与刷新 (2026-06-28)
- `diy.html`: "我的投稿"列表加 30 分钟内存缓存. 原逻辑: 每次切 tab 进 mine 都重请 /diy/user_cards 拼上 N 张图的 base64, 占带宽宝贵. 改为: 内存级 `_mineCache` (Map<uid, {ts, html, hasData}>) + `MINE_CACHE_TTL_MS = 30 * 60 * 1000`. 切 tab 复用 HTML 快照, 事件重新绑 (`_bindMineCardsEvents` 用 `dataset.bound=1` 防重复)
- `diy.html`: tabs 区右侧加 `↻ 刷新` 按钮 (`#btnRefreshMine`, 默认 display:none, 仅"我的投稿"tab 可见). 点击 → `refreshMine()` → `_invalidateMineCache(uid)` + `loadMine(true)` 强制重拉. 按钮点击期间 disabled (防连点)
- `diy.html`: 三种主动失效缓存的场景: 1) 刷新按钮 2) 右键删卡成功后 (保证列表马上反映被删的卡) 3) 未绑定 QQ 时调 loadMine (clear 全部, 防账号混淆)
- `diy.html`: 列表底部加一行小记录: 最近加载时间 ("刚刚 / N 分钟前 / N 小时前") + 提示"30 分钟内不重请, 可点右上角"刷新""
- `diy.html` CSS: `.tabs` 加 `align-items: center`; 新增 `.tab-spacer { flex: 1 }` 占位 + `.tab-refresh` 金色边框透明背景按钮 (与 .tabs 底部边框对齐用 margin-bottom:-1px)

#### 验证
- 缓存逻辑 17/17 全过 (Python 复制逻辑跑 8 场景): 首载走网络 / 切 tab 命中缓存 / 刷新强制重拉 / 多 uid 隔离 / TTL 过期重拉 / 删卡后失效 / force 参数 / 退出登录清空
- diy.html 静态扫 22/22 全过: HTML 元素 / CSS / JS 函数 / 事件绑定 / showTab 显隐 / 删卡后失效 / 防重绑 / 时间格式
- diy.html 内嵌 <script> node --check 语法通过
- 本机起 serve.py 抓 diy.html, 10/10 关键字符串命中

#### 需同步到服务器
- 仅 diy.html 为前端, 本机生效. 后端未变, bot 无需重启

### 投稿流 (2026-06-28)
- `diy.html`: “我的投稿”列表末尾加一个“+”号占位卡. `_renderMineCards` 在 grid 末尾 appendChild 一个 `.my-card.my-card-add` (2px 虚线边框 + 大加号 + “投稿”标签), 点击 → `enterSubmitMode()`. 缓子中的事件重绑 (与 addCard 区分: dataset.add==1 时只绑 click 进入投稿, 不绑查看/删除)
- `diy.html`: 鉴赏桌加提交模式. `enterSubmitMode()` → 身体加 `body.submit-mode` 类, CSS 隐藏 react-row/btnNext/btnDeleteThis, 显示 `#submitActions` (包含 匿名复选/取消/投稿 三个控件). 退出时 `_exitSubmitMode()` 移除类 + 如果 currentCard 空 → 抽一张
- `diy.html`: 左侧空位 + 拖入. 提交模式下, `#cardStage` 内容变为 drop-hint (“+” + “拖入卡牌图片或点击选择”); cardStage 绑 dragover/drop/dragleave 事件, dragover 时加 `.drag-over` 高亮 (金色边框 + 透明背景). drop 上来后 → `_fileToDataUrl` 读为 data URL → `_renderSubmitPreview` 预览
- `diy.html`: 点空位 / 预览图 → 也可点击重选 (隐藏 filePicker 被 click 触发). 限制 5MB (与后端 MAX_IMAGE_SIZE 一致), 超过提前报错不发请求. 选中后开启“投稿”按钮
- `diy.html` CSS: 新增 .my-card-add (虚线边框 + aspect-ratio 2/3 + 大加号), .card-stage.drag-over (拖拽高亮), body.submit-mode 下隐藏/显示控件, .btn-submit / .btn-cancel (与原 btn-danger / btn-primary 一致风格), .anon-row (复选框 accent-color 与主题同色)
- `diy.html`: 提交 → `POST /diy/submit {uid, image_base64, anonymous}`. 不带 data: 前缀 (后端 base64.b64decode 需纯 base64), `_stripDataUrlPrefix` 拆出. 成功 → showToast + `_exitSubmitMode` + `_invalidateMineCache(uid)` + `loadMine(true)` 刷新列表. 失败/网络错误 → 提示 + 重启“投稿”按钮
- 修 `btnNext` 被多置 4 空格的丝缺 (replaced 上一轮)

#### 验证
- 后竫 mock 11/11 全过: 正常投稿 0 / 匿名投稿 DB anonymous=1 / 无 uid 401 / 无图 1 / 图过大 1 / 达今日 3 张上限 1 / 非图片 base64 1
- diy.html 静态扫 39/41 (两个虚阶: HTML 里没有 my-card-add 字面量, 仅 JS 动态创建; JS 里“btnDoSubmit”最近发生在 HTML 上, 与函数调用 _exitSubmitMode 距离超过 500 字符 — 仅是正则区间设计问题, 代码本身正确)
- diy.html 内嵌 <script> node --check 语法检查通过
- 本机起 serve.py 抓 diy.html, 24/24 关键字符串命中

#### 需同步到服务器
- 仅 diy.html 为前端, 本机生效. 后端 /diy/submit 已有, bot 无需重启

### 跳过的提案
### 投稿模式 UI 裁剪 (2026-06-28)
- `diy.html`: 投稿模式下隐藏鉴赏桌右栏上部的元信息 (sub-tabs 限定/联动寻访 + info-title + info-list 里的 ID/作者/发布时间). 上一轮只隐藏 react-row/btnNext/btnDeleteThis, 但右侧 sub-tabs/info-title/info-list 还在, 与投稿场景不吻合. 现在上半部空白, 右栏只剩 “匿名复选 / 取消 / 投稿” 三个控件
- `diy.html` CSS: `body.submit-mode` 加三条隐藏规则 (.sub-tabs / .info-title / .info-list). 加一条 `.info-pane { justify-content: flex-end; padding-bottom: 8px }` 让 submitActions 紧贴右栏底部. 由于 submitActions 已有 margin-top:auto, 与 flex-end 双重底部对齐, 可靠

#### 验证
- diy.html 静态扫 5/5: 4 条 submit-mode 隐藏规则 + 1 条 info-pane 调整
- 本机起 serve.py 抓 diy.html 4/4 关键 CSS 字符串命中
- 模拟 DOM 状态: 投稿模式下右栏只显示 “匿名/取消/投稿” 三个控件, 其余全隐藏

#### 需同步到服务器
- 仅 diy.html 为前端, 本机生效. 后端未变, bot 无需重启

### 跳过的提案
### 修 panel 命令报错 (2026-06-28)
- `nonebot_kards_recruit_plugin.py`: 移除 @panel.handle 里的死代码1 行. 原代码 `info = await bot.get_group_member_info(user_id=event.user_id)` 缺少必需参数 `group_id`, OneBot v11 适配器在 Pydantic 校验阶段抛 `ActionFailed: retcode=1400 must have required property 'group_id'`, 导致用户输入“个人面板”时 bot 整个 matcher 跳出 stacktrace. 实际上 `info` 赋值后从未被使用 (后续仅走 `await ensure_user_row(uid, await get_user_name(bot, uid))`, 后者已改为从 DB 读取, 不再调外部 API), 是遗留的老代码
- 根因修复: 删除 3 行死代码, 顶部留上“使用 DB 中的昵称 (若未设置则为 uid); get_user_name 已改为从 DB 读, 不再调外部 API”备注. 不影响任何业务逻辑

#### 验证
- `ast.parse` 语法检查通过
- 全文搜索 `get_group_member_info` 零引用 (panel 是唯一调用点)

#### 需同步到服务器
- 本轮修了 bot 端代码, 需要把 `nonebot_kards_recruit_plugin.py` 同步到服务器并重启 bot, 不然修复不生效

### 跳过的提案
### 搜索页 (2026-06-28)
- 新增 `search.html`: 全页就一个公告卡片 (站大半屏, 720×自适应高度). 内容: “本网站不制作搜索功能, 请使用 1939.giaory.xyz 网站提供的网址功能” + “点击整段文字任意位置跳轮”提示. 不制作任何实际搜索功能, 仅为跳轮入口
- “整段任意位置跳轮”的实现: 全部 4 个文字片段 (领说 / 链接 / 领说 / 提示) 都裹在 **同一个** `<a class="notice-card" id="searchJump" href="https://1939.giaory.xyz" target="_blank" rel="noopener noreferrer">` 里. 为了防中间被某个子节点提前关闭 (block-level a 在一些旧浏览器上会被误解), 所有内容都是 `<span>`, 块内无嵌套 `</a>`. 验证: 188 字节全部裹在 a 中
- `search.html` CSS: 复用 diy.html 的侧栏 .side-nav / .slot 样式 (完全一致); .notice-card 居中 720×自适应宝石形 + 鲜明边框 + hover 变金 + 上移 + 阴影; .link 金色 + 下划线; .hint 小灰提示
- `search.html` a11y: `<a>` 本身可焦点 (键盘 Enter 触发跳轮), 加了 tabindex=0 + role=link 作为能力不够的浏览器的兑现
- `search.html` 安全: `target="_blank"` + `rel="noopener noreferrer"` (OneBot 社区常见漏洞, 不加 rel 会让 1939.giaory.xyz 反向 window.opener 控制打开者页面)
- `diy.html`: 侧栏上以何“菜单 5”占位 div (style=font-size:12px) 换为 `<a class="slot" href="search.html" title="搜索">搜 索</a>`. 与上面 4 个 slot (deck/recruit/diy/settings) 一致的 .slot 风格, hover 金色亦适用. 原 admin-only settings 依然隐藏

#### 验证
- search.html 内嵌 <script> node --check 语法检查通过
- search.html 静态扫 23/23: HTML 元素 / 文字例子 / 标题 / target / rel / 侧栏 / active 高亮 / CSS / JS
- 结构验证: notice-card 块 188 字节全部裹在 <a>, 4 个 span (领说/链接/领说/提示) 都在块内, 块内无 `</a>`, href = https://1939.giaory.xyz, 任何位置点击均跳转
- 本机起 serve.py 抓 search.html (200, 4040 bytes) + diy.html (200, 34669 bytes) 均成功; 11/11 关键字符串命中; diy.html 不再含“菜单 5”

#### 需同步到服务器
- 仅前端 search.html + diy.html, 本机生效. 后端未变, bot 无需重启

### 跳过的提案
### 侧栏菜单一致性 (2026-06-28)
- `recruit.html`: 修正侧栏 slot 顺序 + 占位与其他页一致. 原顺序: 卡组 / 限定寻访 / 公开招募 / 管理 / 菜单3, 与 diy.html (search.html 刚加进 diy) 不一致 → 交换限定寻访/公开招募 位置, 菜单3 改为 search.html 链接“搜 索”
- `deck.html`: 侧栏最后一个 `菜单 3` 占位 div 换为 `<a href="search.html">搜 索</a>` 链接. 与 diy/recruit 三页侧栏 slot 顺序完全一致
- 3 页侧栏现在统一为: `deck.html (卡组) → recruit.html (公开招募) → diy.html (限定寻访) → settings.html (管理, admin-only 隐藏) → search.html (搜索)`. 顺序/链接/文案 全部一致

#### 验证
- 本机起 serve.py 抓 deck/diy/recruit 三页 side-nav 块, 提取 slot (href, 文案) 两两比较, 3/3 完全一致 (5 个 slot)
- 4 个页面 (deck/diy/recruit/search) 都返回 200, 字节数正常

#### 需同步到服务器
- 仅前端 HTML, 本机生效. 后端未变, bot 无需重启

### 跳过的提案
### Gate 仅盖侧栏 (2026-06-28)
- `recruit.html` + `diy.html`: 未登录 / 未绑定时的门控 overlay 从全屏遮罩 (`position: fixed; inset: 0; z-index: 150`) 改为仅盖住右侧 main 区域 (`position: fixed; top: 48px; left: 110px; right: 0; bottom: 0; z-index: 100; background: rgba(0, 0, 0, 0.45)`). 这样 topbar (48px) 与 side-nav (110px) 都不被遮, 用户可以点侧栏跳到其他页面 (卡组 / 搜索 等), 不被强制推到 account.html
- `recruit.html` + `diy.html`: 两个 gate box (gateLogin / gateBind) 都加了 `继续浏览 (不登录)` / `继续浏览 (不绑定)` 链接. 点击后只隐藏当前 gate, 不跳转, 主体内容背后仍可见
- 两个 dismiss 链接都用 `data-dismiss` 属性指向要隐藏的 gate id, 顶部全局代码 `document.querySelectorAll("[data-dismiss]").forEach` 一次性绑定事件. 添加新 gate 只需加 `data-dismiss="xxx"` 即可, 不需重复写事件绑定

#### 验证
- recruit.html + diy.html 静态扫 各 14/14, 合计 28/28: CSS 不再 inset:0 + top/left/right/bottom 准确 / dismiss 链接存在 + data-dismiss 属性上对应 / 文案“继续浏览 (不登录)”“继续浏览 (不绑定)” 同时出现 / JS 事件处理代码会取 data-dismiss 并调 display = none
- 两页内嵌 <script> node --check 语法检查通过
- 本机起 serve.py 抓 recruit.html (200, 19467 bytes) + diy.html (200, 35300 bytes) 都含全部关键元素

#### 需同步到服务器
- 仅前端 HTML + CSS, 本机生效. 后端未变, bot 无需重启

### 跳过的提案
### 跳过的提案

### 注册登录与绑定重构 (2026-06-29)
- **account.html** 重写: 4 个 tab — 登录 / 注册 / 绑定 / 邮箱
  - 登录: 账号输入框 (用户名 / 已绑定邮箱均可), 密码
  - 注册: 仅 用户名 + 密码 + 确认密码 (邮箱完全选填, 不再卡注册流程)
  - 绑定 (新流程): 不再让用户输入 UID / QQ, 改为"获取校验码" → 出现 `校验kards账号182*+` (或 `校验diy账号...`) + "点我复制指令" 按钮, 提示 "请在 600 秒内在群聊内发送 [指令]". 群内发送后 bot 监听, 回写 qq 到前端, 自动绑定
  - 邮箱 (新 tab): 选填绑定, 发送验证码 + 填码 + 解绑
- **account.js** 重写: 账号模型由 `email` 改为 `username` (唯一), `email` 降为可选
  - `register({username, pwd})` 校验 3-20 位字母/数字/下划线, 6+ 位密码
  - `login({id, pwd})` 同时支持 username / email
  - 新增 `bindEmail` / `unbindEmail`
  - `sendCode(email, purpose)` 调后端 `POST /api/email_code`, dev 模式返回 devCode, SMTP 启用后真发邮件
  - 新增 `generateVerifyToken()` (3位*2位1位符号) + `preallocVerifyToken` / `pollVerifyToken`
  - 移除旧的 `pollBindCode` / `verifyKardsCode` / `verifyDiyCode` (已替换为 verify_token 流程)
- **serve.py** 重写: 新增 4 个端点
  - `POST /api/email_code`: 读 `youxiang/youxiang.txt`, `enabled=true` 时走真实 SMTP (smtplib), 否则回 devCode
  - `POST /api/verify_token`: 前端预占 token (或后端生成), 存 `data/verify_tokens.json`
  - `GET  /api/verify_token?token=&purpose=`: 前端轮询, 拿 qq
  - `POST /api/verify_token/complete`: bot 监听群消息后调, 标记 token 已绑定
  - 旧的 `/api/bind_code` 系列保留, 兼容旧版 bot
- **nonebot_kards_recruit_plugin.py** + **xunfang.py**: 末尾追加 `on_message(priority=200)` 监听
  - 匹配 `^校验kards账号(.+)$` / `^校验diy账号(.+)$`, 提取 token + 当前 event.user_id (即 QQ)
  - 调 `serve.py /api/verify_token/complete` 标记完成, 前端轮询拿到 qq 即自动绑定
- **youxiang/youxiang.txt**: 新建 SMTP 配置模板 (JSON), `enabled=false`, 所有占位值均为字面量 "滚木" (per 需求)
- 端到端测试通过: 预占 token → 轮询"等待回调" → bot complete → 轮询拿到 qq → 邮箱 dev 模式回 devCode

### 指令统一 + 静默 (2026-06-29)
- **废弃**: 移除 `nonebot_kards_recruit_plugin.py` 中 `kards验证码` 命令 (含 `get_kards_bind_code` 函数体) 与 `xunfang.py` 中 `diy验证码` 命令
- **统一前缀**: 不论绑公开招募 UID 还是限定寻访 QQ, 群内统一发送 `校验kards账号{token}` (例: `校验kards账号182*+` `校验kards账号456*12@`)
- **后端区分**: 同一个指令前缀在两个 bot 中都匹配, 但 xunfang 监听到后调 `/verify_token/complete` 时 `purpose=diy_token_bind`, kards 监听到后 `purpose=kards_token_bind`. 靠 `purpose` 区分
- **静默**: 两个 bot 的 verify listener 全部移除 `verify_cmd.finish()` 调用. 校验码错误 / 不匹配 / 后端报错 / 成功 4 种情况, bot 都不在群里回复任何消息. 前端通过轮询 `/api/verify_token?token=&purpose=` 拿到 qq 后自动调用 `bindUid` / `bindDiyQQ` 完成绑定
- **HTML 同步**: `account.html` `_formatCmd()` 把 `diy_token_bind` 也返回 `校验kards账号{token}`; 初始提示文案明确"与公开招募统一前缀 校验kards账号"
- **端到端验证**: kards/diy 两条 token 路径都能完成 `prealloc → bot complete → poll 拿 qq`; 错误 token complete 收到 `code:1 token 无效或已过期` (前端轮询不会拿到 qq, 显示"校验超时, 请重新获取")


### 绑定页面统一入口 (2026-06-29)
- 校验码统一后, 绑定页面的"获取校验码"按钮也合并为一个
- 旧结构: 两个独立区块 (公开招募 UID / 限定寻访 QQ), 各一个按钮, 各自一份指令/复制框/提示
- 新结构: 单一下拉框 <select id="bindPurpose"> (选项 kards_token_bind / diy_token_bind) + 单按钮 #btnGetBindCode
- 旧 id 全部废弃并清除: btnGetBindCodeKards / btnGetBindCodeDiy / verifyKardsCmd / verifyDiyCmd / btnCopyKards / btnCopyDiy / verifyBoxKards / verifyBoxDiy / getCodeKardsHint / getCodeDiyHint / _setKardsCooldown / bindDiyErr / bindDiyOk
- 新 id: bindPurpose / btnGetBindCode / verifyBox / verifyCmd / btnCopy / getCodeHint
- 智能默认: 进入绑定面板时 _autoSelectBindPurpose() 根据当前账号未绑项自动选默认值 (uid 未绑选 kards_token_bind, 否则 diy_token_bind); 绑定成功后自动切到下一个未绑用途
- 切换用途时清空旧指令显示, 避免上一个 token 残留造成混淆
- 端到端验证: UID 绑定 (kards_token_bind) 与 QQ 绑定 (diy_token_bind) 两条路径都能完成 prealloc → bot complete → 前端轮询拿 qq, verify_tokens.json 落盘正确


### 绑定一次按钮同时绑两项 (2026-06-29)
- 用户最终流程: 进入绑定页 → 默认勾选两项 (公开招募 UID + 限定寻访 QQ) → 点一次"获取校验码" → 看到两条指令卡片 → 在群内分别发送 → 两个绑定自动完成
- UI: 复选框 (chkKards / chkDiy) 取代下拉框, 默认全勾; verifyList 容器动态渲染多张 verify-card, 每张含独立 input + 点我复制指令 + status 行
- JS 流程: _doGetVerify → 读 _readCheckedPurposes() → 每个 purpose 独立 generateVerifyToken → 独立 _renderVerifyCard → 独立 pollVerifyToken → onFound 时根据 BIND_PURPOSE_META[purpose].bindFn 自动调用 KardsAccount.bindUid 或 bindDiyQQ
- 切换勾选时清空 verifyList, 避免旧 token 残留
- 失败/超时/不匹配: bot 静默 (上一轮已实现), 前端 onTimeout 把卡片 status 标红, 用户点"获取校验码"重新生成
- 旧符号全部清除: _autoSelectBindPurpose / _wireCopy / verifyCmd / btnCopy / bindPurpose / _setKardsCooldown / btnGetBindCodeKards 等
- 端到端验证: 一次按钮生成两个 token, 两个 token 独立 prealloc → bot complete → 前端 poll 都拿到 qq, verify_tokens.json 双条目同时落盘


### 修复 admin 登录提示账号不存在 (2026-06-30)
- **问题**: 用户浏览器里 localStorage 还残留旧结构 (2026-06-29 之前的), 账号以 `email` 字段作为唯一 key, 没有 `username` 字段 (例: `{email: "admin@kards.local", pwdHash: ...}`). 我把账号模型从 email-based 改为 username-based 后, login 找的是 `a.username === "admin"`, 老数据没这个字段 → 找不到 → 报 "账号不存在"
- **根本原因**: `ensureSeed` 检查 `!list.some(a => a.username === "admin")` 时, 老账号 `a.username === undefined` 也满足 "不等于 admin", 所以会**重复插入**新 admin 账号, 但 passwordHash 又是新的, 不影响 admin123 登录 -- 问题不在密码, 而在 login 查不到旧 admin 账号
- **修复**: account.js 新增 `_migrateAccounts(list)` 函数, ensureSeed 先迁移再判断:
  - 老账号 (无 username 字段) → 取 email 的 @ 之前作为 username, 真实 email 字段清空
  - 同时补全 `uid` / `diyQQ` 默认值
  - 迁移后再检查 `username === "admin"`, 已存在则不重复插入
- **验证** (Node 模拟 localStorage):
  - 场景 1: 旧 localStorage 残留 admin@kards.local + alice@example.com → 迁移后 username=admin / alice, 用 admin/admin123 登录成功
  - 场景 2: 空 localStorage → seed 插入 admin, 登录成功
  - 场景 3: 迁移后再 seed, 不会重复插入
- **副作用**: 迁移后老账号的 email 字段被清空, 不能再用旧邮箱登录, 必须用 username 登录. 这是有意的 (避免老数据里误把 email 当 username)


### 修复 xunfang 加载 NameError (2026-06-30)
- **症状**: NoneBot 启动时 `Failed to import "xunfang"`, traceback 指向 `xunfang.py:1211 NameError: name 's' is not defined`. kards 插件 `1920` 行也有同样问题 (但报错前 bot 还在 import xunfang, 所以只看到 xunfang 的报错)
- **根因**: 上一轮我用 "文件做中转" 的 Powershell 模式做 Python 替换时, 在 Powershell 变量里多写了一个孤立的 's' 字符, 跟其他内容一起被拼接到 .py 文件末尾. AST 能解析 (因为 's' 是合法 identifier), 但 Python 加载模块时会按语句顺序求值, 看到裸 `s` 就 NameError
- **修复**: 删除两个 bot 文件末尾孤立的 's' 字符
  - `nonebot_kards_recruit_plugin.py`: size 68957 -> 68957 (去掉末尾 's')
  - `xunfang.py`: size 46550 -> 46549 (去掉末尾 's')
- **验证**: AST 解析全过, 起 serve.py 跑 kards/diy 两条 token 路径 (prealloc -> bot complete -> 前端 poll) 完整通过
- **避免**: 后续用 here-string + 变量拼接做代码替换时, 一定要 echo / cat 确认下文件末尾, 不能假设 patch 干净


### 改用 NoneBot pydantic Config 配置 (2026-06-30)
- **背景**: 之前 KARDS_FRONTEND_URL 走 os.environ.get, NoneBot 启动时不读 .env, 用户用 .env 配置需要 dotenv 启动方式. 改用 NoneBot 4.x 标准的 pydantic Config (参考其他插件 nonebot_plugin_bottle 的写法)
- **改动**:
  - `xunfang.py` + `nonebot_kards_recruit_plugin.py` 各加一个 Config 类:
    - imports: `from nonebot import ..., get_plugin_config` + `from pydantic import BaseModel, ConfigDict`
    - `class Config(BaseModel): model_config = ConfigDict(extra="ignore"); kards_frontend_url: str = "http://192.168.10.121:8000"`
    - `config: Config = get_plugin_config(Config)`
  - FRONTEND_PUSH_URL 初始化改为: `_KARDS_FRONTEND_BASE = (os.environ.get("KARDS_FRONTEND_URL") or config.kards_frontend_url).rstrip("/")`. 优先 env (向后兼容), 退到 config.kards_frontend_url
  - 启动诊断简化: 不再扫描 .env / dotenv 路径, 只在 env + config 都为空时 WARN
- **用法** (NoneBot .env.prod 等):
  ```
  kards_frontend_url=http://192.168.10.121:8000
  ```
- **优势**:
  - NoneBot 原生识别 (无需 dotenv 启动)
  - pydantic 类型校验, IP/URL 错时启动直接报错
  - 配置项集中, 后续加更多配置 (SMTP 之类) 直接扩 Config 类
- **验证**: AST 解析两个 bot 都 OK, serve.py 端到端测试 kards_token_bind 流程 (prealloc -> complete -> poll) 通过, 文件末尾无孤立字符残留


### 一个 token 同时绑 UID + QQ (2026-06-30)
- **用户需求**: 同一个 token, 在群内发一次 校验kards账号XXX, 一次性绑完 UID 和 QQ 两个账号 (而不是不同 token 各自绑)
- **改动**:
  - `serve.py` `_handle_verify_token_complete`: 不传 purpose 时, 对所有 VERIFY_PURPOSE_VALID 里的 purpose 遍历, 如果该 key 已预占且未过期, 就标完成. 返回 data.completed = ["kards_token_bind", "diy_token_bind"] (实际标了哪些). 传 purpose 时仍只标那一个, 向后兼容
  - `xunfang.py` + `nonebot_kards_recruit_plugin.py`: 调 complete 时不再传 purpose 字段, 让 serve.py 自动两个都标
  - `account.html` `_doGetVerify`: 只生成一个 token, 为勾选的每个 purpose 都 `preallocVerifyToken` 同一个 token, 然后只渲染一张 `_renderUnifiedCard` (提示 "绑定: 公开招募 UID + 限定寻访 QQ"). 每个 purpose 仍独立轮询, 但共享同一 token. 任意一个 purpose 完成都触发 `bindUid` / `bindDiyQQ` 对应的方法
  - 旧版 `pollVerifyToken` 仍然按 purpose 查不同的 key, 所以前端两个轮询都独立运行, 各自完成时各自绑
- **端到端验证**:
  - 同一 token `600*50%` 在 kards + diy 各 prealloc
  - complete 不传 purpose → 返回 `completed: ["diy_token_bind", "kards_token_bind"]`
  - 两个 purpose 轮询都拿到同一个 qq `99999`
  - 落盘 verify_tokens.json: 两个 key (token|kards_token_bind 和 token|diy_token_bind) qq 都被写入
  - 兼容场景: complete 带 purpose 只标那一个 (向后兼容)
  - 异常: 未预占的 token complete 返回 code:1
- **用户视角**:
  1. 进入绑定页 (默认两项都勾)
  2. 点一次"获取校验码"
  3. 出现一张指令卡片: "在群内发送 (绑定: 公开招募 UID + 限定寻访 QQ) 校验kards账号600*50%"
  4. 复制, 在群内粘贴发送 (1 条)
  5. 几秒后 UID 和 QQ 同时绑好

### 跳过的提案
## 13. 联系 & 维护

- 工作区: `C:\开发`
- 前端端口: 8000 (默认) / 启动命令 `python serve.py --host 0.0.0.0`
- 后端端口: 8080 (kards) / 8090 (diy), 由 NoneBot 启动
- API 详细文档: `C:\开发\API文档.md` (16438 字节, 后端插件原始 API 说明)
- 本说明文档: `C:\开发\PROGRESS.md` (本文)
- 参考图库: `C:\Users\lijia\Downloads\*.png` (设计图)

任何修改请同步更新本文档; 新增 API 端点要在第 4 章补表格; 新增页面要在第 5 章加索引 + 第 7 章补截图。
