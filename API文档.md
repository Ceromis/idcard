# NoneBot 插件 API 文档

## 目录

- [公开招募插件 (kards)](#公开招募插件-kards)
  - [1. 获取用户信息](#1-获取用户信息)
  - [2. 刷新词条](#2-刷新词条)
  - [3. 开始招募](#3-开始招募)
  - [4. 查看招募详情](#4-查看招募详情)
  - [5. 领取招募结果](#5-领取招募结果)
  - [6. 查询卡牌收藏](#6-查询卡牌收藏)
  - [7. 获取赠送列表](#7-获取赠送列表)
  - [8. 处理赠送](#8-处理赠送)
  - [9. 赠送卡牌](#9-赠送卡牌)
  - [10. 改名](#10-改名)

- [限定寻访插件 (diy)](#限定寻访插件-diy)
  - [1. 随机获取DIY卡牌](#1-随机获取diy卡牌)
  - [2. 随机获取联动卡牌](#2-随机获取联动卡牌)
  - [3. 评价卡牌](#3-评价卡牌)
  - [4. 投稿卡牌](#4-投稿卡牌)
  - [5. 查询卡牌详情](#5-查询卡牌详情)
  - [6. 查询用户全部DIY卡牌](#6-查询用户全部diy卡牌)

---

## 公开招募插件 (kards)

### 通用说明

- 所有API均为 **POST** 请求
- 需要传入 `uid` 参数（用户QQ号）
- 未传或用户不存在返回 `{"code": 401, "msg": "请登录", "data": null}`
- 图片使用 **BASE64** 编码

### 响应格式

```json
{
    "code": 0,      // 0=成功, 1=业务错误, 401=未登录
    "msg": "success",
    "data": {}      // 业务数据
}
```

---

### 1. 获取用户信息

**POST** `/kards/user_info`

获取用户当前词条、刷新次数、招募状态、保底进度。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |

**请求示例：**

```json
{
    "uid": "123456789"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "uid": "123456789",
        "tickets": 3,
        "refresh_times": 1,
        "refresh_limit": 3,
        "tags": ["美国", "苏联", "高行动花费", "低花费", "世纪大战"],
        "recruit_status": "寻找中，约25分钟后完成",
        "is_recruit_finished": false,
        "african_progress": 45,
        "african_limit": 70
    }
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| tickets | 剩余招聘许可数 |
| refresh_times | 今日已用刷新次数 |
| refresh_limit | 每日刷新上限 |
| tags | 当前词条列表 |
| recruit_status | 招募状态描述 |
| is_recruit_finished | 招募是否已完成 |
| african_progress | 保底进度（已抽次数） |
| african_limit | 保底所需次数 |

---

### 2. 刷新词条

**POST** `/kards/refresh_tags`

刷新用户的招募词条。

**请求示例：**

```json
{
    "uid": "123456789"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "刷新成功",
    "data": {
        "tags": ["精英", "德国", "苏联", "高花费", "特殊"],
        "refresh_used": 2,
        "refresh_limit": 3
    }
}
```

---

### 3. 查询卡牌收藏

**POST** `/kards/user_cards`

查询用户拥有的卡牌，包含卡牌图片和张数。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |
| rare | string | 否 | 筛选稀有度：精英/特殊/限定/普通/金卡/银卡/铜卡/铁卡 |

**请求示例：**

```json
{
    "uid": "123456789",
    "rare": "精英"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "cards": [
            {
                "card_id": 156,
                "card_name": "Panzer IV",
                "count": 2,
                "rare": "精英",
                "country": "德国",
                "cost": 5,
                "attack": 4,
                "defence": 3,
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
            }
        ]
    }
}
```

---

### 3. 开始招募

**POST** `/kards/start_recruit`

选择词条进行公开招募。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |
| choices | string | 是 | 选择的词条，如 "ABC" 或 "A,B,C"（1-3个A-E） |

**词条说明：**

| 字母 | 对应词条 |
|------|----------|
| A | 第1个词条 |
| B | 第2个词条 |
| C | 第3个词条 |
| D | 第4个词条 |
| E | 第5个词条 |

**特殊词条影响：**

- `资深卡牌(少见)`：招募时间延长至60分钟
- `高级资深卡牌(稀有)`：招募时间延长至120分钟
- 出现高资时必须选择，否则拒绝招募

**请求示例：**

```json
{
    "uid": "123456789",
    "choices": "ABC"
}
```

**成功响应：**

```json
{
    "code": 0,
    "msg": "开始公开招募，请等待30分钟。",
    "data": {
        "duration": 30,
        "finish_time": "2026-06-27 15:30:00",
        "chosen_tags": ["美国", "苏联", "精英"]
    }
}
```

**错误响应示例：**

```json
{
    "code": 1,
    "msg": "你的招聘许可不足。",
    "data": null
}
```

```json
{
    "code": 1,
    "msg": "您已有招募正在进行,请稍等。",
    "data": null
}
```

```json
{
    "code": 1,
    "msg": "高资不抽给我",
    "data": null
}
```

---

### 4. 查看招募详情

**POST** `/kards/recruit_detail`

查看当前招募的详细状态，包括剩余时间、选择的词条、招募结果等。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |

**请求示例：**

```json
{
    "uid": "123456789"
}
```

**招募中响应：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "status": "招募中",
        "start_time": "2026-06-27 15:00:00",
        "finish_time": "2026-06-27 15:30:00",
        "chosen_tags": ["美国", "苏联", "精英"],
        "remain_minutes": 25,
        "remain_text": "约25分钟后完成"
    }
}
```

**等待领取响应：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "status": "招募中",
        "start_time": "2026-06-27 15:00:00",
        "finish_time": "2026-06-27 15:30:00",
        "chosen_tags": ["美国", "苏联", "精英"],
        "remain_text": "等待领取",
        "can_receive": true
    }
}
```

**无招募记录响应：**

```json
{
    "code": 0,
    "msg": "无招募记录",
    "data": {
        "status": "无招募"
    }
}
```

---

### 5. 领取招募结果

**POST** `/kards/get_recruit_result`

领取招募完成的卡牌并刷新词条。

**请求示例：**

```json
{
    "uid": "123456789"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "招募完成",
    "data": {
        "card_id": 89,
        "card_name": "Spitfire",
        "rare": "特殊",
        "country": "英国",
        "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
        "deleted_tags": [
            {"tag": "美国", "status": "被划去"}
        ]
    }
}
```

---

### 6. 查询卡牌收藏

**POST** `/kards/user_cards`

查询用户拥有的卡牌，包含卡牌图片和张数。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |
| rare | string | 否 | 筛选稀有度：精英/特殊/限定/普通/金卡/银卡/铜卡/铁卡 |

**请求示例：**

```json
{
    "uid": "123456789",
    "rare": "精英"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "cards": [
            {
                "card_id": 156,
                "card_name": "Panzer IV",
                "count": 2,
                "rare": "精英",
                "country": "德国",
                "cost": 5,
                "attack": 4,
                "defence": 3,
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
            }
        ]
    }
}
```

---

### 7. 获取赠送列表

**POST** `/kards/trade_list`

获取用户的赠送列表，包含卡牌详细信息和图片。

**请求示例：**

```json
{
    "uid": "123456789"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "trades": [
            {
                "trade_id": 15,
                "time": "2026-06-25 14:30:00",
                "from_uid": "123456789",
                "to_uid": "987654321",
                "from_name": "玩家A",
                "to_name": "玩家B",
                "card_info": {
                    "card_id": 156,
                    "card_name": "Panzer IV",
                    "rare": "精英",
                    "country": "德国",
                    "cost": 5,
                    "attack": 4,
                    "defence": 3,
                    "image_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
                },
                "role": "发起方",
                "status": "待回应"
            }
        ]
    }
}
```

**role字段说明：**

- `发起方`：当前用户是赠送发起者（可取消）
- `接收方`：当前用户是赠送接收者（可接受/拒绝）

---

### 8. 处理赠送

**POST** `/kards/handle_trade`

处理赠送请求（接受/拒绝/取消）。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |
| trade_id | int | 是 | 赠送ID |
| action | string | 是 | 操作：accept/reject/cancel |

**权限说明：**

- `accept`/`reject`：仅接收方可操作
- `cancel`：仅发起方可操作

**接受赠送示例：**

```json
{
    "uid": "987654321",
    "trade_id": 15,
    "action": "accept"
}
```

**拒绝赠送示例：**

```json
{
    "uid": "987654321",
    "trade_id": 15,
    "action": "reject"
}
```

**取消赠送示例：**

```json
{
    "uid": "123456789",
    "trade_id": 15,
    "action": "cancel"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "赠送15已接收"
}
```

---

### 9. 赠送卡牌

**POST** `/kards/give_trade`

赠送卡牌给其他用户。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 赠送方QQ号 |
| target_uid | string | 是 | 接收方QQ号 |
| card_name | string | 是 | 卡牌名称 |

**请求示例：**

```json
{
    "uid": "123456789",
    "target_uid": "987654321",
    "card_name": "Panzer IV"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "赠送请求已发送",
    "data": {
        "trade_id": 15,
        "target_uid": "987654321",
        "card_name": "PANZER IV"
    }
}
```

---

### 10. 改名

**POST** `/kards/change_name`

修改用户昵称。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |
| name | string | 是 | 新昵称（最多20字符） |

**请求示例：**

```json
{
    "uid": "123456789",
    "name": "新昵称"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "改名成功",
    "data": {
        "name": "新昵称"
    }
}
```

---

## 限定寻访插件 (diy)

### 通用说明

- 支持 GET 和 POST 请求
- 图片使用 **BASE64** 编码
- POST 请求需要传入 `uid` 参数

---

### 1. 随机获取DIY卡牌

**GET** `/diy/random`

随机获取一张已审核通过的DIY卡牌。

**响应示例：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "card_id": 15,
        "author": "玩家A",
        "submitted_at": "2026-06-25 14:30:00",
        "likes": 12,
        "dislikes": 2,
        "candies": 5,
        "image_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
}
```

---

### 2. 随机获取联动卡牌

**GET** `/diy/random_special`

随机获取一张联动寻访区的DIY卡牌（非二战/自创国家/官卡改卡/二次元/其他）。

**响应示例：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "card_id": 20,
        "author": "匿名用户",
        "submitted_at": "2026-06-24 10:00:00",
        "likes": 8,
        "dislikes": 1,
        "candies": 3,
        "image_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
}
```

---

### 3. 评价卡牌

**POST** `/diy/react`

评价DIY卡牌。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |
| card_id | int | 是 | 卡牌ID |
| action | string | 是 | 操作：like/dislike/candy |

**每日限制：**

- 👍 (like)：25次/天
- 👎 (dislike)：25次/天
- 🍬 (candy)：15次/天

**评价限制：**

- 不能评价自己的卡牌
- 每个用户每天对同一张卡只能评价1次

**请求示例：**

```json
{
    "uid": "123456789",
    "card_id": 15,
    "action": "like"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "评价成功 +1👍"
}
```

**action说明：**

| action | 说明 |
|--------|------|
| like | 👍 赞 |
| dislike | 👎 踩 |
| candy | 🍬 糖果（同时+1👎） |

---

### 4. 投稿卡牌

**POST** `/diy/submit`

投稿DIY卡牌。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |
| image_base64 | string | 是 | 卡牌图片BASE64 |
| anonymous | bool | 否 | 是否匿名（默认false） |

**限制：**

- 每天最多投稿3张
- 图片大小限制1MB

**请求示例：**

```json
{
    "uid": "123456789",
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
    "anonymous": false
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "投稿成功，等待审核",
    "data": {
        "card_id": 20
    }
}
```

---

### 5. 查询卡牌详情

**GET** `/diy/card/{card_id}`

根据卡牌ID获取卡牌详细信息。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| card_id | int | 卡牌ID |

**请求示例：**

```
GET /diy/card/15
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "card_id": 15,
        "author": "玩家A",
        "submitted_at": "2026-06-25 14:30:00",
        "state": "正常",
        "likes": 12,
        "dislikes": 2,
        "candies": 5,
        "image_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
}
```

**state字段说明：**

| state | 说明 |
|-------|------|
| 未过审 | 审核未通过 |
| 待审核 | 等待审核 |
| 正常 | 审核通过 |
| 🍬区 | 糖果区 |
| 非二战/自创国家区 | 联动卡牌 |
| 官卡改卡区 | 官卡修改版 |
| 二次元区 | 二次元卡牌 |
| 其他卡区 | 其他类型 |

---

### 6. 查询用户全部DIY卡牌

**POST** `/diy/user_cards`

查询指定用户的所有DIY卡牌及其评价信息。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| uid | string | 是 | 用户QQ号 |

**请求示例：**

```json
{
    "uid": "123456789"
}
```

**响应示例：**

```json
{
    "code": 0,
    "msg": "success",
    "data": {
        "user_uid": "123456789",
        "total": 3,
        "total_likes": 25,
        "total_dislikes": 5,
        "total_candies": 8,
        "cards": [
            {
                "card_id": 15,
                "author": "玩家A",
                "submitted_at": "2026-06-25 14:30:00",
                "state": "正常",
                "likes": 12,
                "dislikes": 2,
                "candies": 5,
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
            },
            {
                "card_id": 10,
                "author": "玩家A",
                "submitted_at": "2026-06-24 10:00:00",
                "state": "🍬区",
                "likes": 8,
                "dislikes": 2,
                "candies": 20,
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
            }
        ]
    }
}
```

**响应字段说明：**

| 字段 | 说明 |
|------|------|
| user_uid | 用户QQ号 |
| total | 卡牌总数 |
| total_likes | 所有卡牌获得的👍总数 |
| total_dislikes | 所有卡牌获得的👎总数 |
| total_candies | 所有卡牌获得的🍬总数 |
| cards | 卡牌列表（按ID倒序） |

---

## 错误码说明

| code | 说明 |
|------|------|
| 0 | 成功 |
| 1 | 业务错误（具体错误见msg） |
| 401 | 未登录/用户不存在 |
| 400 | 请求格式错误 |

---

## 图片使用说明

所有返回的 `image_base64` 字段均为纯Base64字符串，前端可直接使用：

```html
<img src="data:image/png;base64,iVBORw0KGgo..." />
```

或通过JavaScript解码：

```javascript
const img = document.createElement('img');
img.src = `data:image/png;base64,${response.data.image_base64}`;
document.body.appendChild(img);
```
