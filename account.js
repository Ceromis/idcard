/**
 * 账号模块 (前端 localStorage 版)
 * - key "kards_accounts" : Array<{ email, pwdHash, uid?, isAdmin, createdAt }>
 * - key "kards_session"  : { email } 当前登录态
 * - key "kards_settings" : { apiBase } 全局 API 接入 IP 设置
 */
(function (global) {
  const ACC_KEY = "kards_accounts";
  const SESS_KEY = "kards_session";
  const SET_KEY = "kards_settings";
  const DEFAULT_API = "http://110.42.63.235:8080";
  const DEFAULT_DIY_API = "http://192.168.10.100:8090";

  // 纯 JS SHA-256 fallback: 当 crypto.subtle 不可用时使用
  // 适用场景: 非 https / 非 localhost 访问, 浏览器不暴露 Web Crypto
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
    // 优先用 Web Crypto (快, async), 不可用时 (非 https / 非 localhost) 退回纯 JS fallback
    if (typeof crypto !== "undefined" && crypto.subtle && crypto.subtle.digest) {
      try {
        const buf = new TextEncoder().encode(text);
        const hash = await crypto.subtle.digest("SHA-256", buf);
        return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, "0")).join("");
      } catch (e) {
        // 某些环境下 subtle.digest 抛错 (e.g. NotSupportedError), 继续走 fallback
      }
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
  function saveSettings(s) { localStorage.setItem(SET_KEY, JSON.stringify(s)); }

  function getSession() {
    try { return JSON.parse(localStorage.getItem(SESS_KEY) || "null"); }
    catch { return null; }
  }
  function setSession(s) {
    if (s) localStorage.setItem(SESS_KEY, JSON.stringify(s));
    else localStorage.removeItem(SESS_KEY);
  }

  // ===== 邮箱验证码 (占位) =====
  // 真实接入时: 在后端用 163 SMTP (smtp.163.com:465 SSL, 授权码登录) 发邮件;
  // 前端只调 /account/send_code 拿到成功/失败状态.
  // 现阶段: 本地生成 6 位数字, console.log + 弹窗显示.
  const PENDING_CODE_KEY = "kards_pending_code";
  const EMAIL_CODE_TTL_MS = 10 * 60 * 1000;  // 邮箱验证码 10 分钟过期
  const PASSWORD_MIN_LEN = 6;

  // ===== 绑定验证码 (NoneBot 群内指令生成, 由后端 POST 到前端 /api/bind_code) =====
  // 两个 key 互不干扰, 前端轮询 GET /api/bind_code 拉取最新码
  const PENDING_KARDS_BIND_KEY = "kards_pending_bind_code";
  const PENDING_DIY_BIND_KEY = "diy_pending_bind_code";
  const BIND_CODE_TTL_MS = 10 * 60 * 1000;
  const BIND_POLL_INTERVAL_MS = 2000;
  const BIND_POLL_TIMEOUT_MS = 60000;

  function generateCode() { return String(Math.floor(100000 + Math.random() * 900000)); }
  async function sendCode(email) {
    const normalized = String(email || "").trim().toLowerCase();
    const code = generateCode();
    localStorage.setItem(PENDING_CODE_KEY, JSON.stringify({ email: normalized, code, ts: Date.now() }));
    console.log("[email-verify] code for", normalized, "=", code);
    return code; // 真实接入后,这里只返回 true/false
  }
  function verifyCode(email, code) {
    try {
      const p = JSON.parse(localStorage.getItem(PENDING_CODE_KEY) || "null");
      if (!p || p.email !== email) return false;
      if (Date.now() - p.ts > EMAIL_CODE_TTL_MS) return false;
      return p.code === String(code).trim();
    } catch { return false; }
  }

  // ===== 账号 CRUD =====
  async function register({ email, pwd, code }) {
    email = String(email || "").trim().toLowerCase();
    if (!email || !pwd) throw new Error("邮箱或密码不能为空");
    if (!verifyCode(email, code)) throw new Error("验证码错误或已过期");
    const list = loadAccounts();
    if (list.some(a => a.email === email)) throw new Error("该邮箱已注册");
    const acc = { email, pwdHash: await sha256(pwd), uid: "", isAdmin: false, createdAt: Date.now() };
    list.push(acc);
    saveAccounts(list);
    return acc;
  }
  async function login({ email, pwd }) {
    email = String(email || "").trim().toLowerCase();
    let acc = loadAccounts().find(a => String(a.email || "").toLowerCase() === email);
    if (!acc) {
      // 防御: localStorage 可能在 init 之前就被清空/损坏, 触发一次 seed 再查一次
      await ensureSeed();
      acc = loadAccounts().find(a => String(a.email || "").toLowerCase() === email);
    }
    if (!acc) throw new Error("账号不存在");
    if (acc.pwdHash !== await sha256(pwd)) throw new Error("密码错误");
    setSession({ email: acc.email });
    return acc;
  }
  function logout() { setSession(null); }
  function getCurrentAccount() {
    const s = getSession();
    if (!s) return null;
    return loadAccounts().find(a => a.email === s.email) || null;
  }
  function bindUid(uid) {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    cur.uid = String(uid || "").trim();
    const list = loadAccounts();
    const i = list.findIndex(a => a.email === cur.email);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  function bindDiyQQ(qq) {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    cur.diyQQ = String(qq || "").trim();
    const list = loadAccounts();
    const i = list.findIndex(a => a.email === cur.email);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  function getDiyQQ() {
    const cur = getCurrentAccount();
    return cur ? (cur.diyQQ || "") : null;
  }
  // ===== 绑定验证码: 拉取/校验 =====
  function _frontendBase() {
    // 前端同源地址, 由 serve.py 提供 /api/bind_code
    return (location.origin && location.origin !== "null") ? location.origin : "";
  }
  function _saveBindCode(key, qq, code, ts) {
    try { localStorage.setItem(key, JSON.stringify({ qq: String(qq), code: String(code), ts: Number(ts) || Date.now() })); }
    catch {}
  }
  function _loadBindCode(key) {
    try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; }
  }
  function _clearBindCode(key) {
    try { localStorage.removeItem(key); } catch {}
  }
  async function pollBindCode(purpose, qq, opts) {
    const timeoutMs = (opts && opts.timeoutMs) || BIND_POLL_TIMEOUT_MS;
    const onFound = (opts && opts.onFound) || function() {};
    const onTick = (opts && opts.onTick) || function() {};
    const onTimeout = (opts && opts.onTimeout) || function() {};
    const base = _frontendBase();
    if (!base) { onTimeout("无法连接前端服务"); return; }
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      onTick();
      try {
        const resp = await fetch(base + "/api/bind_code?qq=" + encodeURIComponent(qq) + "&purpose=" + encodeURIComponent(purpose), { cache: "no-store" });
        const data = await resp.json().catch(() => null);
        if (data && data.code === 0 && data.data && data.data.code) {
          const item = data.data;
          _saveBindCode(
            purpose === "kards_uid_bind" ? PENDING_KARDS_BIND_KEY : PENDING_DIY_BIND_KEY,
            item.qq, item.code, item.ts
          );
          onFound(item);
          return item;
        }
      } catch (e) {
        // 忽略单次失败, 继续轮询
      }
      await new Promise(r => setTimeout(r, BIND_POLL_INTERVAL_MS));
    }
    onTimeout("超时未收到验证码, 请重试");
    return null;
  }
  function verifyKardsCode(uid, code) {
    if (!uid || !code) return false;
    const p = _loadBindCode(PENDING_KARDS_BIND_KEY);
    if (!p) return false;
    if (String(p.code) !== String(code).trim()) return false;
    if (String(p.qq) !== String(uid).trim()) return false;
    if (Date.now() - Number(p.ts) > BIND_CODE_TTL_MS) { _clearBindCode(PENDING_KARDS_BIND_KEY); return false; }
    _clearBindCode(PENDING_KARDS_BIND_KEY);
    return true;
  }
  function verifyDiyCode(qq, code) {
    if (!qq || !code) return false;
    const p = _loadBindCode(PENDING_DIY_BIND_KEY);
    if (!p) return false;
    if (String(p.code) !== String(code).trim()) return false;
    if (String(p.qq) !== String(qq).trim()) return false;
    if (Date.now() - Number(p.ts) > BIND_CODE_TTL_MS) { _clearBindCode(PENDING_DIY_BIND_KEY); return false; }
    _clearBindCode(PENDING_DIY_BIND_KEY);
    return true;
  }
  // 远程校验: 当本地 localStorage 没有缓存 (前端从未轮询到码) 时, 让 serve.py 直接在内存里查
  // 解决 "bot 与前端不在同一内网 / KARDS_FRONTEND_URL 没配对" 场景下手动填码的卡死
  async function verifyBindCodeRemote(purpose, qq, code) {
    const base = _frontendBase();
    if (!base) return { ok: false, msg: "无法连接前端服务" };
    try {
      const resp = await fetch(base + "/api/bind_code/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ qq: String(qq), code: String(code), purpose }),
        cache: "no-store"
      });
      const data = await resp.json().catch(() => null);
      if (data && data.code === 0) return { ok: true };
      return { ok: false, msg: (data && data.msg) ? data.msg : "验证码无效或已过期" };
    } catch (e) {
      return { ok: false, msg: "网络错误: " + (e && e.message || e) };
    }
  }
  function getKardsPendingCode() { return _loadBindCode(PENDING_KARDS_BIND_KEY); }
  function getDiyPendingCode() { return _loadBindCode(PENDING_DIY_BIND_KEY); }

  async function changePassword(oldPwd, newPwd) {
    const cur = getCurrentAccount();
    if (!cur) throw new Error("请先登录");
    if (typeof newPwd !== "string" || newPwd.length < PASSWORD_MIN_LEN) {
      throw new Error("新密码长度至少 " + PASSWORD_MIN_LEN + " 位");
    }
    if (cur.pwdHash !== await sha256(oldPwd)) throw new Error("原密码错误");
    cur.pwdHash = await sha256(newPwd);
    const list = loadAccounts();
    const i = list.findIndex(a => a.email === cur.email);
    if (i >= 0) { list[i] = cur; saveAccounts(list); }
    return cur;
  }
  function listAll() { return loadAccounts(); }
  function deleteAccount(email) {
    const list = loadAccounts().filter(a => a.email !== email);
    saveAccounts(list);
    if (getSession() && getSession().email === email) setSession(null);
  }

  // ===== 初始化: 预置管理员 =====
  // 用内存级 _seeded 标志位短路: 避免每次 init / login 自愈都跑 loadAccounts + sha256 + 写盘
  let _seeded = false;
  async function ensureSeed() {
    if (_seeded) return;
    const list = loadAccounts();
    let dirty = false;
    if (!list.some(a => String(a.email || "").toLowerCase() === "admin@kards.local")) {
      list.push({
        email: "admin@kards.local",
        pwdHash: await sha256("admin123"),
        uid: "",
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
    sha256, ensureSeed, sendCode, verifyCode,
    register, login, logout, getCurrentAccount, bindUid, bindDiyQQ, getDiyQQ, changePassword,
    listAll, deleteAccount,
    loadSettings, saveSettings,
    pollBindCode, verifyKardsCode, verifyDiyCode, verifyBindCodeRemote, getKardsPendingCode, getDiyPendingCode,
    DEFAULT_API, DEFAULT_DIY_API
  };
})(window);

