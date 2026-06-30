/**
 * 账号模块 (前端 localStorage 版)
 * - key "kards_accounts" : Array<{ username, pwdHash, email?, uid?, diyQQ?, isAdmin, createdAt }>
 *   - username: 必填, 唯一, 登录用
 *   - email:    选填, 绑定的邮箱 (SMTP 验证后)
 *   - uid:      公开招募 UID (= 实际 QQ 号)
 *   - diyQQ:    限定寻访 QQ
 * - key "kards_session"  : { username } 当前登录态
 * - key "kards_settings" : { apiBase, diyApiBase } 全局 API 接入 IP 设置
 * - key "kards_pending_email_code" : { email, code, ts, purpose }
 */
(function (global) {
  const ACC_KEY = "kards_accounts";
  const SESS_KEY = "kards_session";
  const SET_KEY = "kards_settings";
  const PENDING_CODE_KEY = "kards_pending_email_code";
  const DEFAULT_API = "http://110.42.63.235:8080";
  const DEFAULT_DIY_API = "http://192.168.10.100:8090";

  // ===== SHA-256 =====
  function _sha256Pure(text) {
    const H = [0x6A09E667|0, 0xBB67AE85|0, 0x3C6EF372|0, 0xA54FF53A|0,
               0x510E527F|0, 0x9B05688C|0, 0x1F83D9AB|0, 0x5BE0CD19|0];
    const K = [
      0x428A2F98,0x71374491,0xB5C0FBCF,0xE9B5DBA5,0x3956C25B,0x59F111F1,0x923F82A4,0xAB1C5ED5,
      0xD807AA98,0x12835B01,0x243185BE,0x550C7DC3,0x72BE5D74,0x80DEB1FE,0x9BDC06A7,0xC19BF174,
      0xE49B69C1,0xEFBE4786,0x0FC19DC6,0x240CA1CC,0x2DE92C6F,0x4A7484AA,0x5CB0A9DC,0x76F988DA,
      0x983E5152,0xA831C66D,0xB00327C8,0xBF597FC7,0xC6E00BF3,0xD5A79147,0x06CA6351,0x14292967,
      0x27B70A85,0x2E1B2138,0x4D2C6DFC,0x53380D13,0x650A7354,0x766A0ABB,0x81C2C92E,0x92722C85,
      0xA2BFE8A1,0xA81A664B,0xC24B8B70,0xC76C51A3,0xD192E819,0xD6990624,0xF40E3585,0x106AA070,
      0x19A4C116,0x1E376C08,0x2748774C,0x34B0BCB5,0x391C0CB3,0x4ED8AA4A,0x5B9CCA4F,0x682E6FF3,
      0x748F82EE,0x78A5636F,0x84C87814,0x8CC70208,0x90BEFFFA,0xA4506CEB,0xBEF9A3F7,0xC67178F2];
    const utf8 = unescape(encodeURIComponent(text));
    const bytes = [];
    for (let i = 0; i < utf8.length; i++) bytes.push(utf8.charCodeAt(i));
    const bitLen = bytes.length * 8;
    bytes.push(0x80);
    while (bytes.length % 64 !== 56) bytes.push(0);
    const hi = Math.floor(bitLen / 0x100000000);
    const lo = bitLen >>> 0;
    for (let i = 7; i >= 0; i--) {
      if (i >= 4) bytes.push((hi >>> ((i - 4) * 8)) & 0xFF);
      else bytes.push((lo >>> (i * 8)) & 0xFF);
    }
    const W = new Array(64);
    for (let chunk = 0; chunk < bytes.length; chunk += 64) {
      for (let i = 0; i < 16; i++) {
        W[i] = (bytes[chunk + i*4] << 24) | (bytes[chunk + i*4 + 1] << 16) |
               (bytes[chunk + i*4 + 2] << 8) | bytes[chunk + i*4 + 3];
        W[i] = W[i] | 0;
      }
      for (let i = 16; i < 64; i++) {
        const s0 = (((W[i-15] >>> 7) | (W[i-15] << 25)) ^ ((W[i-15] >>> 18) | (W[i-15] << 14)) ^ (W[i-15] >>> 3)) | 0;
        const s1 = (((W[i-2] >>> 17) | (W[i-2] << 15)) ^ ((W[i-2] >>> 19) | (W[i-2] << 13)) ^ (W[i-2] >>> 10)) | 0;
        W[i] = (W[i-16] + s0 + W[i-7] + s1) | 0;
      }
      let [a,b,c,d,e,f,g,h] = H;
      for (let i = 0; i < 64; i++) {
        const S1 = (((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7))) | 0;
        const ch = ((e & f) ^ ((~e) & g)) | 0;
        const t1 = (h + S1 + ch + K[i] + W[i]) | 0;
        const S0 = (((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10))) | 0;
        const mj = ((a & b) ^ (a & c) ^ (b & c)) | 0;
        const t2 = (S0 + mj) | 0;
        h = g; g = f;
        f = e; e = (d + t1) | 0;
        d = c; c = b;
        b = a; a = (t1 + t2) | 0;
      }
      H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0;
      H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0;
      H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0;
      H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
    }
    let out = "";
    for (let i = 0; i < 8; i++) {
      out += ((H[i] >>> 28) & 0xF).toString(16) +
             ((H[i] >>> 24) & 0xF).toString(16) +
             ((H[i] >>> 20) & 0xF).toString(16) +
             ((H[i] >>> 16) & 0xF).toString(16) +
             ((H[i] >>> 12) & 0xF).toString(16) +
             ((H[i] >>> 8) & 0xF).toString(16) +
             ((H[i] >>> 4) & 0xF).toString(16) +
             (H[i] & 0xF).toString(16);
    }
    return out;
  }

  async function sha256(text) {
    if (typeof crypto !== "undefined" && crypto.subtle && crypto.subtle.digest) {
      try {
        const buf = new TextEncoder().encode(text);
        const hash = await crypto.subtle.digest("SHA-256", buf);
        return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, "0")).join("");
      } catch (e) {}
    }
    return _sha256Pure(text);
  }

  function loadAccounts() {
    try { return JSON.parse(localStorage.getItem(ACC_KEY) || "[]"); }
    catch { return []; }
  }
  function saveAccounts(arr) { localStorage.setItem(ACC_KEY, JSON.stringify(arr)); }

  function loadSettings() {
    try {
      const s = JSON.parse(localStorage.getItem(SET_KEY) || "null");
      return s || { apiBase: DEFAULT_API, diyApiBase: DEFAULT_DIY_API };
    } catch { return { apiBase: DEFAULT_API, diyApiBase: DEFAULT_DIY_API }; }
  }
  function saveSettings(s) {
    const cur = loadSettings();
    const next = Object.assign({}, cur, s || {});
    localStorage.setItem(SET_KEY, JSON.stringify(next));
    return next;
  }

  function setSession(s) {
    if (s) localStorage.setItem(SESS_KEY, JSON.stringify(s));
    else localStorage.removeItem(SESS_KEY);
  }
  function getSession() {
    try { return JSON.parse(localStorage.getItem(SESS_KEY) || "null"); }
    catch { return null; }
  }

  // ===== 校验码常量 =====
  const EMAIL_CODE_TTL_MS = 10 * 60 * 1000;  // 邮箱验证码 10 分钟过期
  const PASSWORD_MIN_LEN = 6;
  const USERNAME_MIN_LEN = 3;
  const USERNAME_MAX_LEN = 20;
  const USERNAME_RE = /^[A-Za-z0-9_]{3,20}$/;
  const BIND_POLL_INTERVAL_MS = 2000;
  const BIND_POLL_TIMEOUT_MS = 600000; // 10 分钟, 与后端 BIND_CODE_TTL 一致

  function generateCode(len) {
    len = len || 6;
    let s = "";
    for (let i = 0; i < len; i++) s += Math.floor(Math.random() * 10);
    return s;
  }
  // 校验码: 3 位 + 2 位 + 1 位, 形如 "182*+", 包含字母+数字+符号
  function generateVerifyToken() {
    const digits = generateCode(3);          // 3 位数字
    const mid = generateCode(2);             // 2 位数字
    const sym = String.fromCharCode(33 + Math.floor(Math.random() * 15)); // 1 位符号
    return digits + "*" + mid + sym;
  }

  // ===== 邮箱验证码 (选填) =====
  // SMTP 真发送由 serve.py 在后端做, 前端只发请求, dev 模式(未配 SMTP)时由后端返回 devCode
  async function sendCode(email, purpose) {
    const normalized = String(email || "").trim().toLowerCase();
    if (!normalized) throw new Error("邮箱不能为空");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) throw new Error("邮箱格式不正确");
    const code = generateCode(6);
    localStorage.setItem(PENDING_CODE_KEY, JSON.stringify({ email: normalized, code, ts: Date.now(), purpose: purpose || "bind" }));
    // 同时通知后端, 让 serve.py 走 SMTP 发邮件; 后端不可达时本地存 dev code 也能让前端流程跑通
    const base = _frontendBase();
    let devCode = null;
    if (base) {
      try {
        const resp = await fetch(base + "/api/email_code", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: normalized, code, purpose: purpose || "bind" }),
          cache: "no-store"
        });
        const data = await resp.json().catch(() => null);
        if (data && data.code === 0) {
          if (data.data && data.data.devCode) devCode = data.data.devCode;
        } else {
          // 后端失败: 走 dev fallback, 让验证码本地可见
          devCode = code;
        }
      } catch (e) {
        devCode = code;
      }
    } else {
      devCode = code;
    }
    return { ok: true, devCode: devCode };
  }
  function verifyCode(email, code, purpose) {
    try {
      const p = JSON.parse(localStorage.getItem(PENDING_CODE_KEY) || "null");
      if (!p) return false;
      if (p.email !== String(email || "").trim().toLowerCase()) return false;
      if (purpose && p.purpose && p.purpose !== purpose) return false;
      if (Date.now() - p.ts > EMAIL_CODE_TTL_MS) return false;
      return p.code === String(code).trim();
    } catch { return false; }
  }

  // ===== 账号 CRUD =====
  function _normalizeUsername(s) {
    return String(s || "").trim();
  }
  async function register({ username, pwd }) {
    username = _normalizeUsername(username);
    if (!username) throw new Error("用户名不能为空");
    if (!USERNAME_RE.test(username)) throw new Error("用户名仅支持 3-20 位字母/数字/下划线");
    if (!pwd || String(pwd).length < PASSWORD_MIN_LEN) throw new Error("密码长度至少 " + PASSWORD_MIN_LEN + " 位");
    const list = loadAccounts();
    if (list.some(a => a.username && a.username.toLowerCase() === username.toLowerCase())) {
      throw new Error("该用户名已被注册");
    }
    const acc = { username, pwdHash: await sha256(pwd), email: "", uid: "", diyQQ: "", isAdmin: false, createdAt: Date.now() };
    list.push(acc);
    saveAccounts(list);
    return acc;
  }
  async function login({ id, pwd }) {
    const key = String(id || "").trim();
    if (!key || !pwd) throw new Error("请输入账号和密码");
    let acc = loadAccounts().find(a => (a.username && a.username.toLowerCase() === key.toLowerCase()) || (a.email && a.email === key.toLowerCase()));
    if (!acc) {
      await ensureSeed();
      acc = loadAccounts().find(a => (a.username && a.username.toLowerCase() === key.toLowerCase()) || (a.email && a.email === key.toLowerCase()));
    }
    if (!acc) throw new Error("账号不存在");
    if (acc.pwdHash !== await sha256(pwd)) throw new Error("密码错误");
    setSession({ username: acc.username });
    return acc;
  }
  function logout() { setSession(null); }
  function getCurrentAccount() {
    const s = getSession();
    if (!s) return null;
    return loadAccounts().find(a => a.username === s.username) || null;
  }
  function bindUid(uid) {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    cur.uid = String(uid || "").trim();
    if (!cur.uid) throw new Error("UID 不能为空");
    const list = loadAccounts();
    const i = list.findIndex(a => a.username === cur.username);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  function bindDiyQQ(qq) {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    cur.diyQQ = String(qq || "").trim();
    if (!cur.diyQQ) throw new Error("QQ 不能为空");
    const list = loadAccounts();
    const i = list.findIndex(a => a.username === cur.username);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  function bindEmail(email, code) {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    const normalized = String(email || "").trim().toLowerCase();
    if (!normalized) throw new Error("邮箱不能为空");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) throw new Error("邮箱格式不正确");
    if (!verifyCode(normalized, code, "bind")) throw new Error("验证码错误或已过期");
    // 邮箱唯一性: 别的账号已用这个邮箱, 则不允许
    const list = loadAccounts();
    if (list.some(a => a.username !== cur.username && a.email === normalized)) {
      throw new Error("该邮箱已被其他账号绑定");
    }
    cur.email = normalized;
    const i = list.findIndex(a => a.username === cur.username);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  function unbindEmail() {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    cur.email = "";
    const list = loadAccounts();
    const i = list.findIndex(a => a.username === cur.username);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  function getDiyQQ() {
    const cur = getCurrentAccount();
    return cur ? (cur.diyQQ || "") : null;
  }
  function unbindUid() {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    if (!cur.uid) throw new Error("未绑定公开招募 UID, 无需解绑");
    cur.uid = "";
    const list = loadAccounts();
    const i = list.findIndex(a => a.username === cur.username);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  function unbindDiyQQ() {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    if (!cur.diyQQ) throw new Error("未绑定限定寻访 QQ, 无需解绑");
    cur.diyQQ = "";
    const list = loadAccounts();
    const i = list.findIndex(a => a.username === cur.username);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  async function changePassword(oldPwd, newPwd) {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    if (typeof newPwd !== "string" || newPwd.length < PASSWORD_MIN_LEN) {
      throw new Error("新密码长度至少 " + PASSWORD_MIN_LEN + " 位");
    }
    if (cur.pwdHash !== await sha256(oldPwd)) throw new Error("原密码错误");
    cur.pwdHash = await sha256(newPwd);
    const list = loadAccounts();
    const i = list.findIndex(a => a.username === cur.username);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  function listAll() { return loadAccounts(); }
  function deleteAccount(username) {
    const list = loadAccounts().filter(a => a.username !== username);
    saveAccounts(list);
    if (getSession() && getSession().username === username) setSession(null);
  }

  // ===== 校验指令 (bot 监听群消息, 回调 serve.py 完成绑定) =====
  function _frontendBase() {
    return (location.origin && location.origin !== "null") ? location.origin : "";
  }
  // 申请一个 token: 调 serve.py /api/verify_token 预留位置, 拿到后端占位
  // serve.py 内部建一个 {token: {purpose, ts, qq:null}} 记录, 等 bot 回调
  async function requestVerifyToken(purpose) {
    const base = _frontendBase();
    if (!base) return null;
    try {
      const resp = await fetch(base + "/api/verify_token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ purpose }),
        cache: "no-store"
      });
      const data = await resp.json().catch(() => null);
      if (data && data.code === 0 && data.data && data.data.token) return data.data.token;
    } catch (e) {}
    return null;
  }
  // 把生成的 token 通知 serve.py 预占
  async function preallocVerifyToken(purpose, token) {
    const base = _frontendBase();
    if (!base) return false;
    try {
      const resp = await fetch(base + "/api/verify_token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ purpose, token }),
        cache: "no-store"
      });
      const data = await resp.json().catch(() => null);
      return !!(data && data.code === 0);
    } catch (e) { return false; }
  }
  // 轮询: 等 bot 把 token 标记为已完成, 并把 qq 写回
  async function pollVerifyToken(purpose, token, opts) {
    const timeoutMs = (opts && opts.timeoutMs) || BIND_POLL_TIMEOUT_MS;
    const onFound = (opts && opts.onFound) || function() {};
    const onTimeout = (opts && opts.onTimeout) || function() {};
    const base = _frontendBase();
    if (!base) { onTimeout("无法连接前端服务"); return; }
    // 先在后端预占这个 token
    await preallocVerifyToken(purpose, token);
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const resp = await fetch(base + "/api/verify_token?token=" + encodeURIComponent(token) + "&purpose=" + encodeURIComponent(purpose), { cache: "no-store" });
        const data = await resp.json().catch(() => null);
        if (data && data.code === 0 && data.data && data.data.qq) {
          onFound({ qq: data.data.qq, ts: data.data.ts });
          return;
        }
      } catch (e) {}
      await new Promise(r => setTimeout(r, BIND_POLL_INTERVAL_MS));
    }
    onTimeout("校验超时");
  }

  // ===== 初始化: 预置管理员 =====
  let _seeded = false;
  // 迁移老结构 (2026-06-29 之前): 账号以 email 作为唯一 key, username 字段不存在
  // 新结构: username 必填且唯一, email 降为可选绑定邮箱
  // 这里做向后兼容: 把老账号的 email 字段拆为 username (取 @ 之前) + 真实 email 字段 (空字符串)
  function _migrateAccounts(list) {
    let dirty = false;
    for (const a of list) {
      if (!a || typeof a !== "object") continue;
      if (a.username) continue; // 新结构, 跳过
      if (a.email) {
        const at = String(a.email).indexOf("@");
        a.username = at > 0 ? String(a.email).slice(0, at) : String(a.email);
        a.email = "";
        dirty = true;
      } else {
        a.username = "user_" + (a.createdAt || Date.now());
        dirty = true;
      }
      if (typeof a.diyQQ === "undefined") { a.diyQQ = ""; dirty = true; }
      if (typeof a.uid === "undefined") { a.uid = ""; dirty = true; }
    }
    return dirty;
  }

  async function ensureSeed() {
    if (_seeded) return;
    const list = loadAccounts();
    let dirty = _migrateAccounts(list);
    // 兼容老默认管理员账号 admin@kards.local: 迁移后 username 会变成 "admin"
    if (!list.some(a => a.username === "admin")) {
      list.push({
        username: "admin",
        pwdHash: await sha256("admin123"),
        email: "",
        uid: "",
        diyQQ: "",
        isAdmin: true,
        createdAt: Date.now()
      });
      dirty = true;
    }
    if (dirty) saveAccounts(list);
    if (!localStorage.getItem(SET_KEY)) saveSettings({ apiBase: DEFAULT_API, diyApiBase: DEFAULT_DIY_API });
    _seeded = true;
  }

  global.KardsAccount = {
    sha256, ensureSeed, sendCode, verifyCode, generateVerifyToken,
    register, login, logout, getCurrentAccount, bindUid, bindDiyQQ, bindEmail, unbindEmail, unbindUid, unbindDiyQQ, getDiyQQ, changePassword,
    listAll, deleteAccount,
    loadSettings, saveSettings,
    requestVerifyToken, preallocVerifyToken, pollVerifyToken,
    DEFAULT_API, DEFAULT_DIY_API,
    initPageNav: function(pageName) {
      var s = loadSettings();
      if (!s.theme || s.theme === "default") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", s.theme);
      if (s.navMode === "sidebar") document.body.setAttribute("data-nav", "sidebar");
      else document.body.removeAttribute("data-nav");
      var cur = getCurrentAccount();
      var whoEl = document.getElementById("who");
      if (whoEl) whoEl.textContent = cur ? cur.username + (cur.isAdmin ? " (管理员)" : "") : "未登录";
      document.querySelectorAll(".topbar-nav a").forEach(function(a) {
        a.classList.toggle("active", a.dataset.page === pageName);
      });
      document.querySelectorAll(".side-nav .slot").forEach(function(a) {
        a.classList.toggle("active", a.dataset.page === pageName);
      });
    }
  };
})(window);