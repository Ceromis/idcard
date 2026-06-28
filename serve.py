#!/usr/bin/env python3
"""
KARDS 前端本地部署服务器
======================

启动一个简易 HTTP 静态服务器, 用于本地预览 4 个页面:
  - account.html    账号 (登录 / 注册 / 绑定 UID)
  - recruit.html    公开招募 (需登录 + 绑 UID)
  - deck.html       卡组解析
  - settings.html   管理面板 (仅管理员)

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
import socketserver
import sys
import threading
import time
import urllib.parse
from functools import partial

# 端口冲突时立即报错, 避免静默失败
socketserver.TCPServer.allow_reuse_address = True

# ===== 验证码接收端点 (NoneBot 插件 POST 到这里, 前端 GET 拉取) =====
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
BIND_CODES_FILE = os.path.join(DATA_DIR, "bind_codes.json")
BIND_CODES_LOCK = threading.Lock()

PURPOSE_VALID = {"kards_uid_bind", "diy_qq_bind"}
BIND_CODE_TTL = 600  # 与后端一致, 10 分钟过期
BIND_CACHE_GC_INTERVAL = 60  # 后台 GC 周期 (秒)


# 内存缓存, 启动时一次性加载; 写时双写 (内存 + 文件), 避免每请求都序列化 JSON
BIND_CACHE = {}


def _load_bind_codes():
    """启动时调用一次, 把磁盘内容载入内存."""
    if not os.path.exists(BIND_CODES_FILE):
        return {}
    try:
        with open(BIND_CODES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_bind_codes(data):
    tmp = BIND_CODES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, BIND_CODES_FILE)


def _gc_bind_codes(data):
    now = time.time()
    out = {}
    for k, v in data.items():
        try:
            if now - float(v.get("ts", 0)) < BIND_CODE_TTL * 6:
                out[k] = v
        except Exception:
            pass
    return out


def _gc_loop():
    """后台线程: 周期清理过期的 bind code, 避免内存无限增长."""
    while True:
        try:
            time.sleep(BIND_CACHE_GC_INTERVAL)
            with BIND_CODES_LOCK:
                if not BIND_CACHE:
                    continue
                cleaned = _gc_bind_codes(BIND_CACHE)
                if len(cleaned) != len(BIND_CACHE):
                    BIND_CACHE.clear()
                    BIND_CACHE.update(cleaned)
                    _save_bind_codes(BIND_CACHE)
        except Exception:
            # 后台线程静默, 不影响主服务
            pass


# 站点入口
ENTRY_PAGES = [
    ("account.html",   "账号 (登录 / 注册 / 绑定 UID)"),
    ("recruit.html",   "公开招募 (需先登录账号)"),
    ("deck.html",      "卡组解析"),
    ("settings.html",  "管理面板 (仅管理员)"),
]


class Handler(http.server.SimpleHTTPRequestHandler):
    """标准静态文件处理器 + /api/bind_code 验证码推送/拉取."""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js":  "application/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".css":  "text/css; charset=utf-8",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
    }

    # 静默常见访问日志, 避免刷屏
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
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_POST(self):
        if self.path.rstrip("/") == "/api/bind_code":
            data = self._read_json()
            qq = str(data.get("qq", "")).strip()
            code = str(data.get("code", "")).strip()
            purpose = str(data.get("purpose", "")).strip()
            ts = data.get("ts")
            if not qq or not code or purpose not in PURPOSE_VALID:
                self._send_json(400, {"code": 1, "msg": "参数错误"})
                return
            try:
                ts = int(ts) if ts else int(time.time())
            except Exception:
                ts = int(time.time())
            with BIND_CODES_LOCK:
                # 直接更新内存缓存, 后台线程会周期 GC + 落盘
                key = f"{qq}|{purpose}"
                existing = BIND_CACHE.get(key)
                if existing and float(existing.get("ts", 0)) > ts:
                    self._send_json(200, {"code": 0, "msg": "忽略旧码"})
                    return
                BIND_CACHE[key] = {"qq": qq, "code": code, "purpose": purpose, "ts": ts}
                # 写: 同步落盘 (best-effort, 失败不影响主流程)
                try:
                    _save_bind_codes(BIND_CACHE)
                except Exception:
                    pass
                # 诊断: 把最近一次收到的原始 payload 写到 data/last_bind_code.json
                # 便于排查 "bot 到底有没有推过来" + "推过来的字段对不对"
                try:
                    diag = {
                        "received_at": time.time(),
                        "remote": self.client_address[0] if self.client_address else None,
                        "key": key,
                        "qq": qq, "code": code, "purpose": purpose, "ts": ts
                    }
                    with open(os.path.join(DATA_DIR, "last_bind_code.json"), "w", encoding="utf-8") as _f:
                        json.dump(diag, _f, ensure_ascii=False)
                except Exception:
                    pass
                # 调试日志: 写一行到 stderr, 用户从终端能直接看到
                sys.stderr.write("[bind_code] received from %s key=%s code=%s purpose=%s\n" % (
                    self.client_address[0] if self.client_address else "?", key, code, purpose))
            self._send_json(200, {"code": 0, "msg": "ok"})
            return
        if self.path.rstrip("/") == "/api/bind_code/verify":
            # 手动填码路径: 前端拿用户输入的码直接让后端校验
            # 适用场景: 前端轮询从未拿到过码 (bot 与前端不在同一内网 / KARDS_FRONTEND_URL 没配对)
            data = self._read_json()
            qq = str(data.get("qq", "")).strip()
            code = str(data.get("code", "")).strip()
            purpose = str(data.get("purpose", "")).strip()
            if not qq or not code or purpose not in PURPOSE_VALID:
                self._send_json(400, {"code": 1, "msg": "参数错误"})
                return
            with BIND_CODES_LOCK:
                key = f"{qq}|{purpose}"
                item = BIND_CACHE.get(key)
                if not item or str(item.get("code", "")) != code:
                    self._send_json(200, {"code": 1, "msg": "验证码无效或已过期"})
                    return
                # 验证成功: 原子地删掉这条 (防重放/重复绑定), 同样落盘
                BIND_CACHE.pop(key, None)
                try:
                    _save_bind_codes(BIND_CACHE)
                except Exception:
                    pass
            self._send_json(200, {"code": 0, "msg": "ok"})
            return
        # 其他路径不接受 POST, 避免无谓穿透到静态处理器
        self.send_error(405, "Method Not Allowed")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.rstrip("/") == "/api/bind_code":
            qs = urllib.parse.parse_qs(parsed.query)
            qq = (qs.get("qq", [""])[0] or "").strip()
            purpose = (qs.get("purpose", [""])[0] or "").strip()
            if not qq or purpose not in PURPOSE_VALID:
                self._send_json(400, {"code": 1, "msg": "参数错误"})
                return
            with BIND_CODES_LOCK:
                # 命中即返回, 无需每请求 GC
                key = f"{qq}|{purpose}"
                item = BIND_CACHE.get(key)
            if not item:
                self._send_json(200, {"code": 1, "msg": "暂无新验证码"})
                return
            self._send_json(200, {"code": 0, "data": item})
            return
        if parsed.path == "/":
            self.path = "/account.html"
        return super().do_GET()


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
    """先尝试绑定, 失败则给出友好提示."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError as e:
            print(f"[错误] 端口 {port} 已被占用: {e}", file=sys.stderr)
            print("提示: 用 --port 指定其他端口, 或先结束占用该端口的进程.", file=sys.stderr)
            sys.exit(1)


def main():
    args = parse_args()

    # 切到脚本所在目录, 保证相对路径生效
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # 校验关键文件存在
    missing = [name for name, _ in ENTRY_PAGES if not os.path.exists(name)]
    if missing:
        print(f"[警告] 以下页面文件缺失: {', '.join(missing)}", file=sys.stderr)

    check_port_free(args.host, args.port)

    # 启动时把 bind codes 一次性加载进内存, 后台线程负责周期 GC + 落盘
    with BIND_CODES_LOCK:
        BIND_CACHE.update(_load_bind_codes())
    gc_thread = threading.Thread(target=_gc_loop, name="bind-cache-gc", daemon=True)
    gc_thread.start()

    base = f"http://{args.host}:{args.port}"
    print("=" * 60)
    print("  KARDS 前端本地部署服务器")
    print("=" * 60)
    print(f"  工作目录: {os.getcwd()}")
    print(f"  监听地址: {base}")
    print("-" * 60)
    print("  入口页面:")
    for name, desc in ENTRY_PAGES:
        marker = "  " if os.path.exists(name) else "x "
        print(f"  {marker} {base}/{name:14s}  {desc}")
    print("-" * 60)
    print("  预置管理员: admin@kards.local / admin123")
    print("  按 Ctrl+C 停止服务器")
    print("=" * 60)
    print("  验证码接收端点: POST /api/bind_code (供 NoneBot 插件推送)")
    print("  如果 bot 与前端不在同一台机器, 请用 --host 0.0.0.0 允许外部连接")
    print("  并在 bot 机器上设置 KARDS_FRONTEND_URL=http://<本机IP>:%d" % args.port)

    if args.open:
        import webbrowser
        webbrowser.open(f"{base}/account.html")

    # 用 partial 把 (directory, port) 绑进 handler, 避免在子线程里访问 args
    handler = partial(Handler, directory=os.getcwd())
    with socketserver.ThreadingTCPServer((args.host, args.port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务器已停止")


if __name__ == "__main__":
    main()
