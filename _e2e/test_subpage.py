"""
子分页 E2E 测试: 我的收藏 + 赠送 + 抽屉 + 响应式 + 门控
"""
from playwright.sync_api import sync_playwright
import json, time, os

PORT = 8765
BASE = "http://127.0.0.1:" + str(PORT)
SHOT_DIR = r"C:\开发\_e2e\shots"
os.makedirs(SHOT_DIR, exist_ok=True)

RED_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="

INIT = {
    "kards_accounts": [{
        "username": "admin",
        "pwdHash": "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
        "email": "", "uid": "123456", "diyQQ": "",
        "organization": "T", "isAdmin": True, "createdAt": 1,
    }],
    "kards_session": {"username": "admin"},
    "kards_settings": {"apiBase": "http://127.0.0.1:" + str(PORT), "diyApiBase": "http://127.0.0.1:8090"},
}

# mock 状态
state = {
    "collection": [
        {"card_id": 1, "card_name": "Spitfire", "count": 3, "rare": "普通", "country": "英国", "cost": 3, "attack": 0, "defence": 0, "image_base64": RED_PNG},
        {"card_id": 2, "card_name": "T-34", "count": 1, "rare": "特殊", "country": "苏联", "cost": 4, "attack": 0, "defence": 0, "image_base64": RED_PNG},
        {"card_id": 3, "card_name": "M4 谢尔曼", "count": 2, "rare": "限定", "country": "美国", "cost": 5, "attack": 0, "defence": 0, "image_base64": RED_PNG},
    ],
    "trades_receiver": [
        {"trade_id": 101, "time": "2026-06-25 14:30:00", "from_uid": "999", "to_uid": "123456", "from_name": "小李", "to_name": "我", "role": "receiver",
         "card_info": {"card_id": 4, "card_name": "曼哈顿计划", "rare": "衍生", "country": "美国", "cost": 0, "attack": 0, "defence": 0, "image_base64": RED_PNG}},
    ],
    "trades_sender": [
        {"trade_id": 202, "time": "2026-06-26 10:00:00", "from_uid": "123456", "to_uid": "888", "from_name": "我", "to_name": "老王", "role": "sender",
         "card_info": {"card_id": 5, "card_name": "虎式坦克", "rare": "普通", "country": "德国", "cost": 6, "attack": 0, "defence": 0, "image_base64": RED_PNG}},
    ],
    "recruit": {"status": "无招募"},
}

# 路由调用计数
calls = {"user_cards": 0, "trade_list": 0, "give_trade": 0, "handle_trade": 0}


def make_route_user_cards(route):
    calls["user_cards"] += 1
    body = json.dumps({"code": 0, "data": {"cards": state["collection"]}}, ensure_ascii=False).encode("utf-8")
    route.fulfill(status=200, content_type="application/json; charset=utf-8", body=body)


def make_route_trade_list(route):
    calls["trade_list"] += 1
    role_filter = route.request.post_data_json if route.request.post_data else None
    # \u8fd4\u56de\u4e24\u4e2a role
    body = json.dumps({"code": 0, "data": {"trades": state["trades_receiver"] + state["trades_sender"]}}, ensure_ascii=False).encode("utf-8")
    route.fulfill(status=200, content_type="application/json; charset=utf-8", body=body)


def make_route_give_trade(route):
    calls["give_trade"] += 1
    data = route.request.post_data_json or {}
    target = data.get("target_uid", "")
    # \u6a21\u62df: target="fail" \u8fd4\u5931\u8d25
    if target == "fail":
        body = json.dumps({"code": 1, "msg": "目标用户不存在", "data": None}, ensure_ascii=False).encode("utf-8")
    else:
        body = json.dumps({"code": 0, "msg": "赠送请求已发送", "data": {"trade_id": 999, "target_uid": target, "card_name": data.get("card_name", "")}}, ensure_ascii=False).encode("utf-8")
    route.fulfill(status=200, content_type="application/json; charset=utf-8", body=body)


def make_route_handle_trade(route):
    calls["handle_trade"] += 1
    data = route.request.post_data_json or {}
    body = json.dumps({"code": 0, "msg": "操作成功", "data": None}, ensure_ascii=False).encode("utf-8")
    route.fulfill(status=200, content_type="application/json; charset=utf-8", body=body)


def make_route_recruit_detail(route):
    body = json.dumps({"code": 0, "data": state["recruit"]}, ensure_ascii=False).encode("utf-8")
    route.fulfill(status=200, content_type="application/json; charset=utf-8", body=body)


def make_route_user_info(route):
    body = json.dumps({"code": 0, "data": {"tickets": 3, "tags": ["美国", "苏联", "低花费"], "refresh_limit": 3, "refresh_times": 0}}, ensure_ascii=False).encode("utf-8")
    route.fulfill(status=200, content_type="application/json; charset=utf-8", body=body)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.add_init_script("""
            const init = %s;
            for (const k in init) { localStorage.setItem(k, JSON.stringify(init[k])); }
        """ % json.dumps(INIT))

        def handler(route):
            url = route.request.url
            if "/kards/user_cards" in url: return make_route_user_cards(route)
            if "/kards/trade_list" in url: return make_route_trade_list(route)
            if "/kards/give_trade" in url: return make_route_give_trade(route)
            if "/kards/handle_trade" in url: return make_route_handle_trade(route)
            if "/kards/recruit_detail" in url: return make_route_recruit_detail(route)
            if "/kards/user_info" in url: return make_route_user_info(route)
            route.continue_()
        page.route("**/*", handler)

        page.goto(BASE + "/recruit.html", wait_until="networkidle")
        time.sleep(0.6)

        # 1. \u5b50\u5206\u9875\u521d\u59cb\u663e\u793a\u4e3a\u201c\u6211\u7684\u6536\u85cf\u201d
        page.click('#subNav .sub-tab[data-sub="collection"]'); time.sleep(0.5); assert page.locator("#subpanel").is_visible(), "subpanel not visible"
        assert page.locator("#subNav .sub-tab.active").text_content().strip() == "\u6211\u7684\u6536\u85cf", "default tab wrong"
        # 2. \u6536\u85cf\u52a0\u8f7d
        page.wait_for_selector(".my-card", timeout=5000)
        n_cards = page.locator(".my-card").count()
        assert n_cards == 3, f"expected 3 cards, got {n_cards}"
        page.screenshot(path=SHOT_DIR + "/01_collection.png", full_page=True)
        # \u603b\u5f20\u6570 = 3+1+2 = 6
        count_text = page.locator("#collectionCount").text_content().strip()
        assert count_text == "6", f"expected count=6, got {count_text}"
        print("[1,2] collection loaded, 3 cards, total 6 ok")

        # 3. \u70b9\u51fb\u7b2c\u4e00\u5f20\u5361 -> \u62bd\u5c49\u6ed1\u5165
        page.locator(".my-card").first.click()
        time.sleep(0.4)
        assert "open" in (page.locator("#cardDetailDrawer").get_attribute("class") or ""), "drawer not open"
        assert page.locator("#drawerName").text_content() == "Spitfire"
        assert page.locator("#drawerCount").text_content() == "3"
        assert page.locator("#drawerRare").text_content() == "\u666e\u901a"
        page.screenshot(path=SHOT_DIR + "/03_drawer.png", full_page=True)
        print("[3] drawer slid in, fields ok")

        # 4. \u70b9\u201c\u8d60\u9001\u201d -> \u8f93\u5165\u6846\u5c55\u5f00
        page.click("#btnGiveToggle")
        time.sleep(0.2)
        assert page.locator("#drawerGiveForm").is_visible(), "give form not shown"
        page.screenshot(path=SHOT_DIR + "/04_give_form.png", full_page=True)
        print("[4] give form shown")

        # 5. \u8d60\u9001\u5931\u8d25 (\u76ee\u6807=fail)
        page.fill("#giveTargetUid", "fail")
        page.click("#btnGiveConfirm")
        time.sleep(0.5)
        assert "err" in (page.locator("#giveMsg").get_attribute("class") or ""), "should be err"
        assert "\u76ee\u6807\u7528\u6237\u4e0d\u5b58\u5728" in page.locator("#giveMsg").text_content()
        page.screenshot(path=SHOT_DIR + "/05_give_fail.png", full_page=True)
        print("[5] give failure shown in giveMsg")

        # 6. \u8d60\u9001\u6210\u529f
        page.fill("#giveTargetUid", "888")
        page.click("#btnGiveConfirm")
        time.sleep(0.5)
        # \u62bd\u5c49\u5173\u95ed, toast
        assert "open" not in (page.locator("#cardDetailDrawer").get_attribute("class") or ""), "drawer should be closed"
        assert calls["give_trade"] == 2
        page.screenshot(path=SHOT_DIR + "/06_give_ok.png", full_page=True)
        print("[6] give success, drawer closed, give_trade called 2x")

        # 7. \u5173\u95ed\u62bd\u5c49
        page.locator(".my-card").nth(1).click()
        time.sleep(0.3)
        assert "open" in (page.locator("#cardDetailDrawer").get_attribute("class") or "")
        page.click("#drawerClose")
        time.sleep(0.3)
        assert "open" not in (page.locator("#cardDetailDrawer").get_attribute("class") or "")
        print("[7] drawer close ok")

        # 8. \u5207\u5230\u8d60\u9001 tab
        page.click('[data-sub="trade"]')
        time.sleep(0.5)
        assert page.locator("#tradeList").is_visible()
        # \u9ed8\u8ba4\u63a5\u6536\u65b9, 1 \u6761
        n_recv = page.locator("#tradeList .trade-row").count()
        assert n_recv == 1, f"expected 1 receiver trade, got {n_recv}"
        first = page.locator("#tradeList .trade-row").first
        assert "\u5c0f\u674e" in first.text_content()
        assert "999" in first.text_content()
        assert "\u66fc\u54c8\u987f\u8ba1\u5212" in first.text_content()
        assert "\u884d\u751f" in first.text_content()
        # \u63a5\u53d7/\u62d2\u7edd\u6309\u94ae
        assert first.locator('[data-action="accept"]').count() == 1
        assert first.locator('[data-action="reject"]').count() == 1
        page.screenshot(path=SHOT_DIR + "/08_trade_receiver.png", full_page=True)
        print("[8] trade receiver tab: 1 row, accept/reject buttons ok")

        # 9. \u5207\u5230\u53d1\u8d77\u65b9
        page.click('[data-trade-role="sender"]')
        time.sleep(0.5)
        n_send = page.locator("#tradeList .trade-row").count()
        assert n_send == 1, f"expected 1 sender trade, got {n_send}"
        first = page.locator("#tradeList .trade-row").first
        assert "\u8001\u738b" in first.text_content()
        assert first.locator('[data-action="cancel"]').count() == 1
        page.screenshot(path=SHOT_DIR + "/09_trade_sender.png", full_page=True)
        print("[9] trade sender tab: 1 row, cancel button ok")

        # 10. \u70b9\u53d1\u8d77\u65b9\u201c\u53d6\u6d88\u201d -> handle_trade \u8c03\u7528
        calls["handle_trade"] = 0
        first.locator('[data-action="cancel"]').click()
        time.sleep(0.4)
        assert calls["handle_trade"] == 1
        # \u5217\u8868\u7a7a
        assert page.locator("#tradeList .empty").count() == 1
        print("[10] sender cancel removed the row")

        # 11. \u54cd\u5e94\u5f0f: 900px \u5c3a\u5bf8
        page.set_viewport_size({"width": 900, "height": 800})
        time.sleep(0.3)
        # \u54cd\u5e94\u5f0f: 900px \u4e0b sub-nav \u4ecd\u53ef\u89c1, subpanel (\u4ec5\u5728 collection/trade tab) \u4ecd\u53ef\u89c1
        subnav_disp = page.evaluate("getComputedStyle(document.getElementById('subNav')).display")
        assert subnav_disp != "none", f"subNav should be visible at 900px, got {subnav_disp}"
        page.screenshot(path=SHOT_DIR + "/11_responsive_900.png", full_page=True)
        print("[11] responsive: subNav visible at 900px")

        # 12. \u95e8\u63a7: \u672a\u767b\u5f55\u65f6\u5b50\u5206\u9875\u4e0d\u663e\u793a
        page.set_viewport_size({"width": 1400, "height": 900})
        # 清空 session: 调 logout(), 等 _gateObserver 1s tick
        page.evaluate("KardsAccount.logout();")
        time.sleep(1.3)
        # \u672a\u767b\u5f55, \u4e3b\u9762\u677f\u88ab\u9501, subpanel \u4ecd\u53ef\u80fd\u521d\u59cb\u4e3a display:none
        # \u4f46\u91cd\u8f7d\u540e UID \u4e3a\u7a7a, _showSubpanelIfReady \u4e0d\u4f1a\u8c03
        subpanel_disp2 = page.evaluate("document.getElementById('subpanel').style.display")
        assert subpanel_disp2 == "none", f"subpanel should be display:none when not logged in, got '{subpanel_disp2}'"
        page.screenshot(path=SHOT_DIR + "/12_gated.png", full_page=True)
        print("[12] gate: subpanel hidden when not logged in")

        print("\n=== ALL 12 SUBPAGE TESTS PASSED ===")
        browser.close()


if __name__ == "__main__":
    main()