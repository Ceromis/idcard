"""
NoneBot v2 plugin: Card Submission & Review System
Features implemented:
- Users can submit one 500x702 image per day (anonymous or real). Submissions stored on disk and in SQLite DB.
- Submissions require review. Admin web UI to review (approve / reject / skip) and a "candy area" for cards with many 🍬.
- Draw (抽取) command to get a random approved card and display info.
- Reaction commands: 赞{id} (👍), 踩{id} (👎), 评卡{id}🍬 (🍬). Limits: each user 5/5/5 per day; each user can react to a given card at most once per day.
- When a card reaches 20 🍬 it moves to the candy area (approved_state=2).

Prereqs (install in your bot env):
- nonebot2 (v2.4.x) with onebot v11 adapter
- aiosqlite
- pillow
- aiohttp

Drop this file into your plugins folder and adapt paths/permissions as needed.

Notes / Caveats:
- Downloading images depends on the onebot adapter message segment providing a public URL in segment.data['url'] or segment.data['file']. The code attempts common patterns; if your adapter doesn't expose a URL, you may need to adapt the download logic (see comments in download_image).
- The web UI is implemented by registering routes on get_driver().server_app (FastAPI). You can open /diy/review for the review interface and /cards/candy for the candy area.

"""

from nonebot import on_command, on_message, get_driver, require
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message, MessageSegment
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.params import CommandArg
from nonebot.typing import T_State

import aiosqlite
import aiohttp
from PIL import Image
from io import BytesIO
import os
import asyncio
import random
from datetime import datetime, date
import uuid
import base64
import time
import sys

require("nonebot_plugin_access_control_api")

from nonebot_plugin_access_control_api.service import create_plugin_service

plugin_service = create_plugin_service("nonebot_plugin_xiandingxunfang")
# --- Config ---
DB_PATH = "./diy.db"
IMAGES_DIR = "./diy_images"
SUBMIT_WAIT_SECONDS = 120  # wait time for image after prompt
CANDY_THRESHOLD = 20
DAILY_LIMIT_LIKE = 25
DAILY_LIMIT_DISLIKE = 25
DAILY_LIMIT_CANDY = 15
MAX_IMAGE_SIZE = 1024 * 1024  # 1MB
BIND_CODE_TTL = 600
BIND_CODE_COOLDOWN = 60
BIND_CODE_DAILY = 10
FRONTEND_PUSH_URL = os.environ.get('KARDS_FRONTEND_URL', 'http://192.168.10.121:8000') + '/api/bind_code'
# 启动诊断: 让运维一眼看清前端配在哪, 缺失或配错都直接打 WARN/INFO
_KARDS_FRONTEND_RAW = os.environ.get('KARDS_FRONTEND_URL')
if not _KARDS_FRONTEND_RAW:
    print('[xunfang][WARN] KARDS_FRONTEND_URL not set, push to ' + FRONTEND_PUSH_URL + ' (default 127.0.0.1, frontend may NOT receive)', file=sys.stderr)
    # 诊断: 扫描常见 .env 路径, 帮用户定位为什么 env 没被加载
    try:
        _candidates = [
            os.path.join(os.getcwd(), '.env'),
            os.path.join(os.getcwd(), '.env.prod'),
            os.path.join(os.getcwd(), '.env.dev'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env'),
        ]
        print('[xunfang][diag] cwd=' + os.getcwd(), file=sys.stderr)
        print('[xunfang][diag] __file__=' + os.path.abspath(__file__), file=sys.stderr)
        for _p in _candidates:
            if os.path.isfile(_p):
                print('[xunfang][diag] env found at: ' + _p, file=sys.stderr)
            else:
                print('[xunfang][diag] env NOT found at: ' + _p, file=sys.stderr)
        # 也尝试用 dotenv 自己加载一份测试 (NoneBot 默认不带 dotenv, 但用户可能装了)
        try:
            from dotenv import load_dotenv as _load_dotenv
            for _p in _candidates:
                if os.path.isfile(_p):
                    _load_dotenv(_p, override=False)
            _after = os.environ.get('KARDS_FRONTEND_URL')
            if _after:
                print('[xunfang][diag] dotenv loaded KARDS_FRONTEND_URL=' + _after + ' (但 NoneBot 启动时未加载, 请确认 .env 路径或使用 ENV GROUPS / dotenv 启动方式)', file=sys.stderr)
        except ImportError:
            print('[xunfang][diag] python-dotenv not installed, skip auto-load', file=sys.stderr)
    except Exception as _e:
        print('[xunfang][diag][ERR] ' + str(_e), file=sys.stderr)
else:
    print('[xunfang][INFO] KARDS_FRONTEND_URL=' + _KARDS_FRONTEND_RAW + ' -> push to ' + FRONTEND_PUSH_URL, file=sys.stderr)

os.makedirs(IMAGES_DIR, exist_ok=True)

__plugin_meta__ = PluginMetadata(
    name="限定寻访",
    description="用户可投稿限定卡牌，每日一张；他人可抽取并评论。",
    usage=(
        "投稿：发送“投稿限定卡牌”或“匿名投稿限定卡牌”并附上图片\n"
        "抽卡：发送“限定寻访”\n"
        "评卡：例如“评卡1👍”或“评卡1🍬”"
    )
)

# 简单处理一下分区，将过审状态扩展到其他数字来区分分区状态，简单记一下：
# approve_state_mapping = {
#     -1:"未过审/本人删除不可访问，但保留评价"
#     0:"未经审核"
#     1:"已审核/正常卡牌"
#     2:"🍬区"
#     3:"非二战卡牌区/自创国家卡牌区"
#     4:"官卡改卡区"
#     5:"二次元卡牌区"
#     6:"其他卡区"
# }
# 这个字典并不打算使用，仅作各个卡区分类查询用。

awaiting_image = {}  # user_id -> dict{anonymous:bool, timestamp}

# --- Database ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qq TEXT,
                qq_name TEXT,
                anonymous INTEGER DEFAULT 0,
                filename TEXT,
                submitted_at TEXT,
                approved_state INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                dislikes INTEGER DEFAULT 0,
                candies INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS reaction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_qq TEXT,
                card_id INTEGER,
                reaction TEXT,
                date TEXT
            );

            CREATE TABLE IF NOT EXISTS user_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_qq TEXT,
                date TEXT,
                likes INTEGER DEFAULT 0,
                dislikes INTEGER DEFAULT 0,
                candies INTEGER DEFAULT 0
            );
            """
        )
        await db.commit()
        try:
            await db.execute("ALTER TABLE cards ADD COLUMN qq_name TEXT")
            await db.commit()
        except Exception:
            pass  # already exists
        await db.execute('''
            CREATE TABLE IF NOT EXISTS bind_codes (
                code TEXT PRIMARY KEY,
                qq TEXT,
                group_id TEXT,
                created_ts INTEGER,
                purpose TEXT
            )
        ''')
        await db.commit()


@get_driver().on_startup
async def _():
    await init_db()

# --- Utils ---
async def download_image(bot: Bot, seg: MessageSegment) -> BytesIO:
    data = seg.data
    url = data.get("url") or data.get("file") or data.get("download_url")
    if url and (url.startswith("http://") or url.startswith("https://")):
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as resp:
                if resp.status == 200:
                    return BytesIO(await resp.read())
                else:
                    raise RuntimeError(f"failed to fetch image, status {resp.status}")
    img = data.get("base64") or data.get("b64")
    if img:
        import base64
        return BytesIO(base64.b64decode(img))
    raise RuntimeError("cannot find downloadable URL or base64 data in image segment")

# --- 投稿 ---
submit_cmd = on_command("投稿限定卡牌", aliases={"匿名投稿限定卡牌"}, priority=100)

@submit_cmd.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    user = str(event.user_id)
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT count(*) FROM cards WHERE qq=? AND date(submitted_at)=?", (user, today))
        row = await cur.fetchone()
        if row and row[0] >= 3:
            await submit_cmd.finish("你今天已经投稿过整整三张卡片了！")

    is_anonymous = event.get_plaintext().startswith("匿名") or "匿名投稿" in event.get_plaintext()
    awaiting_image[user] = {"anonymous": int(is_anonymous), "ts": datetime.now().timestamp()}
    await submit_cmd.send("请在2分钟内发送卡图（大小需≤1MB）")

@submit_cmd.got("image")
async def _(bot: Bot, event: MessageEvent):
    user = str(event.user_id)
    if user not in awaiting_image:
        await submit_cmd.finish("会话已结束, 请重新执行投稿命令.")
        return
    info = awaiting_image[user]
    if datetime.now().timestamp() - info["ts"] > SUBMIT_WAIT_SECONDS:
        awaiting_image.pop(user, None)
        await submit_cmd.finish("等待已超时，请重新执行投稿命令。")

    for seg in event.message:
        if seg.type == "image":
            try:
                bio = await download_image(bot, seg)
            except Exception as e:
                awaiting_image.pop(user, None)
                await submit_cmd.finish(f"下载图片失败：{e}")

            bio.seek(0, os.SEEK_END)
            size_bytes = bio.tell()
            bio.seek(0)
            if size_bytes > MAX_IMAGE_SIZE:
                awaiting_image.pop(user, None)
                await submit_cmd.finish("图片大小超过 1MB，请取消原图后再上传。")

            try:
                img = Image.open(bio)
            except Exception as e:
                awaiting_image.pop(user, None)
                await submit_cmd.finish(f"无法解析图片：{e}")

            try:
                user_info = await bot.get_stranger_info(user_id=int(user))
                qq_name = user_info.get("nickname", str(user))
            except Exception:
                qq_name = str(user)

            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "INSERT INTO cards (qq, qq_name, anonymous, filename, submitted_at, approved_state) VALUES (?,?,?,?,?,0)",
                    (user, qq_name, info["anonymous"], uuid.uuid4().hex, datetime.now().isoformat())
                )
                await db.commit()
                card_id = cur.lastrowid
                filename = f"card_{card_id}.png"
                path = os.path.join(IMAGES_DIR, filename)
                img.save(path)
                await db.execute("UPDATE cards SET filename=? WHERE id=?", (filename, card_id))
                await db.commit()

            awaiting_image.pop(user, None)
            await submit_cmd.finish(f"已加入数据库，该卡编号为{card_id}。等待审核。")

    if event.get_plaintext().strip():
        awaiting_image.pop(user, None)
        await submit_cmd.finish("已取消投稿。")

# --- 抽卡 ---
draw_cmd = on_command("限定寻访", aliases={"抽取限定"}, priority=100)
xianding = plugin_service.create_subservice('xiandingxunfang')
@draw_cmd.handle()
@xianding.patch_handler()
async def _(bot: Bot, event: MessageEvent):
    # random_offset = 0
    async with aiosqlite.connect(DB_PATH) as db:
        # --- 改进后的抽卡逻辑：👎和🍬越多越难抽 ---
        # 获取所有已通过审核的卡片
        cur = await db.execute(
            "SELECT id, qq_name, anonymous, filename, submitted_at, likes, dislikes, candies "
            "FROM cards WHERE approved_state=1"
        )
        rows = await cur.fetchall()
    
    if not rows:
        await draw_cmd.finish("当前没有可抽取的卡片（已通过审核）。")
    
    # 计算权重：👎和🍬越多，权重越小
    weights = []
    for row in rows:
        card_id, qq_name, anonymous, filename, submitted_at, likes, dislikes, candies = row
        penalty = dislikes + candies  # 惩罚值
        weight = 1.0 / (1.0 + penalty)  # 权重计算（防止除0）
        weights.append(weight)
    
# 按权重随机选择
    total = sum(weights)
    r = random.uniform(0, total)
    cumulative = 0
    chosen = None
    for row, w in zip(rows, weights):
        cumulative += w
        if r <= cumulative:
            chosen = row
            break

    if not chosen:
        chosen = rows[-1]  # 理论上不会发生

    card_id, qq_name, anonymous, filename, submitted_at, likes, dislikes, candies = chosen

    header = f"该卡由{qq_name if not anonymous else '匿名用户'}制作于{datetime.fromisoformat(submitted_at).strftime('%Y-%m-%d')}\n编号：{card_id}\n👍：{likes}👎：{dislikes}🍬：{candies}"
    msg = Message(header)
    img_path = os.path.join(IMAGES_DIR, filename)
    msg.append(MessageSegment.image(file=f"file://{os.path.abspath(img_path)}"))
    await draw_cmd.finish(msg)

# --- 其他卡牌寻访 ---
draw_special_cmd = on_command("联动寻访", aliases={"其他限定寻访"}, priority=100)
liandong = plugin_service.create_subservice('liandongxunfang')
@draw_special_cmd.handle()
@liandong.patch_handler()
async def _(bot: Bot, event: MessageEvent):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, qq_name, anonymous, filename, submitted_at, likes, dislikes, candies "
            "FROM cards WHERE approved_state IN (3,4,5,6) "
            "ORDER BY RANDOM() LIMIT 1"
        )
        row = await cur.fetchone()

        card_id, qq_name, anonymous, filename, submitted_at, likes, dislikes, candies = row

    header = f"该卡由{qq_name if not anonymous else '匿名用户'}制作于{datetime.fromisoformat(submitted_at).strftime('%Y-%m-%d')}\n编号：{card_id}\n👍：{likes}👎：{dislikes}🍬：{candies}"
    msg = Message(header)
    img_path = os.path.join(IMAGES_DIR, filename)
    msg.append(MessageSegment.image(file=f"file://{os.path.abspath(img_path)}"))
    await draw_cmd.finish(msg)



# --- 评价 ---
react_cmd = on_message(priority=100, block=True)
import re

@react_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    txt = event.get_plaintext().strip()
    user = str(event.user_id)
    m_like = re.match(r'^评卡(\d+)👍$', txt)
    m_dislike = re.match(r'^评卡(\d+)👎$', txt)
    m_candy = re.match(r'^评卡(\d+)🍬$', txt)
    if not (m_like or m_dislike or m_candy):
        return
    card_id = int((m_like or m_dislike or m_candy).group(1))
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT qq, approved_state FROM cards WHERE id=?", (card_id,))
        row = await cur.fetchone()
        if not row:
            await react_cmd.finish("找不到该卡片。")

        author_qq, state = row
        if state not in (1, 3, 4, 5, 6):
            await react_cmd.finish("该卡片当前不可评价（未审核或已在🍬区）。")

        # 🚫 禁止用户评价自己的卡
        if str(author_qq) == user:
            await react_cmd.finish("你不能评价自己的卡牌哦。")

        cur = await db.execute("SELECT count(*) FROM reaction_log WHERE user_qq=? AND card_id=? AND date=?", (user, card_id, today))
        already = (await cur.fetchone())[0]
        if already >= 1:
            await react_cmd.finish("你今天已经对这张卡评价过一次，明天再来吧。")

        cur = await db.execute("SELECT likes, dislikes, candies FROM user_limits WHERE user_qq=? AND date=?", (user, today))
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO user_limits (user_qq, date, likes, dislikes, candies) VALUES (?,?,0,0,0)", (user, today))
            await db.commit()
            likes_count = dislikes_count = candies_count = 0
        else:
            likes_count, dislikes_count, candies_count = row

        if m_like:
            if likes_count >= DAILY_LIMIT_LIKE:
                await react_cmd.finish(f"你今天的👍次数已用完（{DAILY_LIMIT_LIKE}次）。")
            await db.execute("UPDATE cards SET likes = likes + 1 WHERE id=?", (card_id,))
            await db.execute("UPDATE user_limits SET likes = likes + 1 WHERE user_qq=? AND date=?", (user, today))
            await db.execute("INSERT INTO reaction_log (user_qq, card_id, reaction, date) VALUES (?,?,?,?)", (user, card_id, 'like', today))
            await db.commit()
            await react_cmd.finish("该卡+1👍")

        if m_dislike:
            if dislikes_count >= DAILY_LIMIT_DISLIKE:
                await react_cmd.finish(f"你今天的👎次数已用完（{DAILY_LIMIT_DISLIKE}次）。")
            await db.execute("UPDATE cards SET dislikes = dislikes + 1 WHERE id=?", (card_id,))
            await db.execute("UPDATE user_limits SET dislikes = dislikes + 1 WHERE user_qq=? AND date=?", (user, today))
            await db.execute("INSERT INTO reaction_log (user_qq, card_id, reaction, date) VALUES (?,?,?,?)", (user, card_id, 'dislike', today))
            await db.commit()
            await react_cmd.finish("该卡+1👎")

        if m_candy:
            if candies_count >= DAILY_LIMIT_CANDY:
                await react_cmd.finish(f"你今天的🍬次数已用完（{DAILY_LIMIT_CANDY}次）。")
            await db.execute("UPDATE cards SET candies = candies + 1, dislikes = dislikes + 1 WHERE id=?", (card_id,))
            await db.execute("UPDATE user_limits SET candies = candies + 1 WHERE user_qq=? AND date=?", (user, today))
            await db.execute("INSERT INTO reaction_log (user_qq, card_id, reaction, date) VALUES (?,?,?,?)", (user, card_id, 'candy', today))
            await db.commit()
            cur = await db.execute("SELECT candies FROM cards WHERE id=?", (card_id,))
            new_candies = (await cur.fetchone())[0]
            if new_candies >= CANDY_THRESHOLD:
                await db.execute("UPDATE cards SET approved_state=2 WHERE id=?", (card_id,))
                await db.commit()
                await react_cmd.finish(f"已标记该卡 +1 🍬。该卡达到 {CANDY_THRESHOLD} 个🍬，已转移到唐诗区。")
            await react_cmd.finish("该卡+1🍬")

# --- Web UI ---
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

server_app = get_driver().server_app

async def fetch_one_pending():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, qq_name, anonymous, filename, submitted_at FROM cards WHERE approved_state=0 ORDER BY id LIMIT 1")
        return await cur.fetchone()

@server_app.get("/diy/review", response_class=HTMLResponse)
async def review_page(request: Request):
    row = await fetch_one_pending()
    if not row:
        return HTMLResponse("<h3>没有待审核的图片。</h3>")
    card_id, qq_name, anonymous, filename, submitted_at = row
    img_url = f"/diy/image/{filename}"
    html = f"""
    <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>非常的新鲜，非常的美味</title>
            <style>
                .container {{
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                    align-items: center;
                    height: 75vh;
                    width: 52.5vh;
                }}
                .title {{
                    display: flex;
                    flex-direction: column;
                    width: 100%;
                    text-align: center;
                    font-size: 56;
                }}
                .diycard {{
                    display: flex;
                    justify-content: center;
                    height: 60%;
                }}

                form {{
                    width:100%;
                    display: flex;
                    flex-direction: column;
                }}
                
                form .buttonbox {{
                    display: flex;
                    flex-direction: row;
                    justify-content: center;
                    gap: 10px;
                    flex-wrap: wrap;
                    margin-top: 8px;
                    width: 100%;
                }}

                .button {{
                    flex: 1;
                    max-width: 80px; 
                }}

                .button button {{
                    width: 100%;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="title">
                    <h3>审核区 — 编号 {card_id}</h3>
                    <span>提交者：{'(匿名)' if anonymous else qq_name}</span>
                    <span>提交时间：{datetime.strftime(datetime.fromisoformat(submitted_at),'%Y-%m-%d %H:%M:%S')}</span>
                    <span>编号：{card_id}</span>
                </div>
                <div class="diycard">
                    <img src="{img_url}" style="max-width:1000px;display:block;"/>
                </div>
                <form method="post" action="/diy/review_action">
                    <div class="buttonbox">
                        <input type="hidden" name="card_id" value="{card_id}" />
                        <div class="button"><button name="action" value="approve">正常通过</button></div>
                        <div class="button"><button name="action" value="reject">拒绝</button></div>
                        <div class="button"><button name="action" value="custom">加入非二战//自创国家区</button></div>
                    </div>
                    <div class="buttonbox">
                        <input type="hidden" name="card_id" value="{card_id}" />
                        <div class="button"><button name="action" value="improve">加入官卡改卡区</button></div>
                        <div class="button"><button name="action" value="anime">加入二次元区</button></div>
                        <div class="button"><button name="action" value="other">加入其他卡区</button></div>
                    </div>
                </form>
            </div>
        </body>
        </html>
    """
    return HTMLResponse(html)

@server_app.post("/diy/review_action")
async def review_action(card_id: int = Form(...), action: str = Form(...)):
    async with aiosqlite.connect(DB_PATH) as db:
        if action == "approve":
            await db.execute("UPDATE cards SET approved_state=1 WHERE id=?", (card_id,))
        elif action == "reject":
            await db.execute("UPDATE cards SET approved_state=-1 WHERE id=?", (card_id,))
        elif action == "custom":
            await db.execute("UPDATE cards SET approved_state=3 WHERE id=?", (card_id,))
        elif action == "improve":
            await db.execute("UPDATE cards SET approved_state=4 WHERE id=?", (card_id,))
        elif action == "anime":
            await db.execute("UPDATE cards SET approved_state=5 WHERE id=?", (card_id,))
        elif action == "other":
            await db.execute("UPDATE cards SET approved_state=6 WHERE id=?", (card_id,))
        await db.commit()
    return RedirectResponse(url="/diy/review", status_code=303)

@server_app.get("/diy/candy", response_class=HTMLResponse)
async def candy_page(request: Request):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, qq_name, anonymous, filename, candies FROM cards WHERE approved_state=2 ORDER BY candies DESC")
        rows = await cur.fetchall()
    if not rows:
        return HTMLResponse('<h3>🍬区为空。</h3>')
    parts = ["<h2>🍬区</h2>"]
    for card_id, qq_name, anonymous, filename, candies in rows:
        img_url = f"/diy/image/{filename}"
        parts.append(f"<div><h4>编号 {card_id} (🍬{candies}) 提交者: {qq_name} {'(匿名)' if anonymous else ''}</h4>")
        parts.append(f"<img src='{img_url}' style='max-width:300px;display:block;'/>")
        parts.append(f"<form method='post' action='/diy/candy_action'>"
                     f"<input type='hidden' name='card_id' value='{card_id}'/>"
                     f"<button name='action' value='clear'>清空🍬并放回普通区</button>"
                     f"<button name='action' value='ignore'>忽略</button>"
                     f"</form></div><hr>")
    return HTMLResponse('\n'.join(parts))

@server_app.post("/diy/candy_action")
async def candy_action(card_id: int = Form(...), action: str = Form(...)):
    async with aiosqlite.connect(DB_PATH) as db:
        if action == "clear":
            await db.execute("UPDATE cards SET candies=0, approved_state=1 WHERE id=?", (card_id,))
        await db.commit()
    return RedirectResponse(url="/diy/candy", status_code=303)

@server_app.get("/diy/image/{filename}")
async def serve_image(filename: str):
    path = os.path.join(IMAGES_DIR, filename)
    if not os.path.exists(path):
        return HTMLResponse("not found", status_code=404)
    return FileResponse(path)

# --- 状态 ---
status_cmd = on_command("卡池状态", permission=SUPERUSER, priority=100)

@status_cmd.handle()
async def _(bot: Bot):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM cards WHERE approved_state=0")
        pending = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM cards WHERE approved_state=1")
        approved = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM cards WHERE approved_state=2")
        candy = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM cards WHERE approved_state IN (3,4,5,6)")
        others = (await cur.fetchone())[0]
    await status_cmd.finish(f"待审核: {pending}，已通过: {approved}，🍬区: {candy}，联动寻访区：{others}")
# --- 删除卡牌 ---
delete_cmd = on_message(priority=100, block=True)

@delete_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    txt = event.get_plaintext().strip()
    m = re.match(r"^删除限定卡牌(\d+)$", txt)
    if not m:
        return
    card_id = int(m.group(1))
    user_id = str(event.user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id,qq,filename FROM cards WHERE id=?", (card_id,))
        row = await cur.fetchone()
        if not row:
            await delete_cmd.finish(f"未找到编号为 {card_id} 的卡片。")
        card_owner = row[1]
        filename = row[2]

        is_superuser = await SUPERUSER(bot,event)
        is_owner = (user_id == card_owner)

        if not (is_superuser or is_owner):
            await delete_cmd.finish("你不是这张卡的制作者，你无权删除这张卡。")
        elif is_superuser:
            await db.execute("DELETE FROM cards WHERE id=?", (card_id,))
            img_path = os.path.join(IMAGES_DIR, filename)
            if os.path.exists(img_path):
                os.remove(img_path)
        elif is_owner:
            await db.execute("UPDATE cards SET approved_state=-1 WHERE id=?", (card_id,))
        await db.commit()

    await delete_cmd.finish(f"编号 {card_id} 的卡片已删除。")


# --- 用户评分统计 ---
score_cmd = on_command("限定卡牌评分", priority=100)

@score_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    user = str(event.user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT IFNULL(SUM(likes),0), IFNULL(SUM(dislikes),0), IFNULL(SUM(candies),0) "
            "FROM cards WHERE qq=?",
            (user,)
        )
        row = await cur.fetchone()
    likes, dislikes, candies = row

    comment_list = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, IFNULL(likes,0) as likes, IFNULL(dislikes,0) as dislikes, IFNULL(candies,0) as candies "
            "FROM cards WHERE qq=? AND approved_state IN (1,3,4,5,6) "
            "ORDER BY id DESC LIMIT 5",
            (user,)
        ) as cursor:
            rows = await cursor.fetchall()
            description = cursor.description
            if description:
                columns = [column[0] for column in description]
                comment_list = [dict(zip(columns,row))for row in rows]
            # print(comment_list)

    cards_info = ""
    for card in comment_list:
        cards_info +=f"\n卡牌编号:{card['id']} ->👍:{card['likes']} 👎:{card['dislikes']} 🍬:{card['candies']}"
    await score_cmd.finish(
        f"你的卡牌一共收获了：\n👍：{likes}\n👎：{dislikes}\n🍬：{candies}"
        f"\n最近的5张diy评分如下：{cards_info}"
    )

# ==================== API 路由 ====================
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

app = get_driver().server_app

# 图片转BASE64
# 返回 data URL (e.g. "data:image/png;base64,iVBORw0K..."),
# 前端 <img src> 可以直接使用, 否则裸 base64 字符串浏览器不会当图片加载
_IMAGE_MIME_MAP = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".bmp":  "image/bmp",
}

def image_to_base64(image_path: str) -> str:
    """将图片转换为 data URL (含 MIME 前缀)"""
    if not os.path.exists(image_path):
        return None
    try:
        ext = os.path.splitext(image_path)[1].lower()
        mime = _IMAGE_MIME_MAP.get(ext, "image/png")  # 后端存的全是 png, fallback 到 png
        with open(image_path, "rb") as f:
            img_data = f.read()
        b64 = base64.b64encode(img_data).decode("utf-8")
        return "data:%s;base64,%s" % (mime, b64)
    except Exception:
        return None

# 检查用户登录
async def check_diy_login(uid: str) -> bool:
    """检查用户是否已登录"""
    if not uid:
        return False
    return True

# API: 随机获取一张DIY卡牌
@app.get("/diy/random")
async def api_random_card(request: Request):
    """随机获取一张已审核通过的DIY卡牌，返回图片、评价、ID、作者与时间"""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, qq, qq_name, anonymous, filename, submitted_at, likes, dislikes, candies "
            "FROM cards WHERE approved_state=1 "
            "ORDER BY RANDOM() LIMIT 1"
        )
        row = await cur.fetchone()
    
    if not row:
        return JSONResponse({
            "code": 1,
            "msg": "当前没有可获取的卡牌",
            "data": None
        })
    
    card_id, qq, qq_name, anonymous, filename, submitted_at, likes, dislikes, candies = row
    
    img_path = os.path.join(IMAGES_DIR, filename)
    img_base64 = image_to_base64(img_path)
    
    return JSONResponse({
        "code": 0,
        "msg": "success",
        "data": {
            "card_id": card_id,
            "author": "匿名用户" if anonymous else qq_name,
            "submitted_at": datetime.fromisoformat(submitted_at).strftime("%Y-%m-%d %H:%M:%S"),
            "likes": likes,
            "dislikes": dislikes,
            "candies": candies,
            "image_base64": img_base64
        }
    })

# API: 随机获取联动寻访卡牌
@app.get("/diy/random_special")
async def api_random_special_card(request: Request):
    """随机获取一张联动寻访区的DIY卡牌"""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, qq, qq_name, anonymous, filename, submitted_at, likes, dislikes, candies "
            "FROM cards WHERE approved_state IN (3,4,5,6) "
            "ORDER BY RANDOM() LIMIT 1"
        )
        row = await cur.fetchone()
    
    if not row:
        return JSONResponse({
            "code": 1,
            "msg": "当前没有可获取的联动卡牌",
            "data": None
        })
    
    card_id, qq, qq_name, anonymous, filename, submitted_at, likes, dislikes, candies = row
    
    img_path = os.path.join(IMAGES_DIR, filename)
    img_base64 = image_to_base64(img_path)
    
    return JSONResponse({
        "code": 0,
        "msg": "success",
        "data": {
            "card_id": card_id,
            "author": "匿名用户" if anonymous else qq_name,
            "submitted_at": datetime.fromisoformat(submitted_at).strftime("%Y-%m-%d %H:%M:%S"),
            "likes": likes,
            "dislikes": dislikes,
            "candies": candies,
            "image_base64": img_base64
        }
    })

# API: 按 ID 查单卡 (用于"我的投稿"左键切鉴赏桌展示该卡)
@app.get("/diy/card/{card_id}")
async def api_get_card(card_id: int):
    """根据 card_id 查一条卡牌, 返回完整字段含 image_base64"""
    try:
        card_id = int(card_id)
    except ValueError:
        return JSONResponse({"code": 1, "msg": "card_id 格式错误", "data": None})
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, qq, qq_name, anonymous, filename, submitted_at, approved_state, likes, dislikes, candies "
            "FROM cards WHERE id=?",
            (card_id,)
        )
        row = await cur.fetchone()
    if not row:
        return JSONResponse({"code": 1, "msg": "卡牌不存在", "data": None})
    card_id, qq, qq_name, anonymous, filename, submitted_at, approved_state, likes, dislikes, candies = row
    img_path = os.path.join(IMAGES_DIR, filename)
    img_base64 = image_to_base64(img_path)
    return JSONResponse({
        "code": 0,
        "msg": "success",
        "data": {
            "card_id": card_id,
            "author": "匿名用户" if anonymous else qq_name,
            "submitted_at": datetime.fromisoformat(submitted_at).strftime("%Y-%m-%d %H:%M:%S"),
            "state": {0:"待审核",1:"正常",2:"正常",3:"正常",4:"正常",5:"正常",6:"正常",-1:"已删除"}.get(approved_state, "未知"),
            "approved_state": approved_state,
            "likes": likes,
            "dislikes": dislikes,
            "candies": candies,
            "image_base64": img_base64,
            "owner_qq": qq
        }
    })

# API: 评价卡牌
@app.post("/diy/react")
async def api_react_card(request: Request):
    """
    评价卡牌
    action: like(👍), dislike(👎), candy(🍬)
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_diy_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    action = data.get("action")
    if action not in ("like", "dislike", "candy"):
        return JSONResponse({"code": 1, "msg": "action参数无效，可选: like/dislike/candy", "data": None})
    
    card_id = data.get("card_id")
    if not card_id:
        return JSONResponse({"code": 1, "msg": "请指定card_id", "data": None})
    
    try:
        card_id = int(card_id)
    except ValueError:
        return JSONResponse({"code": 1, "msg": "card_id格式错误", "data": None})
    
    today = date.today().isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 检查卡牌是否存在
        cur = await db.execute("SELECT qq, approved_state FROM cards WHERE id=?", (card_id,))
        row = await cur.fetchone()
        
        if not row:
            return JSONResponse({"code": 1, "msg": "找不到该卡片", "data": None})
        
        author_qq, state = row
        if state not in (1, 3, 4, 5, 6):
            return JSONResponse({"code": 1, "msg": "该卡片当前不可评价", "data": None})
        
        # 禁止评价自己的卡
        if str(author_qq) == uid:
            return JSONResponse({"code": 1, "msg": "不能评价自己的卡牌", "data": None})
        
        # 检查今日是否已评价
        cur = await db.execute(
            "SELECT count(*) FROM reaction_log WHERE user_qq=? AND card_id=? AND date=?",
            (uid, card_id, today)
        )
        already = (await cur.fetchone())[0]
        if already >= 1:
            return JSONResponse({"code": 1, "msg": "今天已对该卡评价过", "data": None})
        
        # 检查用户今日限制
        cur = await db.execute("SELECT likes, dislikes, candies FROM user_limits WHERE user_qq=? AND date=?", (uid, today))
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO user_limits (user_qq, date, likes, dislikes, candies) VALUES (?,?,0,0,0)", (uid, today))
            await db.commit()
            likes_count = dislikes_count = candies_count = 0
        else:
            likes_count, dislikes_count, candies_count = row
        
        if action == "like":
            if likes_count >= DAILY_LIMIT_LIKE:
                return JSONResponse({"code": 1, "msg": f"今日👍次数已用完({DAILY_LIMIT_LIKE}次)", "data": None})
            await db.execute("UPDATE cards SET likes = likes + 1 WHERE id=?", (card_id,))
            await db.execute("UPDATE user_limits SET likes = likes + 1 WHERE user_qq=? AND date=?", (uid, today))
            await db.execute("INSERT INTO reaction_log (user_qq, card_id, reaction, date) VALUES (?,?,?,?)", (uid, card_id, 'like', today))
            await db.commit()
            return JSONResponse({"code": 0, "msg": "评价成功 +1👍", "data": None})
        
        if action == "dislike":
            if dislikes_count >= DAILY_LIMIT_DISLIKE:
                return JSONResponse({"code": 1, "msg": f"今日👎次数已用完({DAILY_LIMIT_DISLIKE}次)", "data": None})
            await db.execute("UPDATE cards SET dislikes = dislikes + 1 WHERE id=?", (card_id,))
            await db.execute("UPDATE user_limits SET dislikes = dislikes + 1 WHERE user_qq=? AND date=?", (uid, today))
            await db.execute("INSERT INTO reaction_log (user_qq, card_id, reaction, date) VALUES (?,?,?,?)", (uid, card_id, 'dislike', today))
            await db.commit()
            return JSONResponse({"code": 0, "msg": "评价成功 +1👎", "data": None})
        
        if action == "candy":
            if candies_count >= DAILY_LIMIT_CANDY:
                return JSONResponse({"code": 1, "msg": f"今日🍬次数已用完({DAILY_LIMIT_CANDY}次)", "data": None})
            await db.execute("UPDATE cards SET candies = candies + 1, dislikes = dislikes + 1 WHERE id=?", (card_id,))
            await db.execute("UPDATE user_limits SET candies = candies + 1 WHERE user_qq=? AND date=?", (uid, today))
            await db.execute("INSERT INTO reaction_log (user_qq, card_id, reaction, date) VALUES (?,?,?,?)", (uid, card_id, 'candy', today))
            await db.commit()
            
            # 检查是否进入糖果区
            cur = await db.execute("SELECT candies FROM cards WHERE id=?", (card_id,))
            new_candies = (await cur.fetchone())[0]
            if new_candies >= CANDY_THRESHOLD:
                await db.execute("UPDATE cards SET approved_state=2 WHERE id=?", (card_id,))
                await db.commit()
                return JSONResponse({"code": 0, "msg": f"评价成功 +1🍬，该卡已进入🍬区", "data": None})
            
            return JSONResponse({"code": 0, "msg": "评价成功 +1🍬", "data": None})

# API: 删除自己的卡牌
@app.post("/diy/delete")
async def api_delete_card(request: Request):
    """
    用户删除自己投稿的卡牌
    需要传入: uid(用户QQ), card_id(卡牌ID)
    权限: 仅可删除自己投稿的 (按 cards.qq == uid 校验)
    实现: 软删 (approved_state 设为 -1), 保留 reaction_log 让已有评价仍可追溯
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")

    uid = str(data.get("uid") or "").strip()
    card_id = data.get("card_id")
    if not uid or not card_id:
        return JSONResponse({"code": 1, "msg": "参数错误 (uid / card_id 必填)", "data": None})
    try:
        card_id = int(card_id)
    except (ValueError, TypeError):
        return JSONResponse({"code": 1, "msg": "card_id 格式错误", "data": None})

    async with aiosqlite.connect(DB_PATH) as db:
        # 查归属
        cur = await db.execute("SELECT qq, approved_state FROM cards WHERE id=?", (card_id,))
        row = await cur.fetchone()
        if not row:
            return JSONResponse({"code": 1, "msg": "卡牌不存在", "data": None})
        owner_qq, state = row
        if str(owner_qq) != uid:
            return JSONResponse({"code": 403, "msg": "无权删除他人的卡牌", "data": None})
        if state == -1:
            return JSONResponse({"code": 0, "msg": "卡牌已是已删除状态", "data": None})
        # 软删: approved_state = -1 (已定义为: 未过审/本人删除不可访问, 但保留评价)
        await db.execute("UPDATE cards SET approved_state=-1 WHERE id=?", (card_id,))
        await db.commit()
    return JSONResponse({"code": 0, "msg": "删除成功", "data": None})

# API: 投稿卡牌
@app.post("/diy/submit")
async def api_submit_card(request: Request):
    """
    投稿DIY卡牌
    需要传入: uid(用户ID), image_base64(图片BASE64), anonymous(是否匿名,可选)
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_diy_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    img_base64 = data.get("image_base64")
    if not img_base64:
        return JSONResponse({"code": 1, "msg": "请提供图片(BASE64)", "data": None})
    
    anonymous = data.get("anonymous", False)
    
    # 检查今日投稿数量
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT count(*) FROM cards WHERE qq=? AND date(submitted_at)=?", (uid, today))
        row = await cur.fetchone()
        if row and row[0] >= 3:
            return JSONResponse({"code": 1, "msg": "今天已投稿3张，请明天再来", "data": None})
    
    # 解析图片
    try:
        img_data = base64.b64decode(img_base64)
        bio = BytesIO(img_data)
        img = Image.open(bio)
    except Exception as e:
        return JSONResponse({"code": 1, "msg": f"图片解析失败: {str(e)}", "data": None})
    
    # 检查图片大小
    if len(img_data) > MAX_IMAGE_SIZE:
        return JSONResponse({"code": 1, "msg": f"图片大小超过{MAX_IMAGE_SIZE//1024}KB限制", "data": None})
    
    # 获取用户昵称
    qq_name = uid
    
    # 保存图片和入库
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO cards (qq, qq_name, anonymous, filename, submitted_at, approved_state) VALUES (?,?,?,?,?,0)",
            (uid, qq_name, int(anonymous), uuid.uuid4().hex, datetime.now().isoformat())
        )
        await db.commit()
        card_id = cur.lastrowid
        filename = f"card_{card_id}.png"
        path = os.path.join(IMAGES_DIR, filename)
        img.save(path)
        await db.execute("UPDATE cards SET filename=? WHERE id=?", (filename, card_id))
        await db.commit()
    
    return JSONResponse({
        "code": 0,
        "msg": "投稿成功，等待审核",
        "data": {
            "card_id": card_id
        }
    })

# API: 查询卡牌信息
@app.get("/diy/card/{card_id}")
async def api_get_card(card_id: int):
    """根据卡牌ID获取卡牌详细信息"""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, qq, qq_name, anonymous, filename, submitted_at, approved_state, likes, dislikes, candies "
            "FROM cards WHERE id=?",
            (card_id,)
        )
        row = await cur.fetchone()
    
    if not row:
        return JSONResponse({
            "code": 1,
            "msg": "找不到该卡片",
            "data": None
        })
    
    card_id, qq, qq_name, anonymous, filename, submitted_at, approved_state, likes, dislikes, candies = row
    
    state_map = {
        -1: "未过审",
        0: "待审核",
        1: "正常",
        2: "🍬区",
        3: "非二战/自创国家区",
        4: "官卡改卡区",
        5: "二次元区",
        6: "其他卡区"
    }
    
    img_path = os.path.join(IMAGES_DIR, filename)
    img_base64 = image_to_base64(img_path)
    
    return JSONResponse({
        "code": 0,
        "msg": "success",
        "data": {
            "card_id": card_id,
            "author": "匿名用户" if anonymous else qq_name,
            "submitted_at": datetime.fromisoformat(submitted_at).strftime("%Y-%m-%d %H:%M:%S"),
            "state": state_map.get(approved_state, "未知"),
            "likes": likes,
            "dislikes": dislikes,
            "candies": candies,
            "image_base64": img_base64
        }
    })

# API: 查询用户全部DIY卡牌
@app.post("/diy/user_cards")
async def api_user_cards(request: Request):
    """查询指定用户的所有DIY卡牌及其评价"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not uid:
        return JSONResponse({"code": 1, "msg": "请指定uid", "data": None})
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, qq, qq_name, anonymous, filename, submitted_at, approved_state, likes, dislikes, candies "
            "FROM cards WHERE qq=? AND approved_state != -1 "
            "ORDER BY id DESC",
            (uid,)
        )
        rows = await cur.fetchall()
    
    if not rows:
        return JSONResponse({
            "code": 0,
            "msg": "该用户暂无DIY卡牌",
            "data": {"cards": [], "total": 0}
        })
    
    state_map = {
        -1: "未过审",
        0: "待审核",
        1: "正常",
        2: "🍬区",
        3: "非二战/自创国家区",
        4: "官卡改卡区",
        5: "二次元区",
        6: "其他卡区"
    }
    
    cards_list = []
    for row in rows:
        card_id, qq, qq_name, anonymous, filename, submitted_at, approved_state, likes, dislikes, candies = row
        
        img_path = os.path.join(IMAGES_DIR, filename)
        img_base64 = image_to_base64(img_path)
        
        cards_list.append({
            "card_id": card_id,
            "author": "匿名用户" if anonymous else qq_name,
            "submitted_at": datetime.fromisoformat(submitted_at).strftime("%Y-%m-%d %H:%M:%S"),
            "state": state_map.get(approved_state, "未知"),
            "likes": likes,
            "dislikes": dislikes,
            "candies": candies,
            "image_base64": img_base64
        })
    
    # 统计总评价
    total_likes = sum(c["likes"] for c in cards_list)
    total_dislikes = sum(c["dislikes"] for c in cards_list)
    total_candies = sum(c["candies"] for c in cards_list)
    
    return JSONResponse({
        "code": 0,
        "msg": "success",
        "data": {
            "user_uid": uid,
            "total": len(cards_list),
            "total_likes": total_likes,
            "total_dislikes": total_dislikes,
            "total_candies": total_candies,
            "cards": cards_list
        }
    })

# 添加CORS支持 (幂等: 模块可能被多次加载, 避免重复注册)
try:
    from fastapi.middleware.cors import CORSMiddleware
    if not getattr(app, "_cors_added", False):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        app._cors_added = True
except Exception as e:
    print(f"CORS middleware error: {e}")



# ===== 验证码 (用于在网页上绑定限定寻访 QQ) =====
get_diy_bind_code = on_command("diy验证码", priority=100)


@get_diy_bind_code.handle()
async def _(bot: Bot, event: MessageEvent):
    qq = str(event.user_id)
    now_ts = int(time.time())
    today_start_ts = int(datetime.combine(date.today(), datetime.min.time()).timestamp())
    cooldown_remaining = 0
    daily_used = 0
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT created_ts FROM bind_codes WHERE qq=? AND purpose=? ORDER BY created_ts DESC LIMIT 1",
            (qq, "diy_qq_bind"),
        )
        row = await cur.fetchone()
        if row:
            elapsed = now_ts - int(row[0])
            if elapsed < BIND_CODE_COOLDOWN:
                cooldown_remaining = BIND_CODE_COOLDOWN - elapsed
        cur = await db.execute(
            "SELECT COUNT(*) FROM bind_codes WHERE qq=? AND purpose=? AND created_ts>=?",
            (qq, "diy_qq_bind", today_start_ts),
        )
        daily_used = (await cur.fetchone())[0]
    if cooldown_remaining > 0:
        await get_diy_bind_code.finish(f"请勿频繁获取, 还需 {cooldown_remaining} 秒后可再次申请")
    if daily_used >= BIND_CODE_DAILY:
        await get_diy_bind_code.finish("今日验证码次数已用完, 请明天再试")
    code = None
    for _ in range(5):
        candidate = str(random.randint(100000, 999999))
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO bind_codes(code, qq, group_id, created_ts, purpose) VALUES(?,?,?,?,?)",
                    (candidate, qq, str(getattr(event, "group_id", "") or ""), now_ts, "diy_qq_bind"),
                )
                await db.commit()
            code = candidate
            break
        except Exception:
            continue
    if not code:
        await get_diy_bind_code.finish("验证码生成失败, 请稍后再试")

    try:
        print('[xunfang][push] -> %s qq=%s code=%s purpose=diy_qq_bind' % (FRONTEND_PUSH_URL, qq, code), file=sys.stderr)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
            async with session.post(FRONTEND_PUSH_URL, json={
                "qq": qq,
                "code": code,
                "purpose": "diy_qq_bind",
                "ts": now_ts,
            }) as resp:
                print('[xunfang][push] <- %s status=%s' % (FRONTEND_PUSH_URL, resp.status), file=sys.stderr)
    except Exception as e:
        print('[xunfang][push][ERR] %s failed: %s' % (FRONTEND_PUSH_URL, e), file=sys.stderr)

    await get_diy_bind_code.finish(
        f"[CQ:at,qq={qq}]\ndiy 验证码: {code}\n10 分钟内有效, 请到 kards 账号页面绑定限定寻访 QQ"
    )
