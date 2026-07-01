import asyncio
import os
import aiosqlite
import random
import json
import time
import base64
import sys
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, date
from math import floor,ceil
from typing import List, Dict, Tuple, Any, Optional

from PIL import Image, ImageDraw, ImageFont
from nonebot import on_command, get_driver, on_message, require, get_plugin_config
from pydantic import BaseModel, ConfigDict
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment, Message
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot import get_app

# 路径
BASE = Path(__file__).parents[3]/ "Amiya-simple" / "resources" / "kards"
DB = BASE / "gacha.db"
CARDS_SQL = BASE / "Cards.sql"
IMAGE_DIR = BASE / "cards"
TAGS_JSON = BASE / "tags.json"


# 固定参数
DAILY_TICKET = 1
MAX_TICKET = 5
DAILY_TAGS = 5
REFRESH_LIMIT = 3
AFRICAN = 70
# 插件配置 (NoneBot 4.x pydantic 风格, 读 .env / env)
class Config(BaseModel):
    """nonebot_kards_recruit_plugin 配置项
    用法 (.env 或 env):
        kards_frontend_url=http://192.168.10.121:8000
    """
    model_config = ConfigDict(extra="ignore")

    kards_frontend_url: str = "http://192.168.10.121:8000"


config: Config = get_plugin_config(Config)


BIND_CODE_TTL = 600
BIND_CODE_COOLDOWN = 60
BIND_CODE_DAILY = 10
# 从 NoneBot 插件配置读取前端地址 (config.kards_frontend_url)
# 兼容老 env: 仍读 KARDS_FRONTEND_URL, 若 env 显式设置且 config 没设, 优先 env
_KARDS_FRONTEND_ENV = os.environ.get('KARDS_FRONTEND_URL')
_KARDS_FRONTEND_BASE = (_KARDS_FRONTEND_ENV or config.kards_frontend_url).rstrip("/")
FRONTEND_PUSH_URL = _KARDS_FRONTEND_BASE + '/api/bind_code'
if not _KARDS_FRONTEND_ENV and not config.kards_frontend_url:
    print('[kards][WARN] kards_frontend_url not set, push to ' + FRONTEND_PUSH_URL + ' (使用 Config 默认值, 改 NoneBot .env 中 kards_frontend_url 即可覆盖)', file=sys.stderr)
else:
    print('[kards][INFO] frontend url=' + _KARDS_FRONTEND_BASE + ' -> push to ' + FRONTEND_PUSH_URL, file=sys.stderr)
CARD_THUMB = (120, 168)
COLS = 10
ROWS = 18
CARDS_PER_PAGE = COLS * ROWS

# 字体
try:
    FONT = ImageFont.truetype("arial.ttf", 20)
except Exception:
    FONT = ImageFont.load_default()

# 品质权重
QUALITY_WEIGHTS = {
    "精英": 0.001,
    "特殊": 0.099,
    "限定": 0.40,
    "普通": 0.50,
}

# 招募时间（分钟）
T_DEFAULT = 30
T_EXPERT = 60
T_HIGH_EXPERT = 120

#数据库配置与设置
async def init_user_db():
    DB.parent.mkdir(parents = True, exist_ok = True)
    async with aiosqlite.connect(DB) as db:
        # 启用 WAL 模式 + 同步 NORMAL, 提升并发读性能 (WAL 标志会持久化到 DB 文件头, 后续连接自动生效)
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA synchronous = NORMAL")
        await db.execute('''
                            CREATE TABLE IF NOT EXISTS Cards(
                                PicID INTEGER PRIMARY KEY AUTOINCREMENT,
                                CardName TEXT,
                                Effect TEXT,
                                Country TEXT,
                                Rare TEXT,
                                Kind TEXT,
                                Cost INTEGER,
                                AttackCost INTEGER,
                                Attack INTEGER,
                                Defence INTEGER,
                                Pack TEXT,
                                Alias TEXT
                            )
                         ''')
        await db.execute('''
                            CREATE TABLE IF NOT EXISTS Users(
                                qq TEXT PRIMARY KEY,
                                qq_name TEXT,
                                tickets INTEGER,
                                last_ticket_time TEXT,
                                tags_json TEXT,
                                refresh_times INTEGER
                                )
                         ''')
        await db.execute('''
                            CREATE TABLE IF NOT EXISTS UserCards(
                                user_id TEXT,
                                card_id INTEGER,
                                count INTEGER,
                                PRIMARY KEY(user_id,card_id)
                                )
                         ''')
        await db.execute('''
                            CREATE TABLE IF NOT EXISTS RecruitStatus(
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id TEXT,
                                start_ts INTEGER,
                                finish_ts INTEGER,
                                status TEXT,
                                ticket_tags TEXT,
                                result_card_id INTEGER
                                )
                         ''')
        await db.execute('''
                            CREATE TABLE IF NOT EXISTS TradeStatus(
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                time TEXT,
                                from_uid TEXT,
                                to_uid TEXT,
                                offer_card_id INTEGER,
                                status INTEGER,
                                answer INTEGER
                                )
                         ''')
        await db.execute('''
                            CREATE TABLE IF NOT EXISTS BindCodes(
                                code TEXT PRIMARY KEY,
                                qq TEXT,
                                group_id TEXT,
                                created_ts INTEGER,
                                purpose TEXT
                                )
                         ''')
        await db.commit()
    # 导入Cards表的sql文件
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT COUNT(*) FROM Cards")
        cnt = (await cur.fetchone())[0]
    if cnt == 0 and CARDS_SQL.exists():
        with open(CARDS_SQL,'r',encoding = 'utf-8') as file:
            sql = file.read()
        async with aiosqlite.connect(DB) as db2:
            async with db2.cursor() as cur:
                statements = sql.split(';')
                for statement in statements:
                    if statement.strip():
                        await cur.execute(statement)
                await db2.commit()
        
# 标签配置与设置
def load_tags_config():
    if TAGS_JSON.exists():
        try:
            return json.loads(TAGS_JSON.read_text(encoding = 'utf-8'))
        except Exception as e:
            print (f"读取标签JSON失败：{e}")
            return {}
    #改进示例JSON
    return [
        {
            "tag_id":1,
            "weight":0.1,
            "name":"世纪大战",
            "associate":"Pack",
            "param":"世纪大战"
        },
        {
            "tag_id":2,
            "weight":0.1,
            "name":"美国",
            "associate":"Country",
            "param":"美国"
        },
        {
            "tag_id":3,
            "weight":0.1,
            "name":"苏联",
            "associate":"Country",
            "param":"苏联"
        },
        {
            "tag_id":4,
            "weight":0.08,
            "name":"高行动花费",
            "associate":"AttackCost",
            "param":">=3"
        },
        {
            "tag_id":5,
            "weight":0.05,
            "name":"低花费",
            "associate":"Cost",
            "param":"<=4"
        }
    ]

# 读取/返回已注册的用户名（改为从DB读取，避免使用已废弃的get_stranger_info）
async def get_user_name(bot :Bot, user):
    # user 可能是 str 或 int，统一当作 str 存/查
    uid = str(user)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT qq_name FROM Users WHERE qq = ?", (uid,))
        row = await cur.fetchone()
        if row and row[0]:
            return row[0]
    # 若未注册昵称，返回qq id 作为回退显示名（不再尝试调用外部API）
    return uid

# 用户配置与用户抽卡标签
async def ensure_user_row(qq:str,qq_name:str):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT qq FROM Users WHERE qq = ?",(qq,))
        if not await cur.fetchone():
            await db.execute("INSERT INTO Users(qq, qq_name, tickets, refresh_times, last_ticket_time) VALUES(?,?,?,?,?)"
                             ,(qq,qq_name,DAILY_TICKET,0,date.today().isoformat()))
            await db.commit()
        
#查看tag
async def get_tags(qq:str,qq_name:str):
    await ensure_user_row(qq,qq_name)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT tags_json,refresh_times,last_ticket_time FROM Users WHERE qq = ?",(qq,))
        row = await cur.fetchone()
        today = date.today().isoformat()
        if row[0]:# and row[0] is not None
            return json.loads(row[0]),row[1]
        return await generate_tags(qq,qq_name),0

#生成tag    
async def generate_tags(qq:str,qq_name:str):
    await ensure_user_row(qq,qq_name)
    tags = load_tags_config()
    weights = [item["weight"] for item in tags]
    today = date.today().isoformat()
    chosen_tags = []
    attempts = 0
    while len(chosen_tags) < DAILY_TAGS and attempts < 200:
        pick = random.choices(tags,weights = weights,k = 1)[0]
        if pick not in chosen_tags:
            chosen_tags.append(pick)
        attempts += 1
    if (await is_african(qq))[0]:
        chosen_tags[random.randint(0,4)] = tags[1]
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE Users SET tags_json = ?,last_ticket_time = ? WHERE qq = ?",(json.dumps(chosen_tags,ensure_ascii=False),today,qq))
        await db.commit()
    return chosen_tags

# 手动刷新tag
async def refresh_tag(qq:str,qq_name:str):
    await ensure_user_row(qq,qq_name)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT refresh_times,last_ticket_time FROM Users WHERE qq = ?",(qq,))
        row = await cur.fetchone()
        if not row:
            print(f"{qq}:绑定刷新次数与时间失败")
            return None,None
        used, last_reset = row
        today = date.today().isoformat()
        if last_reset != today:
            used = 0
            await db.execute("UPDATE Users SET refresh_times= ? ,last_ticket_time = ? WHERE qq = ?",(0,today,qq))
            await db.commit()
        if used >= REFRESH_LIMIT:
            cur2 = await db.execute("SELECT tags_json,refresh_times FROM Users WHERE qq = ?",(qq,))
            row2 = await cur2.fetchone()
            if row2:
                return json.loads(row2[0]),row2[1]
            else:
                return await get_tags(qq,qq_name)
        used += 1
        tags = await generate_tags(qq,qq_name)
        await db.execute("UPDATE Users SET refresh_times = ?, tags_json = ? WHERE qq = ?",(used,json.dumps(tags,ensure_ascii=False),qq))
        await db.commit()
        return tags, used

# 保底逻辑
# async def is_african(qq:str) -> bool:
#     async with aiosqlite.connect(DB) as db:
#         cur = await db.execute("SELECT COUNT(*) "
#                          "FROM RecruitStatus rs "
#                          "WHERE rs.user_id = ?"
#                          ,(qq,))
#         recruit_count = (await cur.fetchone())[0]
#         if recruit_count < AFRICAN:
#             return False
#
#         cur = await db.execute(
#             "SELECT COUNT(*) "
#             "FROM ("
#             "    SELECT rs.result_card_id "
#             "    FROM RecruitStatus rs "
#             "    WHERE rs.user_id = ? "
#             "    ORDER BY rs.id DESC "
#             "    LIMIT ?"
#             ") recent_recruits "
#             "JOIN Cards c ON recent_recruits.result_card_id = c.PicID "
#             "WHERE c.Rare = '精英'",
#             (qq, AFRICAN)
#         )
#
#         african = (await cur.fetchone())[0]
#
#         return african == 0

# 保底逻辑
async def is_african(qq:str) -> tuple[bool,int]:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT COUNT(*) "
                         "FROM RecruitStatus rs "
                         "WHERE rs.user_id = ?"
                         ,(qq,))
        recruit_count = (await cur.fetchone())[0]
        if recruit_count < AFRICAN:
            return False,recruit_count

        cur = await db.execute(
            "SELECT COUNT(*) "
            "FROM ("
            "    SELECT rs.result_card_id "
            "    FROM RecruitStatus rs "
            "    WHERE rs.user_id = ? "
            "    ORDER BY rs.id DESC "
            "    LIMIT ?"
            ") recent_recruits "
            "JOIN Cards c ON recent_recruits.result_card_id = c.PicID "
            "WHERE c.Rare = '精英'",
            (qq, AFRICAN)
        )

        african = (await cur.fetchone())[0]

        cur = await db.execute(
            """
            WITH last_elite AS (
                SELECT rs.id
                FROM RecruitStatus rs
                JOIN Cards c ON rs.result_card_id = c.PicID
                WHERE rs.user_id = ? AND c.Rare = '精英'
                ORDER BY rs.id DESC
                LIMIT 1
            )
            SELECT COUNT(*)
            FROM RecruitStatus rs
            WHERE rs.user_id = ? 
                AND rs.id > (SELECT id FROM last_elite)
            """,
            (qq, qq)
        )

        since_last_elite = (await cur.fetchone())[0]
        return african == 0,since_last_elite

# 数值属性入库处理
# def solve_number(param:str):

# 判断词条对应属性以及参数
def sort_tag_associate_and_param(tags:List[Dict]):
    conditions = [item["associate"] for item in tags]
    params = [item["param"] for item in tags]

    where_conditions = []
    where_clauses = []

    for condition,param in zip(conditions,params):
        if condition == "special":
            continue

        if condition in ("CardName","Effect","Alias"):
            where_conditions.append(f"{condition} LIKE ?")
            where_clauses.append(f"%{param}%")

        if condition in ("Country", "Kind", "Pack", "Status"):
            where_conditions.append(f"{condition} = ?")
            where_clauses.append(param)

        if condition in ("Cost", "AttackCost", "Attack", "Defence"):
            if "-" in param:
                low,high = param.split("-")
                where_conditions.append(f"{condition} BETWEEN ? AND ?")
                where_clauses.extend([int(low),int(high)])
            elif param.startswith("<="):
                where_conditions.append(f"{condition} <= ?")
                where_clauses.append(int(param[2:]))
            elif param.startswith(">="):
                where_conditions.append(f"{condition} >= ?")
                where_clauses.append(int(param[2:]))
            elif param.startswith("<"):
                where_conditions.append(f"{condition} < ?")
                where_clauses.append(int(param[1:]))
            elif param.startswith(">"):
                where_conditions.append(f"{condition} > ?")
                where_clauses.append(int(param[1:]))
            else:
                where_conditions.append(f"{condition} = ?")
                where_clauses.append(int(param))

    return where_conditions,where_clauses

# 处理抽卡逻辑
async def filter_cards_by_tags(tags:List[Dict]):
    tags_copy = tags.copy()
    deleted_tags = {}
    # 确认卡牌稀有度
    selected_rarity = random.choices(list(QUALITY_WEIGHTS.keys()),weights = list(QUALITY_WEIGHTS.values()),k = 1)[0]
    # 是否撕掉tag
    for i in range(len(tags_copy) - 1,-1,-1):
        tag = tags_copy[i]
        if random.random() < 0.005 and tag["associate"] != "special":
            deleted_tags[tag["name"]] = "被划去"
            tags_copy.remove(tag)
        elif tag["associate"] == "special":
            selected_rarity = tag["param"]
            # if tag["name"] == "资深卡牌(少见)":
            #     selected_rarity = "特殊"
            # if tag["name"] == "高级资深卡牌(稀有)":
            #     selected_rarity = "精英"
            # if tag["name"] == "衍生(传说中的！)":
            #     selected_rarity = "衍生"

    async with aiosqlite.connect(DB) as db:
        row = None
        while tags_copy:
            # 处理tags
            conditions, params = sort_tag_associate_and_param(tags_copy)
            conditions.append("Rare = ?")
            params.append(selected_rarity)
            where_clauses = " AND ".join(conditions)
            # 查询数据库
            sql = f"SELECT * FROM Cards WHERE {where_clauses} ORDER BY RANDOM() LIMIT 1"
            cur = await db.execute(sql,params)
            result = await cur.fetchone()
            await cur.close()
            if not result:
                # 判断非特殊tag
                non_special_tags = [tag for tag in tags_copy if tag["associate"] != "special"]
                if non_special_tags:
                    # 防御: tag 可能缺少 weight 字段, 用 .get 兜底
                    deleted = min(non_special_tags,key = lambda x:x.get("weight",0))
                    deleted_tags[deleted["name"]] = "被划去"
                    tags_copy.remove(deleted)
                else:
                    break
            else:
                row = result
                break
            if random.random() < 0.1 and tags_copy:
                non_special_tags = [tag for tag in tags_copy if tag["associate"] != "special"]
                if non_special_tags:
                    punished = non_special_tags[random.randrange(len(non_special_tags))]
                    deleted_tags[punished["name"]] = "被划去"
                    tags_copy.remove(punished)
        # 兜底: 若 row 仍为 None, 依据稀有度随机 (哪怕只剩 special tag 也要走这条)
        if not row:
            cur = await db.execute("SELECT * FROM Cards WHERE Rare = ? ORDER BY RANDOM() LIMIT 1",(selected_rarity,))
            result = await cur.fetchone()
            await cur.close()
            row = result
        # 最终兜底: 选中的稀有度也可能没卡 (DB 里没有对应 Rare), 退化到全库随机, 保证一定能出卡
        if not row:
            cur = await db.execute("SELECT * FROM Cards ORDER BY RANDOM() LIMIT 1")
            result = await cur.fetchone()
            await cur.close()
            row = result

    return row,deleted_tags

# 指令部分
panel = on_command("个人面板")
show = on_command("公开招募")
refresh = on_command("刷新词条")
receive = on_command("接收卡牌")
view = on_command("个人收藏")
trade = on_command("赠送卡牌")
ticket_add = on_command("发放公招券",permission = SUPERUSER)
refresh_add = on_command("增加刷新次数",permission = SUPERUSER)
set_name = on_command("改名")
# start = on_message(priority = 100)

@set_name.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    uid = str(event.user_id)
    name = arg.extract_plain_text().strip()
    if not name:
        await set_name.finish("用法：设置昵称 [你想使用的昵称]")
    # 确保有用户行，然后更新昵称
    await ensure_user_row(uid, name)
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE Users SET qq_name = ? WHERE qq = ?", (name, uid))
        await db.commit()
    await set_name.finish(f"已将你的昵称设置为：{name}")

@panel.handle()
async def _(bot: Bot, event):
    uid = str(event.user_id)
    # 使用 DB 中的昵称（若未设置则为 uid）；get_user_name 已改为从 DB 读, 不再调外部 API
    await ensure_user_row(uid, await get_user_name(bot, uid))
    now = time.time()
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('''
            SELECT tickets 
            FROM Users 
            WHERE qq = ?
        ''',(uid,))
        row = await cur.fetchone()
        ticket_num = row[0] if row else 0
        cur = await db.execute('''
            SELECT status,finish_ts
            FROM RecruitStatus 
            WHERE user_id = ? 
            ORDER BY id DESC 
            LIMIT 1
        ''',(uid,))
        row2 = await cur.fetchone()
        status = "无招募"
        if row2:
            # 这里数据库里存的时间是string，看看怎么整
            # 改成时间戳了。到2038年就会因为超过21亿而不能用，有意思
            status_db = row2[0]
            end = row2[1]
            if status_db == "招募中":
                remain = max(0,end - int(now))
                if remain > 0:
                    status = f"寻找中，约{ceil(remain/60)}分钟后完成招募"
                else:
                    status = "等待接收"
        cur = await db.execute('''
            SELECT COUNT(*) 
            FROM RecruitStatus 
            WHERE user_id = ?
        ''',(uid,))
        recruit_times = (await cur.fetchone())[0]
        cur = await db.execute('''
            SELECT COUNT(*) 
            FROM TradeStatus 
            WHERE answer = 0 AND(from_uid = ? OR to_uid = ?)
        ''',(uid,uid))
        trades = (await cur.fetchone())[0]
        cur = await db.execute('''
            SELECT COUNT(*) 
            FROM TradeStatus 
            WHERE from_uid = ? AND answer = 1 AND status = 1
        ''',(uid,))
        sends = (await cur.fetchone())[0]
        cur = await db.execute('''
                    SELECT COUNT(*) 
                    FROM TradeStatus 
                    WHERE to_uid = ? AND answer = 1 AND status = 1
                ''', (uid,))
        gets = (await cur.fetchone())[0]
        african_progress = (await is_african(uid))[1]
    await panel.finish(
        f"用户ID:{event.user_id}\n"
        f"招聘许可：{ticket_num} \n"
        f"招募状态：{status}\n"
        f"招募次数：{recruit_times}\n"
        f"保底进度：{african_progress}/{AFRICAN}\n"
        f"赠送列表：{trades}\n"
        f"赠送发起：{sends}\n"
        f"赠送收到：{gets}\n"
    )

# 招募主逻辑
async def start_recruit(qq,qq_name,tags,choices):
    # chosen_letters = [c for c in choices if c in "ABCDE"][:3]
    chosen_letters = []
    for c in choices:
        if c in "ABCDE" and len(chosen_letters) < 3:
            chosen_letters.append(c)
        else:
            # print(f"{qq}:招募选项错误")
            return "请选择1-3个词条进行公开招募。"
    if not chosen_letters:
        # print(f"{qq}:无选项进入招募")
        return "请选择1-3个词条进行公开招募。"
    await ensure_user_row(qq,qq_name)
    chosen_tags = [tags[c] for c in chosen_letters]

    duration = T_DEFAULT
    for tags in chosen_tags:
        if tags["name"] == "资深卡牌(少见)":
           duration = T_EXPERT
        if tags["name"] == "高级资深卡牌(稀有)":
            duration = T_HIGH_EXPERT
    end_ts = int(time.time()) + duration * 60

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('''
            SELECT tickets 
            FROM Users 
            WHERE qq = ?
        ''',(qq,))
        row = await cur.fetchone()
        tickets = row[0]
        if tickets <= 0:
            return "你的招聘许可不足。"
        cur = await db.execute('''
            SELECT status 
            FROM RecruitStatus 
            WHERE user_id = ? 
            ORDER BY id DESC
        ''',(qq,))
        row2 = await cur.fetchone()
        if row2 and row2[0] == "招募中":
            return "您已有招募正在进行,请稍等。"

        await db.execute('''
            UPDATE Users 
            SET tickets = tickets -1 
            WHERE qq = ?
        ''',(qq,))
        await db.commit()

        await db.execute('''
            INSERT INTO RecruitStatus(user_id,start_ts,finish_ts,status,ticket_tags) 
            VALUES(?,?,?,?,?)
        ''',(qq,int(time.time()),end_ts,"招募中",json.dumps(chosen_tags,ensure_ascii=False)))
        await db.commit()
    return f"开始公开招募，请等待{duration}分钟。"

@show.handle()
async def _(bot:Bot, event:MessageEvent, arg:Message = CommandArg()):
    uid = str(event.user_id)
    user_name = await get_user_name(bot,uid)
    await ensure_user_row(uid,user_name)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('''
                    SELECT tickets 
                    FROM Users 
                    WHERE qq = ?
                ''', (uid,))
        tickets = (await cur.fetchone())[0]
    tags, used = await get_tags(uid,user_name)
    choices = ['A','B','C','D','E']
    arg_text = arg.extract_plain_text().strip().replace('+','').replace(' ','').upper()
    # arg_text = arg.extract_plain_text().strip().upper()
    if not arg_text:
        lines = [f"您的招聘许可剩余{tickets}张\n"] if tickets else ["您没有招聘许可了\n"]
        if (await is_african(uid))[0]:
            lines.append("瓦，这还不出金?兔兔把自己高资分给你捏\n")
        lines.append("您的招募词条如下：\n")
        for i,tag in enumerate(tags[:DAILY_TAGS]):
            lines.append(f"{choices[i]}:{tag['name']}\n")
        lines.append(f"刷新剩余：{REFRESH_LIMIT - used}/{REFRESH_LIMIT}次\n")
        lines.append(f"发送'刷新词条'刷新\n")
        lines.append("指令后增加1-3个词条以招募，如ABC")
        await show.finish(''.join(lines))
    else:
        choices_map = {
            "A": tags[0],
            "B": tags[1],
            "C": tags[2],
            "D": tags[3],
            "E": tags[4]
        }
        tags_name = [item["name"] for item in tags]
        chosen = [c for c in arg_text if c in "ABCDE"][:3]
        chosen_name = [choices_map[c]["name"] for c in chosen]
        if "高级资深卡牌(稀有)" in tags_name and "高级资深卡牌(稀有)" not in chosen_name:
            await show.finish("高资不抽给我")
        result = await start_recruit(uid,user_name,choices_map,arg_text)
        await show.finish(result)

@refresh.handle()
async def _(bot:Bot, event:MessageEvent):
    uid = str(event.user_id)
    user_name = await get_user_name(bot,uid)

    tags,used = await refresh_tag(uid,user_name)
    choices = ['A', 'B', 'C', 'D', 'E']
    lines = []
    if used >= REFRESH_LIMIT:
        lines.append("您今日的刷新次数已用完。")
    else:
        lines.append("刷新成功")
    lines.append("您的招募词条如下:")
    for i,tag in enumerate(tags[:DAILY_TAGS]):
        lines.append(f"{choices[i]}:{tag['name']}")
    await refresh.finish('\n'.join(lines))

@receive.handle()
async def _(bot: Bot,event: MessageEvent):
    uid = str(event.user_id)
    user_name = await get_user_name(bot,uid)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('''
            SELECT status, finish_ts, ticket_tags, id
            FROM RecruitStatus 
            WHERE user_id = ? 
            ORDER BY id DESC 
            LIMIT 1
        ''',(uid,))
        row = await cur.fetchone()
        if not row or row[0] == "已完成":
            await receive.finish("你当前没有公开招募。")
        now_ts = int(time.time())
        if row[0] == "招募中":
            if now_ts < (row[1] or 0):
                end_time = datetime.fromtimestamp(row[1]).strftime("%m-%d %H:%M")
                await receive.finish(f"招募将于{end_time}完成，请指挥官耐心等候。")
            else:
                recruit_tags = json.loads(row[2])
                card,deleted_tags = await filter_cards_by_tags(recruit_tags)
                if card and row[3]:
                    await db.execute("UPDATE RecruitStatus SET status = '已完成', result_card_id = ? WHERE id = ?",(card[0],row[3]))
                    await db.commit()
                    await db.execute('''
                        INSERT INTO UserCards(user_id,card_id,count) 
                        VALUES(?,?,1) 
                        ON CONFLICT(user_id,card_id) 
                        DO UPDATE SET count = count + 1
                    ''',(uid,card[0]))
                    await db.commit()
                    await generate_tags(uid,user_name)
                    pic = IMAGE_DIR / f"{card[0]}.png"
                    delete = []
                    if deleted_tags:
                        delete.extend(f"\n{key}:{value}" for key,value in deleted_tags.items())
                    if pic.exists():
                        await receive.finish(MessageSegment.text(f"已招募{card[1]}并刷新词条 "+"".join(delete)) + MessageSegment.image(f"file://{pic.resolve()}"))
                    else:
                        await receive.finish(f"招募到了卡牌 {card[1]} ，但图片变滚木了"+"".join(delete))
                elif not card:
                    await receive.finish("未招募到卡牌，也许是哪里出了问题？")


@view.handle()
async def _(bot:Bot, event: MessageEvent,arg: Message = CommandArg()):
    uid = str(event.user_id)
    user_name = await get_user_name(bot,uid)
    rare_mapper = {
        "金卡": "精英",
        "银卡": "特殊",
        "铜卡": "限定",
        "铁卡": "普通",
        "金": "精英",
        "银": "特殊",
        "铜": "限定",
        "铁": "普通"
    }
    async with aiosqlite.connect(DB) as db:
        arg_text = arg.extract_plain_text().strip()
        sql = '''
                    SELECT uc.card_id,uc.count 
                    FROM UserCards uc 
                    JOIN Cards c 
                    ON uc.card_id = c.PicID 
                    WHERE uc.user_id = ? 
                '''
        params = [uid]
        if arg_text in rare_mapper:
            sql += "AND Rare = ? "
            params.append(rare_mapper[arg_text])
        elif arg_text in ("精英", "特殊", "限定", "普通", "衍生"):
            sql += "AND Rare = ? "
            params.append(arg_text)
        sql += "ORDER BY uc.count DESC, c.Cost"
        
        cur = await db.execute(sql,params)
        rows = await cur.fetchall()
    if not rows:
        await view.finish('你的卡牌收藏为空')
    imgs = []
    for row in rows:
        imgpath = IMAGE_DIR / f"{row[0]}.png"
        if imgpath.exists():
            try:
                image = Image.open(imgpath).convert('RGBA')
                image.thumbnail(CARD_THUMB)
            except Exception:
                image = Image.new('RGBA',CARD_THUMB,(60,60,60))
        else:
            image = Image.new('RGBA', CARD_THUMB, (60, 60, 60))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0,CARD_THUMB[1]-20,20,CARD_THUMB[1]),fill=(90,90,90))
        draw.text((5,CARD_THUMB[1]-15),f'x{row[1]}', font = FONT,fill = (255,255,0))
        imgs.append(image)
    pages = [imgs[i:i + CARDS_PER_PAGE] for i in range(0, len(imgs), CARDS_PER_PAGE)]
    for idx, p in enumerate(pages):
        rows_needed = ceil(len(p) / COLS)
        w = COLS * CARD_THUMB[0]
        h = rows_needed * (CARD_THUMB[1])
        bg = Image.new('RGBA', (w, h), (20, 20, 20))
        for i, im in enumerate(p):
            x = (i % COLS) * CARD_THUMB[0]
            y = (i // COLS) * (CARD_THUMB[1])
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            bg.paste(im, (x, y), im)

        img_bytes = BytesIO()
        bg.convert('RGB').save(img_bytes,format = "PNG")
        img_bytes.seek(0)

        await view.send(MessageSegment.image(img_bytes))
    await view.finish()

@trade.handle()
async def _(bot:Bot, event:MessageEvent, args:Message = CommandArg()):
    uid = str(event.user_id)
    user_name = await get_user_name(bot,uid)
    args_text = args.extract_plain_text().strip().replace("：",":")
    if not args_text:
        await trade.finish(show_trade_help())

    parts = args_text.split(":")
    if len(parts) < 2:
        await trade.finish("请使用命令：赠送卡牌[用户qq]：[卡牌名]")

    target_uid = str(parts[0]).strip()
    card_name = str(parts[1]).strip().replace(" ","").upper()
    try:
        await ensure_user_row(uid,await get_user_name(bot,uid))
        # 这里可能尝试获取未使用该功能的用户的qq昵称
        await ensure_user_row(target_uid, await get_user_name(bot, target_uid))
    except Exception as e:
        print(f"赠送卡牌出错：{e}")
        await trade.finish("赠送卡牌时出错！")
    finally:
        await initiate_trade(uid, target_uid, card_name)

def show_trade_help():
    return (
        "赠送公招卡牌\n"
        "使用方法：\n"
        "• 赠送卡牌 [用户qq]：[卡牌名] - 发起赠送请求\n"
        "• 赠送列表 - 查看待处理的赠送\n"
        "• 接受赠送 [赠送ID] - 接受赠送\n"
        "• 拒绝赠送 [赠送ID] - 拒绝赠送\n"
        "• 取消赠送 [赠送ID] - 取消赠送\n"
        "• 查看个人面板获知ID"
    )


async def initiate_trade(from_uid:str, to_uid:str, card_name:str):
    if from_uid == to_uid:
        await trade.finish("不能将卡牌赠送给自己。")

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('''
            SELECT qq,qq_name 
            FROM Users 
            WHERE qq IN(?,?)
        ''',(from_uid,to_uid))
        users = await cur.fetchall()
        user_dict = {user[0]:user[1] for user in users}

        from_name = user_dict.get(from_uid,f'用户{from_uid}')
        to_name = user_dict.get(to_uid,f'用户{to_uid}')

        cur = await db.execute('''
            SELECT uc.count, c.PicID
            FROM UserCards uc 
            JOIN Cards c ON uc.card_id = c.PicID 
            WHERE uc.user_id = ? and UPPER(c.CardName) = ?
        ''',(from_uid,card_name))
        user_card = await cur.fetchone()
        if not user_card or user_card[0] <= 0:
            await trade.finish(f"你没有卡牌{card_name}。")

        card_id = user_card[1]
        cur = await db.execute('''
            UPDATE UserCards 
            SET count = count -1 
            WHERE user_id = ? AND card_id = ?
        ''',(from_uid,card_id))

        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        await db.execute('''
            INSERT INTO TradeStatus (time,from_uid,to_uid,offer_card_id,status,answer) 
            VALUES (?,?,?,?,?,?)
        ''',(current_time,from_uid,to_uid,card_id,0,0))
        await db.execute("DELETE FROM UserCards WHERE count <= 0")
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        trade_id = (await cur.fetchone())[0]

        await trade.finish(
            f"请求已发送！\n"
            f"赠送ID: {trade_id}\n"
            f"目标用户: {to_name}({to_uid})\n"
            f"赠送卡牌: {card_name}\n"
            f"对方可以使用'接受赠送{trade_id}'来确认赠送"
        )

trade_list = on_command("赠送列表")
@trade_list.handle()
async def handle_trade_list(bot:Bot, event:MessageEvent):
    user_id = str(event.user_id)

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('''
            SELECT t.id,
                t.time,
                t.from_uid,
                t.to_uid,
                from_user.qq_name AS from_user_name,
                to_user.qq_name as to_user_name,
                c.CardName,
                t.status,
                t.answer 
            FROM TradeStatus t 
            JOIN Cards c ON t.offer_card_id = c.PicID 
            JOIN Users from_user ON t.from_uid = from_user.qq 
            JOIN Users to_user ON t.to_uid = to_user.qq
            WHERE (from_uid = ? OR to_uid = ?) AND t.status = 0 
            ORDER BY t.id DESC
        ''',(user_id,user_id))
        trades = await cur.fetchall()

    if not trades:
        await trade_list.finish("没人送你卡捏")

    tr_list = []
    for tr in trades:
        trade_id,trade_time,from_uid,to_uid,from_name,to_name,card_name,status,answer = tr
        role = "发起" if from_uid == user_id else "接收"
        status_text = "待回应" if answer == 0 else "已回应"

        tr_list.append(f'赠送序列{trade_id}:{role}|{card_name}|{status_text}')
    result = "你的未处理赠送： \n"+"\n".join(tr_list)
    result += "\n 使用“接受赠送[ID]”“拒绝赠送[ID]”“取消赠送[ID]”来处理赠送"
    await trade_list.finish(result)

accept_trade = on_command("接受赠送")
reject_trade = on_command("拒绝赠送")
cancel_trade = on_command("取消赠送")

@accept_trade.handle()
async def handle_accept(bot: Bot, event:MessageEvent, args: Message = CommandArg()):
    msg = await process_trade_response(bot, event, args, True)
    # print(msg)
    await accept_trade.finish(msg)

@reject_trade.handle()
async def handle_reject(bot: Bot, event:MessageEvent, args: Message = CommandArg()):
    msg = await process_trade_response(bot, event, args, False)
    # print(msg)
    await reject_trade.finish(msg)

@cancel_trade.handle()
async def handle_cancel(bot: Bot, event:MessageEvent, args: Message = CommandArg()):
    user_id = str(event.user_id)
    args_text = args.extract_plain_text().strip()

    if not args_text or not args_text.isdigit():
        await cancel_trade.finish("请指定取消的赠送ID")

    trade_id = int(args_text)

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('''
            SELECT from_uid, status ,offer_card_id
            FROM TradeStatus 
            WHERE id = ?
        ''',(trade_id,))
        trade = await cur.fetchone()
        if not trade:
            await cancel_trade.finish(f"赠送事件{trade_id}不存在")
            print(trade)
        from_uid,status,card_id = trade
        if from_uid != user_id:
            await cancel_trade.finish("您只能取消自己发起的赠送")
        if status != 0:
            await cancel_trade.finish("该赠送事件已完成或已取消")

        await db.execute("UPDATE TradeStatus SET status = 3,answer = 1 WHERE id = ?",(trade_id,))
        await db.commit()
        await db.execute("INSERT INTO UserCards(user_id,card_id,count) VALUES(?,?,1) ON CONFLICT(user_id,card_id) DO UPDATE SET count = count +1",(user_id,card_id))
        await db.commit()
    await cancel_trade.finish(f"赠送{trade_id}已取消")

async def process_trade_response(bot:Bot,event:MessageEvent,args:Message,accept:bool):
    user_id = str(event.user_id)
    args_text = args.extract_plain_text().strip()
    action = "接收" if accept else "拒绝"
    if not args_text or not args_text.isdigit():
        if args_text.upper() != 'ALL':
            return f"请指定要{action}的赠送ID,或者使用[ALL]操作全部记录"

    return_message = []
    async with aiosqlite.connect(DB) as db:
        if args_text.upper() == "ALL":
            cur = await db.execute(
                "SELECT id "
                "FROM TradeStatus "
                "WHERE to_uid = ? AND answer = 0"
                ,(user_id,))
            trade_ids = [row[0] for row in await cur.fetchall()]
            if not trade_ids:
                return "您当前没有赠送事件。"
        else:
            trade_ids = [int(args_text)]

        for trade_id in trade_ids:
            cur = await db.execute('''
                SELECT from_uid, to_uid, offer_card_id, status 
                FROM TradeStatus 
                WHERE id = ?
            ''',(trade_id,))
            trade = await cur.fetchone()

            if not trade:
                return_message.append(f"赠送{trade_id}不存在")
                break

            from_uid,to_uid,card_id,status = trade

            if to_uid != user_id:
                return_message.append("这不是发给你的赠送请求")
                break

            if status != 0:
                return_message.append("该赠送事件已完成或已取消")
                break

            if accept:
                await execute_trade(db,trade_id,from_uid,to_uid,card_id)
                return_message.append(f"赠送事件{trade_id}已接收！")
            else:
                await db.execute("UPDATE TradeStatus SET status = 2,answer = 1 WHERE id = ?",(trade_id,))
                await db.commit()
                await db.execute(
                    "INSERT INTO UserCards(user_id,card_id,count) VALUES(?,?,1) ON CONFLICT(user_id,card_id) DO UPDATE SET count = count +1",
                    (from_uid, card_id))
                await db.commit()
                return_message.append(f"赠送事件{trade_id}已拒绝！")
    if len(return_message) == 0:
        return "您当前没有赠送事件。"
    return return_message

async def execute_trade(db,trade_id: int,from_uid: str, to_uid: str, card_id:int):
    # await db.execute("UPDATE UserCards SET count = count -1 WHERE user_id = ? AND card_id = ?",(from_uid,card_id))
    await db.execute("INSERT INTO UserCards (user_id,card_id,count) VALUES(?,?,1) "
                     "ON CONFLICT(user_id,card_id) DO UPDATE SET count = count + 1",(to_uid,card_id))
    await db.execute("DELETE FROM UserCards WHERE count <= 0")
    await db.execute("UPDATE TradeStatus SET status = 1, answer = 1 WHERE id = ?",(trade_id,))
    await db.commit()

@ticket_add.handle()
async def add_ticket(bot :Bot, event: MessageEvent,arg:Message = CommandArg()):
    user_id = arg.extract_plain_text().strip()

    if not user_id:
        await ticket_add.finish("请输入给予招聘许可的用户ID(qq号)")

    async with aiosqlite.connect(DB) as db:
        if user_id in ('all', 'ALL'):
            await db.execute(f"UPDATE Users SET tickets = tickets +1 WHERE tickets < {MAX_TICKET}")
            await db.commit()
            await ticket_add.finish("已为所有记录用户增加1张招聘许可！（上限为5张）")
        # 保证目标用户有行（使用其已有昵称或用 id 作为回退名）
        target_name = await get_user_name(bot, user_id)
        await ensure_user_row(user_id, target_name)
        await db.execute(f"UPDATE Users SET tickets = tickets +1 WHERE qq = ? AND tickets < {MAX_TICKET}",(user_id,))
        await db.commit()
        await ticket_add.finish(f"已为用户{user_id}增加1张招聘许可！（上限为5张）")

@refresh_add.handle()
async def reload_add(bot :Bot, event: MessageEvent,arg:Message = CommandArg()):
    user_id = arg.extract_plain_text().strip()

    if not user_id:
        await refresh_add.finish("请输入增加刷新次数的用户ID(qq号)")

    async with aiosqlite.connect(DB) as db:
        if user_id in ('all', 'ALL'):
            await db.execute(f"UPDATE Users SET refresh_times = refresh_times -1 WHERE refresh_times > 0")
            await db.commit()
            await refresh_add.finish("已为所有记录用户增加1次刷新次数！")
        target_name = await get_user_name(bot, user_id)
        await ensure_user_row(user_id, target_name)
        await db.execute(f"UPDATE Users SET refresh_times = refresh_times -1 WHERE qq = ? AND refresh_times > 0",(user_id,))
        await db.commit()
        await refresh_add.finish(f"已为用户{user_id}增加1次刷新次数！）")

# 每日更新
try:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler
    @scheduler.scheduled_job('cron', hour=0,minute=0,timezone="Asia/Shanghai")
    async def _daily_reset():
        async with aiosqlite.connect(DB) as db:
            await db.execute('''
                UPDATE Users 
                SET refresh_times = 0
            ''')
            await db.commit()
        print(f"{datetime.now()}刷新任务成功")


    @scheduler.scheduled_job('cron', hour="0,6,12,18,21",timezone="Asia/Shanghai")
    async def _daily_ticket():
        async with aiosqlite.connect(DB) as db:
            await db.execute(f'''
                    UPDATE Users 
                    SET tickets = tickets +1
                    WHERE tickets < {MAX_TICKET}
                ''')
            await db.commit()
        print(f"{datetime.now()}发放任务成功")
except Exception as e:
    # pass
    print(f"{datetime.now()}定时任务失败:{e}")
# ==================== API 路由 ====================
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

app = get_app()

# 图片转BASE64
# 超过该大小的图片不编码, 避免单次响应过大 / 内存炸
IMAGE_BASE64_MAX_BYTES = 5 * 1024 * 1024  # 5MB

# LRU 缓存: 同一张图多次返回时, 直接走内存, 避免重复读盘 + base64 编码
# key = (path_str, mtime, size), value = base64 string 或 None
_IMAGE_BASE64_CACHE_MAX = 128
_IMAGE_BASE64_CACHE = {}  # dict 保持插入顺序, 简易 LRU

def _image_base64_cache_get(key):
    v = _IMAGE_BASE64_CACHE.get(key)
    if v is None:
        return None, False
    # 命中: 移动到末尾 (最近使用)
    _IMAGE_BASE64_CACHE.pop(key, None)
    _IMAGE_BASE64_CACHE[key] = v
    return v, True

def _image_base64_cache_put(key, value):
    _IMAGE_BASE64_CACHE[key] = value
    # 超过上限: 弹出最久未用的 (字典第一个 key)
    while len(_IMAGE_BASE64_CACHE) > _IMAGE_BASE64_CACHE_MAX:
        _IMAGE_BASE64_CACHE.pop(next(iter(_IMAGE_BASE64_CACHE)), None)

def image_to_base64(image_path: Path) -> Optional[str]:
    """将图片转换为BASE64字符串 (带 LRU 缓存)"""
    try:
        # 不存在 / stat 失败: 走一次实读, 缓存 None 也可避免反复 stat
        if not image_path.exists():
            return None
        st = image_path.stat()
        if st.st_size > IMAGE_BASE64_MAX_BYTES:
            return None
        key = (str(image_path), st.st_mtime, st.st_size)
        cached, hit = _image_base64_cache_get(key)
        if hit:
            return cached
        with open(image_path, "rb") as f:
            img_data = f.read()
        b64 = base64.b64encode(img_data).decode("utf-8")
        _image_base64_cache_put(key, b64)
        return b64
    except Exception:
        return None

# 检查用户登录
async def check_login(uid: str) -> bool:
    """检查用户是否已登录（存在于数据库中）"""
    if not uid:
        return False
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT qq FROM Users WHERE qq = ?", (uid,))
        row = await cur.fetchone()
        return row is not None

# API: 获取用户信息
@app.post("/kards/user_info")
async def api_user_info(request: Request):
    """获取用户词条、刷新次数、招募状态"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    async with aiosqlite.connect(DB) as db:
        # 获取用户基本信息
        cur = await db.execute("SELECT tickets, refresh_times, last_ticket_time FROM Users WHERE qq = ?", (uid,))
        user_row = await cur.fetchone()
        tickets = user_row[0] if user_row else 0
        refresh_times = user_row[1] if user_row else 0
        
        # 获取词条
        cur = await db.execute("SELECT tags_json FROM Users WHERE qq = ?", (uid,))
        tags_row = await cur.fetchone()
        tags = json.loads(tags_row[0]) if tags_row and tags_row[0] else []
        tags_list = [t["name"] for t in tags[:DAILY_TAGS]]
        
        # 获取招募状态
        cur = await db.execute(
            "SELECT status, finish_ts FROM RecruitStatus WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (uid,)
        )
        recruit_row = await cur.fetchone()
        recruit_status = "无招募"
        is_finished = False
        if recruit_row:
            status_db = recruit_row[0]
            finish_ts = recruit_row[1]
            now_ts = int(time.time())
            if status_db == "招募中":
                if now_ts < (finish_ts or 0):
                    remain = ceil((finish_ts - now_ts) / 60)
                    recruit_status = f"寻找中，约{remain}分钟后完成"
                else:
                    recruit_status = "等待接收"
                    is_finished = True
            elif status_db == "已完成":
                recruit_status = "已完成"
                is_finished = True
        
        # 获取保底进度
        african_progress = (await is_african(uid))[1]
    
    return JSONResponse({
        "code": 0,
        "msg": "success",
        "data": {
            "uid": uid,
            "tickets": tickets,
            "refresh_times": refresh_times,
            "refresh_limit": REFRESH_LIMIT,
            "tags": tags_list,
            "recruit_status": recruit_status,
            "is_recruit_finished": is_finished,
            "african_progress": african_progress,
            "african_limit": AFRICAN
        }
    })

# API: 刷新词条
@app.post("/kards/refresh_tags")
async def api_refresh_tags(request: Request):
    """刷新词条并返回新词条"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    user_name = await get_user_name(None, uid)
    tags, used = await refresh_tag(uid, user_name)
    
    if used >= REFRESH_LIMIT:
        return JSONResponse({
            "code": 1,
            "msg": "今日刷新次数已用完",
            "data": {
                "tags": [t["name"] for t in tags[:DAILY_TAGS]],
                "refresh_used": used,
                "refresh_limit": REFRESH_LIMIT
            }
        })
    
    return JSONResponse({
        "code": 0,
        "msg": "刷新成功",
        "data": {
            "tags": [t["name"] for t in tags[:DAILY_TAGS]],
            "refresh_used": used,
            "refresh_limit": REFRESH_LIMIT
        }
    })

# API: 查询卡牌收藏
@app.post("/kards/user_cards")
async def api_user_cards(request: Request):
    """返回用户拥有的卡牌，包含BASE64图片和张数"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    rare_filter = data.get("rare", None)
    
    async with aiosqlite.connect(DB) as db:
        sql = '''
            SELECT uc.card_id, uc.count, c.CardName, c.Rare, c.Country, c.Cost, c.Attack, c.Defence
            FROM UserCards uc 
            JOIN Cards c ON uc.card_id = c.PicID 
            WHERE uc.user_id = ?
        '''
        params = [uid]
        
        rare_mapper = {
            "金卡": "精英", "银卡": "特殊", "铜卡": "限定", "铁卡": "普通",
            "金": "精英", "银": "特殊", "铜": "限定", "铁": "普通"
        }
        
        if rare_filter:
            if rare_filter in rare_mapper:
                sql += " AND Rare = ?"
                params.append(rare_mapper[rare_filter])
            elif rare_filter in ("精英", "特殊", "限定", "普通", "衍生"):
                sql += " AND Rare = ?"
                params.append(rare_filter)
        
        sql += " ORDER BY uc.count DESC, c.Cost"
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    
    if not rows:
        return JSONResponse({
            "code": 0,
            "msg": "卡牌收藏为空",
            "data": {"cards": []}
        })
    
    cards_list = []
    for row in rows:
        card_id, count, card_name, rare, country, cost, attack, defence = row
        img_path = IMAGE_DIR / f"{card_id}.png"
        img_base64 = image_to_base64(img_path)
        
        cards_list.append({
            "card_id": card_id,
            "card_name": card_name,
            "count": count,
            "rare": rare,
            "country": country,
            "cost": cost,
            "attack": attack,
            "defence": defence,
            "image_base64": img_base64
        })
    
    return JSONResponse({
        "code": 0,
        "msg": "success",
        "data": {"cards": cards_list}
    })

# API: 获取赠送列表
@app.post("/kards/trade_list")
async def api_trade_list(request: Request):
    """获取用户的赠送列表，包含卡牌详细信息和图片"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('''
            SELECT t.id, t.time, t.from_uid, t.to_uid,
                from_user.qq_name AS from_name,
                to_user.qq_name AS to_name,
                c.CardName, c.Rare, c.Country, c.Cost, c.Attack, c.Defence, c.PicID,
                t.status, t.answer
            FROM TradeStatus t 
            JOIN Cards c ON t.offer_card_id = c.PicID 
            JOIN Users from_user ON t.from_uid = from_user.qq 
            JOIN Users to_user ON t.to_uid = to_user.qq
            WHERE (from_uid = ? OR to_uid = ?) AND t.status = 0 
            ORDER BY t.id DESC
        ''', (uid, uid))
        trades = await cur.fetchall()
    
    trades_list = []
    for tr in trades:
        trade_id, trade_time, from_uid, to_uid, from_name, to_name, card_name, rare, country, cost, attack, defence, card_id, status, answer = tr
        role = "发起方" if from_uid == uid else "接收方"
        status_text = "待回应" if answer == 0 else "已回应"
        
        img_path = IMAGE_DIR / f"{card_id}.png"
        img_base64 = image_to_base64(img_path)
        
        trades_list.append({
            "trade_id": trade_id,
            "time": trade_time,
            "from_uid": from_uid,
            "to_uid": to_uid,
            "from_name": from_name,
            "to_name": to_name,
            "card_info": {
                "card_id": card_id,
                "card_name": card_name,
                "rare": rare,
                "country": country,
                "cost": cost,
                "attack": attack,
                "defence": defence,
                "image_base64": img_base64
            },
            "role": role,
            "status": status_text
        })
    
    return JSONResponse({
        "code": 0,
        "msg": "success",
        "data": {"trades": trades_list}
    })

# API: 处理赠送（接受/拒绝/取消）
@app.post("/kards/handle_trade")
async def api_handle_trade(request: Request):
    """
    处理赠送请求
    action: accept(接受), reject(拒绝), cancel(取消)
    - accept/reject: 仅接收方(tou_uid)可操作
    - cancel: 仅发起方(from_uid)可操作
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    action = data.get("action")
    if action not in ("accept", "reject", "cancel"):
        return JSONResponse({"code": 1, "msg": "action参数无效，可选: accept/reject/cancel", "data": None})
    
    trade_id = data.get("trade_id")
    if not trade_id:
        return JSONResponse({"code": 1, "msg": "请指定赠送ID", "data": None})
    
    try:
        trade_id = int(trade_id)
    except ValueError:
        return JSONResponse({"code": 1, "msg": "赠送ID格式错误", "data": None})
    
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT from_uid, to_uid, offer_card_id, status, answer FROM TradeStatus WHERE id = ?",
            (trade_id,)
        )
        trade = await cur.fetchone()
        
        if not trade:
            return JSONResponse({"code": 1, "msg": f"赠送{trade_id}不存在", "data": None})
        
        from_uid, to_uid, card_id, status, answer = trade
        
        if status != 0:
            return JSONResponse({"code": 1, "msg": "该赠送已完成或已取消", "data": None})
        
        # 接受/拒绝操作
        if action in ("accept", "reject"):
            if to_uid != uid:
                return JSONResponse({"code": 1, "msg": "这不是发给你的赠送请求", "data": None})
            
            if answer != 0:
                return JSONResponse({"code": 1, "msg": "该赠送已回应", "data": None})
            
            if action == "accept":
                await execute_trade(db, trade_id, from_uid, to_uid, card_id)
                return JSONResponse({
                    "code": 0,
                    "msg": f"赠送{trade_id}已接收",
                    "data": None
                })
            else:  # reject
                await db.execute("UPDATE TradeStatus SET status = 2, answer = 1 WHERE id = ?", (trade_id,))
                await db.commit()
                await db.execute(
                    "INSERT INTO UserCards(user_id,card_id,count) VALUES(?,?,1) ON CONFLICT(user_id,card_id) DO UPDATE SET count = count + 1",
                    (from_uid, card_id)
                )
                await db.commit()
                return JSONResponse({
                    "code": 0,
                    "msg": f"赠送{trade_id}已拒绝",
                    "data": None
                })
        
        # 取消操作
        if action == "cancel":
            if from_uid != uid:
                return JSONResponse({"code": 1, "msg": "只能取消自己发起的赠送", "data": None})
            
            await db.execute("UPDATE TradeStatus SET status = 3, answer = 1 WHERE id = ?", (trade_id,))
            await db.commit()
            await db.execute(
                "INSERT INTO UserCards(user_id,card_id,count) VALUES(?,?,1) ON CONFLICT(user_id,card_id) DO UPDATE SET count = count + 1",
                (uid, card_id)
            )
            await db.commit()
            return JSONResponse({
                "code": 0,
                "msg": f"赠送{trade_id}已取消",
                "data": None
            })

# API: 赠送卡牌
@app.post("/kards/give_trade")
async def api_give_trade(request: Request):
    """赠送卡牌给其他用户"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    target_uid = data.get("target_uid")
    card_name = data.get("card_name")
    
    if not target_uid or not card_name:
        return JSONResponse({"code": 1, "msg": "请指定目标用户和卡牌名称", "data": None})
    
    if uid == target_uid:
        return JSONResponse({"code": 1, "msg": "不能赠送给自己", "data": None})
    
    card_name = card_name.strip().upper()
    
    async with aiosqlite.connect(DB) as db:
        # 检查目标用户是否存在
        cur = await db.execute("SELECT qq FROM Users WHERE qq = ?", (target_uid,))
        if not await cur.fetchone():
            return JSONResponse({"code": 1, "msg": "目标用户不存在", "data": None})
        
        # 检查赠送方是否有该卡牌
        cur = await db.execute('''
            SELECT uc.count, c.PicID 
            FROM UserCards uc 
            JOIN Cards c ON uc.card_id = c.PicID 
            WHERE uc.user_id = ? AND UPPER(c.CardName) = ?
        ''', (uid, card_name))
        user_card = await cur.fetchone()
        
        if not user_card or user_card[0] <= 0:
            return JSONResponse({"code": 1, "msg": f"你没有卡牌{card_name}", "data": None})
        
        card_id = user_card[1]
        
        # 扣减卡牌
        await db.execute(
            "UPDATE UserCards SET count = count - 1 WHERE user_id = ? AND card_id = ?",
            (uid, card_id)
        )
        
        # 创建赠送记录
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO TradeStatus (time, from_uid, to_uid, offer_card_id, status, answer) VALUES (?,?,?,?,?,?)",
            (current_time, uid, target_uid, card_id, 0, 0)
        )
        await db.execute("DELETE FROM UserCards WHERE count <= 0")
        await db.commit()
        
        cur = await db.execute("SELECT last_insert_rowid()")
        trade_id = (await cur.fetchone())[0]
    
    return JSONResponse({
        "code": 0,
        "msg": "赠送请求已发送",
        "data": {
            "trade_id": trade_id,
            "target_uid": target_uid,
            "card_name": card_name
        }
    })

# API: 获取招募到的卡牌详情
@app.post("/kards/get_recruit_result")
async def api_get_recruit_result(request: Request):
    """获取招募结果并领取卡牌"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    user_name = await get_user_name(None, uid)
    
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT status, finish_ts, ticket_tags, id FROM RecruitStatus WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (uid,)
        )
        row = await cur.fetchone()
        
        if not row:
            return JSONResponse({"code": 1, "msg": "当前没有进行中的招募", "data": None})
        # 幂等领取: 若已是"已完成"且有 result_card_id, 直接返回卡牌详情 (避免前端刷新/重复点击时报错)
        if row[0] == "已完成":
            existing_card_id = row[3]
            if existing_card_id:
                cur = await db.execute("SELECT CardName, Rare, Country FROM Cards WHERE PicID = ?", (existing_card_id,))
                card_info = await cur.fetchone()
                if card_info:
                    img_path = IMAGE_DIR / f"{existing_card_id}.png"
                    return JSONResponse({
                        "code": 0,
                        "msg": "招募完成",
                        "data": {
                            "card_id": existing_card_id,
                            "card_name": card_info[0],
                            "rare": card_info[1] or "未知",
                            "country": card_info[2] or "未知",
                            "image_base64": image_to_base64(img_path),
                            "deleted_tags": []
                        }
                    })
            # 已完成但拿不到卡, 视为无可领取招募
            return JSONResponse({"code": 1, "msg": "当前没有进行中的招募", "data": None})
        
        now_ts = int(time.time())
        if row[0] == "招募中":
            if now_ts < (row[1] or 0):
                end_time = datetime.fromtimestamp(row[1]).strftime("%m-%d %H:%M")
                return JSONResponse({
                    "code": 1,
                    "msg": f"招募将于{end_time}完成，请耐心等待",
                    "data": None
                })
            else:
                recruit_tags = json.loads(row[2])
                card, deleted_tags = await filter_cards_by_tags(recruit_tags)
                
                if card and row[3]:
                    await db.execute(
                        "UPDATE RecruitStatus SET status = '已完成', result_card_id = ? WHERE id = ?",
                        (card[0], row[3])
                    )
                    await db.commit()
                    await db.execute(
                        "INSERT INTO UserCards(user_id,card_id,count) VALUES(?, ?, 1) "
                        "ON CONFLICT(user_id,card_id) DO UPDATE SET count = count + 1",
                        (uid, card[0])
                    )
                    await db.commit()
                    await generate_tags(uid, user_name)
                    
                    img_path = IMAGE_DIR / f"{card[0]}.png"
                    img_base64 = image_to_base64(img_path)
                    
                    delete_info = []
                    if deleted_tags:
                        delete_info = [{"tag": k, "status": v} for k, v in deleted_tags.items()]
                    
                    return JSONResponse({
                        "code": 0,
                        "msg": "招募完成",
                        "data": {
                            "card_id": card[0],
                            "card_name": card[1],
                            "rare": card[4] if len(card) > 4 else "未知",
                            "country": card[3] if len(card) > 3 else "未知",
                            "image_base64": img_base64,
                            "deleted_tags": delete_info
                        }
                    })
                elif not card:
                    return JSONResponse({"code": 1, "msg": "未招募到卡牌，请稍后重试", "data": None})
    
    return JSONResponse({"code": 1, "msg": "状态异常", "data": None})

# API: 改名
@app.post("/kards/change_name")
async def api_change_name(request: Request):
    """修改用户昵称"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    new_name = data.get("name")
    if not new_name or not str(new_name).strip():
        return JSONResponse({"code": 1, "msg": "昵称不能为空", "data": None})
    
    new_name = str(new_name).strip()
    if len(new_name) > 20:
        return JSONResponse({"code": 1, "msg": "昵称过长，最多20个字符", "data": None})
    
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE Users SET qq_name = ? WHERE qq = ?", (new_name, uid))
        await db.commit()
    
    return JSONResponse({
        "code": 0,
        "msg": "改名成功",
        "data": {"name": new_name}
    })

# API: 开始招募
@app.post("/kards/start_recruit")
async def api_start_recruit(request: Request):
    """
    开始招募
    choices: 选择的词条，如 "ABC" 或 "A,B,C"（1-3个A-E）
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    choices_input = data.get("choices")
    if not choices_input:
        return JSONResponse({"code": 1, "msg": "请选择词条", "data": None})
    
    # 处理输入格式：支持 "ABC" 或 "A,B,C" 或 "A B C"
    choices_clean = str(choices_input).upper().replace(",", "").replace(" ", "")
    
    # 验证词条选择
    valid_choices = [c for c in choices_clean if c in "ABCDE"][:3]
    if not valid_choices:
        return JSONResponse({"code": 1, "msg": "词条选择无效，请选择A-E（1-3个）", "data": None})
    
    if len(valid_choices) > 3:
        return JSONResponse({"code": 1, "msg": "最多选择3个词条", "data": None})
    
    user_name = await get_user_name(None, uid)
    
    # 获取当前词条
    tags, used = await get_tags(uid, user_name)
    choices_map = {
        "A": tags[0],
        "B": tags[1],
        "C": tags[2],
        "D": tags[3],
        "E": tags[4]
    }
    
    # 检查高资
    tags_name = [item["name"] for item in tags]
    chosen_name = [choices_map[c]["name"] for c in valid_choices]
    if "高级资深卡牌(稀有)" in tags_name and "高级资深卡牌(稀有)" not in chosen_name:
        return JSONResponse({"code": 1, "msg": "高资不抽给我", "data": None})
    
    # 调用招募逻辑
    result = await start_recruit(uid, user_name, choices_map, choices_clean)
    
    # 解析结果
    if "不足" in result:
        return JSONResponse({"code": 1, "msg": result, "data": None})
    elif "正在进行" in result:
        return JSONResponse({"code": 1, "msg": result, "data": None})
    elif "请选择" in result:
        return JSONResponse({"code": 1, "msg": result, "data": None})
    else:
        # 成功开始招募
        # 计算完成时间
        duration = T_DEFAULT
        for c in valid_choices:
            tag_name = choices_map[c]["name"]
            if tag_name == "资深卡牌(少见)":
                duration = T_EXPERT
            if tag_name == "高级资深卡牌(稀有)":
                duration = T_HIGH_EXPERT
        
        finish_ts = int(time.time()) + duration * 60
        finish_time = datetime.fromtimestamp(finish_ts).strftime("%Y-%m-%d %H:%M:%S")
        
        return JSONResponse({
            "code": 0,
            "msg": result,
            "data": {
                "duration": duration,
                "finish_time": finish_time,
                "chosen_tags": chosen_name
            }
        })

# API: 查看招募详情
@app.post("/kards/recruit_detail")
async def api_recruit_detail(request: Request):
    """查看当前招募详情"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    
    uid = data.get("uid")
    if not await check_login(uid):
        return JSONResponse({"code": 401, "msg": "请登录", "data": None})
    
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('''
            SELECT status, start_ts, finish_ts, ticket_tags, result_card_id
            FROM RecruitStatus 
            WHERE user_id = ? 
            ORDER BY id DESC 
            LIMIT 1
        ''', (uid,))
        row = await cur.fetchone()
        
        if not row:
            return JSONResponse({
                "code": 0,
                "msg": "无招募记录",
                "data": {"status": "无招募"}
            })
        
        status, start_ts, finish_ts, ticket_tags, result_card_id = row
        now_ts = int(time.time())
        
        recruit_info = {
            "status": status,
            "start_time": datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S") if start_ts else None,
            "finish_time": datetime.fromtimestamp(finish_ts).strftime("%Y-%m-%d %H:%M:%S") if finish_ts else None,
            "chosen_tags": [t["name"] for t in json.loads(ticket_tags)] if ticket_tags else [],
            "result_card_id": result_card_id
        }
        
        if status == "招募中":
            if now_ts < (finish_ts or 0):
                remain = ceil((finish_ts - now_ts) / 60)
                recruit_info["remain_minutes"] = remain
                recruit_info["remain_text"] = f"约{remain}分钟后完成"
            else:
                recruit_info["remain_text"] = "等待领取"
                recruit_info["can_receive"] = True
        
        if status == "已完成" and result_card_id:
            cur = await db.execute("SELECT CardName, Rare, Country FROM Cards WHERE PicID = ?", (result_card_id,))
            card_info = await cur.fetchone()
            if card_info:
                recruit_info["result_card_name"] = card_info[0]
                recruit_info["result_card_rare"] = card_info[1]
                recruit_info["result_card_country"] = card_info[2]
                img_path = IMAGE_DIR / f"{result_card_id}.png"
                recruit_info["result_card_image"] = image_to_base64(img_path)
    
    return JSONResponse({
        "code": 0,
        "msg": "success",
        "data": recruit_info
    })

try:
    from fastapi.middleware.cors import CORSMiddleware
    # 幂等: NoneBot 重载时可能再次执行此模块, 避免重复 add_middleware 抛错
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

try:
    driver = get_driver()
    @driver.on_startup
    async def _startup():
        await init_user_db()
except Exception:
    asyncio.get_event_loop().create_task(init_user_db())



# ===== 校验指令监听 (2026-06-29 新机制) =====
# 群内用户发送 "校验kards账号{token}" 时, 调 serve.py /api/verify_token/complete 标记 token 已绑定
# 触发前端轮询拿到 qq, 自动绑定
import re as _re_verify

_FRONTEND_COMPLETE_URL = FRONTEND_PUSH_URL.rsplit("/", 1)[0] + "/verify_token/complete"
_KARDS_VERIFY_RE = _re_verify.compile(r"^校验kards账号(.+)$")
verify_cmd = on_message(priority=200, block=False)

@verify_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    raw = ""
    try:
        raw = event.get_plaintext().strip()
    except Exception:
        return
    m = _KARDS_VERIFY_RE.match(raw)
    if not m:
        return
    token = m.group(1).strip()
    qq = str(event.user_id)
    if not token:
        return
    try:
        import aiohttp
        print('[kards][verify] -> %s qq=%s token=%s' % (_FRONTEND_COMPLETE_URL, qq, token), file=sys.stderr)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
            async with session.post(_FRONTEND_COMPLETE_URL, json={
                "token": token,
                "qq": qq,
                # 不传 purpose: serve.py 会同时为所有 purpose 标完成 (kards + diy 一次绑俩)
            }) as resp:
                text = await resp.text()
                print('[kards][verify] <- %s status=%s body=%s' % (_FRONTEND_COMPLETE_URL, resp.status, text[:200]), file=sys.stderr)
    except Exception as e:
        print('[kards][verify][ERR] %s failed: %s' % (_FRONTEND_COMPLETE_URL, e), file=sys.stderr)
        return
    # 静默: 成功也不在群里发消息, 失败/无匹配/异常都直接 return
    # 前端轮询会从 serve.py 拿到 qq 并自动绑定, 用户体验上不依赖 bot 群内回复
