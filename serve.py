#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KARDS 前端本地部署服务器
======================

启动一个简易 HTTP 静态服务器, 用于本地预览 4 个页面:
  - account.html    账号 (登录 / 注册 / 绑定)
  - recruit.html    公开招募 (需登录 + 绑 UID)
  - deck.html       卡组解析
  - settings.html   管理面板 (仅管理员)

新增端点 (2026-06-29 改造):
  - POST /api/email_code            前端调, 后端按 youxiang/youxiang.txt 走 SMTP 发邮件 (dev 模式直接回 devCode)
  - POST /api/verify_token          前端预占校验码 {token, purpose}; 不带 token 时由后端生成
  - GET  /api/verify_token          前端轮询, 等 bot 把 qq 写回
  - POST /api/verify_token/complete bot 回调, 标记 token 已绑定并写入 qq
  - POST /api/bind_code             (旧) 仍保留, 兼容旧版 bot
  - GET  /api/bind_code             (旧) 仍保留
  - POST /api/bind_code/verify      (旧) 仍保留

用法
----
    python serve.py                # 默认端口 8000
    python serve.py --port 8080    # 自定义端口
    python serve.py --host 0.0.0.0 # 允许局域网访问

打开浏览器访问:
    http://localhost:8000/account.html    入口页面 (推荐先打开这个)
"""
import argparse
import http.server
import json
import os
import random
import re
import smtplib
import socketserver
import string
import sys
import threading
import time
import urllib.parse
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from functools import partial

# 端口冲突时立即报错, 避免静默失败
socketserver.TCPServer.allow_reuse_address = True

# ===== 路径与存储 =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
YOUXIANG_TXT = os.path.join(BASE_DIR, "youxiang", "youxiang.txt")
BIND_CODES_FILE = os.path.join(DATA_DIR, "bind_codes.json")
BIND_CODES_LOCK = threading.Lock()

# 旧的按 qq|purpose 推送的验证码 (兼容旧版 bot)
PURPOSE_VALID = {"kards_uid_bind", "diy_qq_bind"}
BIND_CODE_TTL = 600
BIND_CACHE_GC_INTERVAL = 60

# 新的按 token|purpose 推送的校验指令 (2026-06-29 改造)
VERIFY_TOKENS_FILE = os.path.join(DATA_DIR, "verify_tokens.json")
VERIFY_TOKENS_LOCK = threading.Lock()
VERIFY_PURPOSE_VALID = {"kards_token_bind", "diy_token_bind"}
VERIFY_TOKEN_TTL = 600  # 校验码 10 分钟过期

# 内存缓存
BIND_CACHE = {}
VERIFY_CACHE = {}

def _load_json_file(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json_file(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _save_bind_codes(data):
    _save_json_file(BIND_CODES_FILE, data)


def _save_verify_tokens(data):
    _save_json_file(VERIFY_TOKENS_FILE, data)


def _gc_by_ts(data, ttl, keep_factor=6):
    now = time.time()
    out = {}
    for k, v in data.items():
        try:
            if now - float(v.get("ts", 0)) < ttl * keep_factor:
                out[k] = v
        except Exception:
            pass
    return out


# ===== SMTP 配置 (从 youxiang/youxiang.txt 加载) =====
SMTP_CFG = None
SMTP_CFG_LOCK = threading.Lock()
SMTP_CFG_MTIME = 0.0


def _load_smtp_config():
    """读取 youxiang/youxiang.txt, 返回 dict; 解析失败时返回 None (表示未启用)."""
    if not os.path.exists(YOUXIANG_TXT):
        return None
    try:
        with open(YOUXIANG_TXT, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            return None
        # 占位符滚木 = 视为未启用, 不尝试发送
        if not cfg.get("enabled"):
            return None
        required = ("host", "port", "user", "password", "from")
        for k in required:
            v = cfg.get(k)
            if v is None:
                return None
            if isinstance(v, str) and v.strip() == "滚木":
                return None
        if not cfg.get("port"):
            return None
        return cfg
    except Exception as e:
        print("[smtp] 加载 youxiang.txt 失败: " + str(e), file=sys.stderr)
        return None


def _get_smtp_config():
    """惰性 + mtime 失效: 文件变更后下次调用自动重读."""
    global SMTP_CFG, SMTP_CFG_MTIME
    with SMTP_CFG_LOCK:
        try:
            mtime = os.path.getmtime(YOUXIANG_TXT)
        except OSError:
            return SMTP_CFG
        if SMTP_CFG is None or mtime > SMTP_CFG_MTIME:
            SMTP_CFG = _load_smtp_config()
            SMTP_CFG_MTIME = mtime
            if SMTP_CFG:
                print("[smtp] 已加载配置: host=" + str(SMTP_CFG.get("host")) + " user=" + str(SMTP_CFG.get("user")), file=sys.stderr)
            else:
                print("[smtp] 未启用 (youxiang/youxiang.txt 中 enabled=false 或仍为占位符 滚木)", file=sys.stderr)
        return SMTP_CFG


def _render_template(tpl, mapping, default_subject_prefix="KARDS"):
    """简单模板: {key} 替换."""
    if not tpl:
        return ""
    out = tpl
    for k, v in mapping.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _send_email_smtp(cfg, to_addr, subject, body):
    """真实 SMTP 发送. 失败抛异常."""
    host = cfg["host"]
    port = int(cfg["port"])
    user = cfg["user"]
    password = cfg["password"]
    from_addr = cfg["from"]
    from_name = cfg.get("from_name") or user
    use_tls = bool(cfg.get("use_tls", True))

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr))
    msg["To"] = to_addr

    if use_tls:
        client = smtplib.SMTP_SSL(host, port, timeout=10)
    else:
        client = smtplib.SMTP(host, port, timeout=10)
        client.ehlo()
        if cfg.get("starttls", False):
            client.starttls()
            client.ehlo()
    try:
        client.login(user, password)
        client.sendmail(from_addr, [to_addr], msg.as_string())
    finally:
        try:
            client.quit()
        except Exception:
            pass


# ===== 校验码 token 生成 =====
def _generate_token():
    """3位数字*2位数字1位符号, 形如 '182*+'. 与前端 account.js generateVerifyToken 保持一致."""
    digits1 = "".join(random.choice(string.digits) for _ in range(3))
    digits2 = "".join(random.choice(string.digits) for _ in range(2))
    sym = random.choice("!@#$%^&*+=-?")
    return digits1 + "*" + digits2 + sym


# ===== 站点入口 =====
ENTRY_PAGES = [
    ("account.html",   "账号 (登录 / 注册 / 绑定)"),
    ("recruit.html",   "公开招募 (需先登录账号)"),
    ("deck.html",      "卡组解析"),
    ("diy.html",       "限定寻访 (需先登录账号)"),
    ("settings.html",  "管理面板 (仅管理员)"),
    ("search.html",    "搜索"),
]


class Handler(http.server.SimpleHTTPRequestHandler):
    """标准静态文件处理器 + 验证码推送/拉取 + 校验指令 + 邮件发送."""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js":  "application/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".css":  "text/css; charset=utf-8",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
    }

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status, "OK")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8")
            print("[read-json] len=" + str(length) + " raw=" + repr(raw[:200]), file=sys.stderr)
            return json.loads(raw)
        except Exception as e:
            print("[read-json] err: " + str(e), file=sys.stderr)
            return {}

    # ---------- 旧 bind_code 兼容 ----------
    def _handle_bind_code_post(self, data):
        qq = str(data.get("qq", "")).strip()
        code = str(data.get("code", "")).strip()
        purpose = str(data.get("purpose", "")).strip()
        ts = data.get("ts")
        if not qq or not code or purpose not in PURPOSE_VALID:
            self._send_json(400, {"code": 1, "msg": "参数错误"})
            return
        with BIND_CODES_LOCK:
            key = qq + "|" + purpose
            BIND_CACHE[key] = {"qq": qq, "code": code, "purpose": purpose, "ts": float(ts or time.time())}
            try:
                _save_bind_codes(BIND_CACHE)
            except Exception as e:
                print("[bind_code] 写盘失败: " + str(e), file=sys.stderr)
        self._send_json(200, {"code": 0, "msg": "ok"})

    def _handle_bind_code_get(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        qq = (qs.get("qq", [""])[0] or "").strip()
        purpose = (qs.get("purpose", [""])[0] or "").strip()
        if not qq or purpose not in PURPOSE_VALID:
            self._send_json(400, {"code": 1, "msg": "参数错误"})
            return
        with BIND_CODES_LOCK:
            key = qq + "|" + purpose
            item = BIND_CACHE.get(key)
        if not item:
            self._send_json(200, {"code": 1, "msg": "暂无新验证码"})
            return
        self._send_json(200, {"code": 0, "data": item})

    def _handle_bind_code_verify(self, data):
        qq = str(data.get("qq", "")).strip()
        code = str(data.get("code", "")).strip()
        purpose = str(data.get("purpose", "")).strip()
        if not qq or not code or purpose not in PURPOSE_VALID:
            self._send_json(400, {"code": 1, "msg": "参数错误"})
            return
        with BIND_CODES_LOCK:
            key = qq + "|" + purpose
            item = BIND_CACHE.get(key)
            if not item or str(item.get("code", "")) != code:
                self._send_json(200, {"code": 1, "msg": "验证码无效或已过期"})
                return
            BIND_CACHE.pop(key, None)
            try:
                _save_bind_codes(BIND_CACHE)
            except Exception:
                pass
        self._send_json(200, {"code": 0, "msg": "ok"})

    # ---------- 邮箱验证码 (新) ----------
    def _handle_email_code_post(self, data):
        email = str(data.get("email", "")).strip().lower()
        code = str(data.get("code", "")).strip()
        purpose = str(data.get("purpose", "bind")).strip() or "bind"
        if not email or not code or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            self._send_json(400, {"code": 1, "msg": "参数错误"})
            return
        cfg = _get_smtp_config()
        if not cfg:
            # dev 模式: 返回 devCode, 前端弹窗显示
            self._send_json(200, {"code": 0, "msg": "dev 模式", "data": {"devCode": code}})
            return
        # 真发送
        subject = _render_template(cfg.get("subject_bind") or "{prefix} 绑定验证码", {"prefix": cfg.get("subject_prefix") or "KARDS", "code": code})
        body = _render_template(cfg.get("bind_template") or "您的绑定验证码是 {code}, 10 分钟内有效.", {"code": code, "prefix": cfg.get("subject_prefix") or "KARDS"})
        try:
            _send_email_smtp(cfg, email, subject, body)
            self._send_json(200, {"code": 0, "msg": "ok", "data": {"sent": True}})
        except Exception as e:
            print("[smtp] 发送失败: " + str(e), file=sys.stderr)
            # 发送失败: 降级为 devCode, 让用户能继续走流程
            self._send_json(200, {"code": 0, "msg": "smtp 失败, 降级 dev", "data": {"devCode": code, "error": str(e)}})

    # ---------- 校验指令 (新) ----------
    def _handle_verify_token_post(self, data):
        purpose = str(data.get("purpose", "")).strip()
        if purpose not in VERIFY_PURPOSE_VALID:
            self._send_json(400, {"code": 1, "msg": "参数错误"})
            return
        token = str(data.get("token", "")).strip()
        with VERIFY_TOKENS_LOCK:
            if token:
                key = token + "|" + purpose
                if key not in VERIFY_CACHE:
                    VERIFY_CACHE[key] = {"token": token, "purpose": purpose, "ts": time.time(), "qq": None}
                    try:
                        _save_verify_tokens(VERIFY_CACHE)
                    except Exception as e:
                        print("[verify_token] 写盘失败: " + str(e), file=sys.stderr)
                self._send_json(200, {"code": 0, "msg": "ok", "data": {"token": token}})
                return
            # 后端生成
            for _ in range(10):
                candidate = _generate_token()
                key = candidate + "|" + purpose
                if key not in VERIFY_CACHE:
                    VERIFY_CACHE[key] = {"token": candidate, "purpose": purpose, "ts": time.time(), "qq": None}
                    try:
                        _save_verify_tokens(VERIFY_CACHE)
                    except Exception as e:
                        print("[verify_token] 写盘失败: " + str(e), file=sys.stderr)
                    self._send_json(200, {"code": 0, "msg": "ok", "data": {"token": candidate}})
                    return
            self._send_json(500, {"code": 1, "msg": "token 生成失败"})

    def _handle_verify_token_get(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        token = (qs.get("token", [""])[0] or "").strip()
        purpose = (qs.get("purpose", [""])[0] or "").strip()
        if not token or purpose not in VERIFY_PURPOSE_VALID:
            self._send_json(400, {"code": 1, "msg": "参数错误"})
            return
        with VERIFY_TOKENS_LOCK:
            key = token + "|" + purpose
            item = VERIFY_CACHE.get(key)
        if not item:
            self._send_json(200, {"code": 1, "msg": "token 无效或已过期"})
            return
        if not item.get("qq"):
            self._send_json(200, {"code": 1, "msg": "等待 bot 回调"})
            return
        self._send_json(200, {"code": 0, "data": {"qq": item.get("qq"), "ts": item.get("ts")}})

    def _handle_verify_token_complete(self, data):
        """bot 回调: 群内有人发送 校验kards账号{token} 时, bot 调这个端点.
        同一个 token 同时为所有 purpose 标记完成 (前提: 该 purpose 已被前端 prealloc 过).
        如果请求里指定了 purpose, 则只标那一个 (向后兼容, 不会误触其他 purpose)."""
        token = str(data.get("token", "")).strip()
        purpose = str(data.get("purpose", "")).strip()
        qq = str(data.get("qq", "")).strip()
        if not token or not qq:
            self._send_json(400, {"code": 1, "msg": "参数错误"})
            return
        if purpose and purpose not in VERIFY_PURPOSE_VALID:
            self._send_json(400, {"code": 1, "msg": "参数错误"})
            return
        # 决定要为哪些 purpose 标完成
        if purpose:
            target_purposes = [purpose]
        else:
            target_purposes = list(VERIFY_PURPOSE_VALID)
        completed = []
        with VERIFY_TOKENS_LOCK:
            for p in target_purposes:
                key = token + "|" + p
                item = VERIFY_CACHE.get(key)
                if not item:
                    continue
                if time.time() - float(item.get("ts", 0)) > VERIFY_TOKEN_TTL:
                    VERIFY_CACHE.pop(key, None)
                    continue
                # 同一个 qq 同时标到所有相关 purpose
                item["qq"] = qq
                item["completed_ts"] = time.time()
                completed.append(p)
            if completed:
                try:
                    _save_verify_tokens(VERIFY_CACHE)
                except Exception as e:
                    print("[verify_token] 写盘失败: " + str(e), file=sys.stderr)
        if not completed:
            self._send_json(200, {"code": 1, "msg": "token 无效或已过期 (任何 purpose 都未预占)"})
            return
        self._send_json(200, {"code": 0, "msg": "ok", "data": {"completed": completed}})



    # ---------- 聊天室 API ----------



    # ---------- 入口分发 ----------
    def do_POST(self):
        path = self.path.rstrip("/")
        if path == "/api/bind_code":
            return self._handle_bind_code_post(self._read_json())
        if path == "/api/bind_code/verify":
            return self._handle_bind_code_verify(self._read_json())
        if path == "/api/email_code":
            return self._handle_email_code_post(self._read_json())
        if path == "/api/verify_token":
            return self._handle_verify_token_post(self._read_json())
        if path == "/api/verify_token/complete":
            return self._handle_verify_token_complete(self._read_json())
        self.send_error(405, "Method Not Allowed")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.rstrip("/") == "/api/bind_code":
            return self._handle_bind_code_get(parsed)
        if parsed.path.rstrip("/") == "/api/verify_token":
            return self._handle_verify_token_get(parsed)
        if parsed.path == "/":
            self.path = "/account.html"
        return super().do_GET()

    def do_OPTIONS(self):
        # CORS 预检
        self.send_response(204, "OK")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def _gc_loop():
    """后台线程: 周期清理过期的 bind code / verify token, 避免内存无限增长."""
    while True:
        try:
            time.sleep(BIND_CACHE_GC_INTERVAL)
            with BIND_CODES_LOCK:
                if BIND_CACHE:
                    cleaned = _gc_by_ts(BIND_CACHE, BIND_CODE_TTL)
                    if len(cleaned) != len(BIND_CACHE):
                        BIND_CACHE.clear()
                        BIND_CACHE.update(cleaned)
                        _save_bind_codes(BIND_CACHE)
            with VERIFY_TOKENS_LOCK:
                if VERIFY_CACHE:
                    cleaned = _gc_by_ts(VERIFY_CACHE, VERIFY_TOKEN_TTL)
                    if len(cleaned) != len(VERIFY_CACHE):
                        VERIFY_CACHE.clear()
                        VERIFY_CACHE.update(cleaned)
                        _save_verify_tokens(VERIFY_CACHE)
        except Exception:
            pass


def parse_args():
    p = argparse.ArgumentParser(
        description="KARDS 前端本地部署服务器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--port", "-p", type=int, default=8000, help="监听端口 (默认 8000)")
    p.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1, 局域网请用 0.0.0.0)")
    p.add_argument("--open", "-o", action="store_true", help="启动后自动在默认浏览器打开入口页")
    return p.parse_args()


def check_port_free(host, port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError as e:
            print("[错误] 端口 " + str(port) + " 已被占用: " + str(e), file=sys.stderr)
            print("提示: 用 --port 指定其他端口, 或先结束占用该端口的进程.", file=sys.stderr)
            sys.exit(1)


def main():
    args = parse_args()

    os.chdir(BASE_DIR)

    missing = [name for name, _ in ENTRY_PAGES if not os.path.exists(name)]
    if missing:
        print("[警告] 以下页面文件缺失: " + ", ".join(missing), file=sys.stderr)

    check_port_free(args.host, args.port)

    # 启动时把缓存一次性加载进内存, 后台线程负责周期 GC + 落盘
    with BIND_CODES_LOCK:
        BIND_CACHE.update(_load_json_file(BIND_CODES_FILE, {}))
    with VERIFY_TOKENS_LOCK:
        VERIFY_CACHE.update(_load_json_file(VERIFY_TOKENS_FILE, {}))
    gc_thread = threading.Thread(target=_gc_loop, name="bind-cache-gc", daemon=True)
    gc_thread.start()

    # 触发一次 SMTP 配置加载 (含 enabled/log)
    try:
        _get_smtp_config()
    except Exception as e:
        print("[smtp] 初始化失败: " + str(e), file=sys.stderr)

    base = "http://" + args.host + ":" + str(args.port)
    print("=" * 60)
    print("  KARDS 前端本地部署服务器")
    print("=" * 60)
    print("  工作目录: " + os.getcwd())
    print("  监听地址: " + base)
    print("-" * 60)
    print("  入口页面:")
    for name, desc in ENTRY_PAGES:
        marker = "  " if os.path.exists(name) else "x "
        print("  " + marker + " " + base + "/" + name.ljust(14) + "  " + desc)
    print("-" * 60)
    print("  预置管理员: admin / admin123")
    print("  按 Ctrl+C 停止服务器")
    print("=" * 60)
    print("  验证码接收端点 (旧, 兼容): POST /api/bind_code (供 NoneBot 插件推送)")
    print("  校验指令端点 (新):  POST/GET /api/verify_token")
    print("  SMTP 邮箱: 读取 youxiang/youxiang.txt (enabled=false 时回 devCode)")
    print("  如果 bot 与前端不在同一台机器, 请用 --host 0.0.0.0 允许外部连接")
    print("  并在 bot 机器上设置 KARDS_FRONTEND_URL=http://<本机IP>:" + str(args.port))

    if args.open:
        import webbrowser
        webbrowser.open(base + "/account.html")

    handler = partial(Handler, directory=os.getcwd())
    with socketserver.ThreadingTCPServer((args.host, args.port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务器已停止")


if __name__ == "__main__":
    main()