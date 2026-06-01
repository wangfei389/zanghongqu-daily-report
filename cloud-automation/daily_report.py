#!/usr/bin/env python3
"""
藏红曲销售团队每日工作汇报总结 — 云端自动化脚本

功能：
1. 读取腾讯文档"每日工作汇报表"和"意向客户跟进表"
2. 对李立、王保同、胡平、韩婉臻四人进行分析
3. 未填写日报的人重点提示
4. 已填写的内容进行总结分析并给出建议
5. 通过 PushPlus 推送到微信

部署：GitHub Actions / 任意云服务器 (Python 3.8+)
"""

import json
import os
import sys
import traceback
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests

# ============================================================
# 配置区域 — 通过环境变量注入（云端安全存储）
# ============================================================

# 腾讯文档认证 — 支持两种模式:
# 模式A（推荐）: 直接传 access_token（简单，但需手动更新）
# 模式B: OAuth 自动刷新（需要 Client Secret + Refresh Token）
TENCENT_ACCESS_TOKEN = os.environ.get("TENCENT_ACCESS_TOKEN", "")
CLIENT_ID = os.environ.get("TENCENT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TENCENT_CLIENT_SECRET", "")
OPEN_ID = os.environ.get("TENCENT_OPEN_ID", "")
REFRESH_TOKEN = os.environ.get("TENCENT_REFRESH_TOKEN", "")
DIRECT_MODE = bool(TENCENT_ACCESS_TOKEN)  # 有 access_token 就用直接模式

# 表格 ID
DAILY_REPORT_FILE_ID = "ZJqIjcaPAtAH"
DAILY_REPORT_SHEET_ID = "BB08J2"
CUSTOMER_TRACK_FILE_ID = "ZKEaEdisammD"
CUSTOMER_TRACK_SHEET_ID = "BB08J2"

# PushPlus
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "bdf1d66a49e346cd95c946ef9a131e5f")

# 监控人员
TEAM_MEMBERS = ["李立", "王保同", "胡平", "韩婉臻"]

# ============================================================
# API 常量
# ============================================================

TOKEN_URL = "https://docs.qq.com/oauth/v2/token"
SHEET_API = "https://docs.qq.com/openapi/spreadsheet/v3/files"
PUSHPLUS_URL = "https://www.pushplus.plus/send"

# ============================================================
# Token 管理
# ============================================================

_current_access_token = None


def get_access_token() -> str:
    """获取有效的 access_token。
    直接模式下返回环境变量中的 token，无需刷新。
    OAuth 模式下用 refresh_token 自动刷新。"""
    global _current_access_token

    if _current_access_token:
        return _current_access_token

    if DIRECT_MODE:
        _current_access_token = TENCENT_ACCESS_TOKEN
        return _current_access_token

    # OAuth 模式: 用 refresh_token 换取新的 access_token
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
    }

    resp = requests.get(TOKEN_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        raise Exception(f"Token 刷新失败: {data}")

    _current_access_token = data["access_token"]
    return _current_access_token


def api_headers() -> dict:
    """构建 API 请求头"""
    return {
        "Access-Token": get_access_token(),
        "Open-Id": OPEN_ID,
        "Client-Id": CLIENT_ID,
        "Accept": "application/json",
    }


# ============================================================
# 表格读取
# ============================================================


def parse_cell(cell: dict) -> str:
    """从 cellValue 中提取文本或数字"""
    if not cell or "cellValue" not in cell:
        return ""
    cv = cell["cellValue"]
    if not cv:
        return ""
    if "text" in cv:
        return cv["text"].strip()
    if "number" in cv:
        val = cv["number"]
        if isinstance(val, float) and val == int(val):
            return str(int(val))
        return str(val)
    if "link" in cv:
        return cv["link"].get("text", "")
    return ""


def read_sheet(file_id: str, sheet_id: str, range_str: str) -> list:
    """读取表格指定范围"""
    url = f"{SHEET_API}/{file_id}/{sheet_id}/{range_str}"
    resp = requests.get(url, headers=api_headers(), timeout=30)

    if resp.status_code == 401 and not DIRECT_MODE:
        # OAuth 模式: Token 可能过期，刷新后重试
        global _current_access_token
        _current_access_token = None
        resp = requests.get(
            url,
            headers={
                "Access-Token": get_access_token(),
                "Open-Id": OPEN_ID,
                "Client-Id": CLIENT_ID,
                "Accept": "application/json",
            },
            timeout=30,
        )

    resp.raise_for_status()
    data = resp.json()

    if data.get("ret") != 0:
        raise Exception(f"API 错误 [{data.get('ret')}]: {data.get('msg')}")

    return data["data"]["gridData"]["rows"]


def read_daily_report() -> list:
    """读取每日工作汇报表（工作表1）"""
    # 列: 日期|姓名|岗位|当日销量|月累计销量|月销量目标|销量完成率|
    #      当日活动场次|月累计场次|月场次目标|场次完成率|
    #      当日拜访客户数|月累计拜访数|新增意向客户|综合达标|备注
    rows = read_sheet(DAILY_REPORT_FILE_ID, DAILY_REPORT_SHEET_ID, "A1:P500")

    records = []
    for i, row in enumerate(rows[1:], start=2):  # 跳过表头
        values = row.get("values", [])
        if len(values) < 16:
            continue

        name = parse_cell(values[1]) if len(values) > 1 else ""
        if not name:
            continue

        records.append(
            {
                "row": i,
                "date": parse_cell(values[0]) if len(values) > 0 else "",
                "name": name,
                "position": parse_cell(values[2]) if len(values) > 2 else "",
                "daily_sales": parse_cell(values[3]) if len(values) > 3 else "",
                "monthly_sales": parse_cell(values[4]) if len(values) > 4 else "",
                "sales_target": parse_cell(values[5]) if len(values) > 5 else "",
                "sales_rate": parse_cell(values[6]) if len(values) > 6 else "",
                "daily_events": parse_cell(values[7]) if len(values) > 7 else "",
                "monthly_events": parse_cell(values[8]) if len(values) > 8 else "",
                "events_target": parse_cell(values[9]) if len(values) > 9 else "",
                "events_rate": parse_cell(values[10]) if len(values) > 10 else "",
                "daily_visits": parse_cell(values[11]) if len(values) > 11 else "",
                "monthly_visits": parse_cell(values[12]) if len(values) > 12 else "",
                "new_leads": parse_cell(values[13]) if len(values) > 13 else "",
                "达标": parse_cell(values[14]) if len(values) > 14 else "",
                "备注": parse_cell(values[15]) if len(values) > 15 else "",
            }
        )

    return records


def read_customer_tracking() -> list:
    """读取意向客户跟进表（工作表1）"""
    # 上半区: 序号|客户姓名|联系电话|客户来源|意向产品|意向等级|
    #         首次接触日期|负责销售|当前跟进阶段|最近跟进日期|
    #         下次跟进日期|跟进摘要|预计成交日期|实际成交日期|成交数量|备注
    rows = read_sheet(CUSTOMER_TRACK_FILE_ID, CUSTOMER_TRACK_SHEET_ID, "A1:P200")

    records = []
    for i, row in enumerate(rows[1:], start=2):
        values = row.get("values", [])

        # 检测是否到达下半区统计面板
        if len(values) > 0:
            first_cell = parse_cell(values[0]) if len(values) > 0 else ""
            if first_cell in ("跟进阶段统计", "来源渠道分析", "销售跟进统计"):
                break

        if len(values) < 16:
            continue

        sales_person = parse_cell(values[7]) if len(values) > 7 else ""
        customer_name = parse_cell(values[1]) if len(values) > 1 else ""
        if not sales_person and not customer_name:
            continue

        records.append(
            {
                "row": i,
                "序号": parse_cell(values[0]) if len(values) > 0 else "",
                "客户姓名": customer_name,
                "联系电话": parse_cell(values[2]) if len(values) > 2 else "",
                "客户来源": parse_cell(values[3]) if len(values) > 3 else "",
                "意向产品": parse_cell(values[4]) if len(values) > 4 else "",
                "意向等级": parse_cell(values[5]) if len(values) > 5 else "",
                "首次接触日期": parse_cell(values[6]) if len(values) > 6 else "",
                "负责销售": sales_person,
                "当前跟进阶段": parse_cell(values[8]) if len(values) > 8 else "",
                "最近跟进日期": parse_cell(values[9]) if len(values) > 9 else "",
                "下次跟进日期": parse_cell(values[10]) if len(values) > 10 else "",
                "跟进摘要": parse_cell(values[11]) if len(values) > 11 else "",
                "预计成交日期": parse_cell(values[12]) if len(values) > 12 else "",
                "实际成交日期": parse_cell(values[13]) if len(values) > 13 else "",
                "成交数量": parse_cell(values[14]) if len(values) > 14 else "",
                "备注": parse_cell(values[15]) if len(values) > 15 else "",
            }
        )

    return records


# ============================================================
# 数据分析
# ============================================================


def match_date(record_date: str, today_str: str, today_alt: str) -> bool:
    """判断记录日期是否匹配今天"""
    if not record_date:
        return False
    return record_date == today_str or record_date == today_alt


def analyze_daily_report(all_records: list):
    """分析每日汇报数据"""
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    today_alt = f"{today.month}/{today.day}"

    # 按姓名查找今天的记录
    submitted = {}
    not_submitted = []

    for member in TEAM_MEMBERS:
        found = [r for r in all_records if r["name"] == member and match_date(r["date"], today_str, today_alt)]
        if found:
            submitted[member] = found[-1]  # 取最新一条
        else:
            not_submitted.append(member)

    return submitted, not_submitted


def analyze_customer_data(all_records: list):
    """分析客户跟进数据"""
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")

    member_stats = defaultdict(
        lambda: {
            "total": 0,
            "by_stage": defaultdict(int),
            "by_source": defaultdict(int),
            "today_followups": [],
            "overdue": [],
            "closed": 0,
            "lost": 0,
        }
    )

    for r in all_records:
        person = r["负责销售"]
        if person not in TEAM_MEMBERS:
            continue

        stats = member_stats[person]
        stats["total"] += 1

        stage = r["当前跟进阶段"]
        stats["by_stage"][stage] += 1

        source = r["客户来源"]
        stats["by_source"][source] += 1

        # 今日跟进
        if r["最近跟进日期"] and match_date(r["最近跟进日期"], today_str, f"{today.month}/{today.day}"):
            stats["today_followups"].append(r)

        # 已成交
        if stage == "已成交":
            stats["closed"] += 1

        # 已流失
        if stage == "已流失":
            stats["lost"] += 1

        # 超期未跟进（下次跟进日期已过但未更新）
        next_date = r["下次跟进日期"]
        if next_date and stage not in ("已成交", "已流失"):
            try:
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d", "%m月%d日"):
                    try:
                        nd = datetime.strptime(next_date, fmt)
                        if nd.year == 1900:
                            nd = nd.replace(year=today.year)
                        if nd.date() < today:
                            stats["overdue"].append(r)
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

    return member_stats


# ============================================================
# 报告生成
# ============================================================


def safe_num(val: str, default: str = "-") -> str:
    """安全显示数值"""
    if not val:
        return default
    return val


def generate_report(submitted: dict, not_submitted: list, customer_stats: dict) -> str:
    """生成 Markdown 格式的总结报告"""
    today = date.today()
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    weekday = weekdays[today.weekday()]

    lines = []
    lines.append(f"# 藏红曲销售团队日报总结")
    lines.append(f"###  {today.strftime('%Y年%m月%d日')} 星期{weekday}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ========== Part 1: 填报状态 ==========
    lines.append("## 一、今日填报状态")
    lines.append("")

    if not_submitted:
        lines.append("### 未填报 — 重点提示")
        lines.append("")
        for name in not_submitted:
            lines.append(f"- **{name}** 今日未提交工作汇报")
        lines.append("")
    else:
        lines.append("全部人员已完成今日填报")
        lines.append("")

    if submitted:
        lines.append("### 已填报")
        lines.append("")
        lines.append(
            "| 姓名 | 岗位 | 当日销量(盒) | 月累计 | 完成率 | "
            "活动场次 | 累计 | 完成率 | 拜访客户 | 新增意向 | 达标 |"
        )
        lines.append(
            "|------|------|:----------:|:------:|:------:|"
            ":--------:|:----:|:------:|:--------:|:--------:|:----:|"
        )

        for name in TEAM_MEMBERS:
            if name in submitted:
                r = submitted[name]
                lines.append(
                    f"| {name} | {r['position']} | "
                    f"{safe_num(r['daily_sales'])} | {safe_num(r['monthly_sales'])} | "
                    f"{safe_num(r['sales_rate'])} | "
                    f"{safe_num(r['daily_events'])} | {safe_num(r['monthly_events'])} | "
                    f"{safe_num(r['events_rate'])} | "
                    f"{safe_num(r['daily_visits'])} | "
                    f"{safe_num(r['new_leads'])} | "
                    f"{safe_num(r['达标'], '-')} |"
                )
            else:
                lines.append(
                    f"| {name} | - | - | - | - | - | - | - | - | - | 未填报 |"
                )

        lines.append("")

    # ========== Part 2: 分析总结 ==========
    lines.append("## 二、数据分析与建议")
    lines.append("")

    if submitted:
        # 销量汇总
        total_sales = 0
        total_events = 0
        total_visits = 0
        total_new_leads = 0
        count_with_data = 0

        for r in submitted.values():
            try:
                total_sales += int(r["daily_sales"]) if r["daily_sales"] else 0
                total_events += int(r["daily_events"]) if r["daily_events"] else 0
                total_visits += int(r["daily_visits"]) if r["daily_visits"] else 0
                total_new_leads += int(r["new_leads"]) if r["new_leads"] else 0
                count_with_data += 1
            except ValueError:
                count_with_data += 1

        lines.append(f"**今日汇总**（{count_with_data} 人已填报）")
        lines.append(f"- 当日总销量: **{total_sales}** 盒")
        lines.append(f"- 当日活动场次: **{total_events}** 场")
        lines.append(f"- 当日拜访客户: **{total_visits}** 人")
        lines.append(f"- 新增意向客户: **{total_new_leads}** 人")
        lines.append("")

        # 个人建议
        lines.append("### 个人分析")
        lines.append("")

        for name in TEAM_MEMBERS:
            if name not in submitted:
                continue
            r = submitted[name]
            lines.append(f"**{name}**")

            suggestions = []

            # 销量分析
            try:
                ds = int(r["daily_sales"]) if r["daily_sales"] else 0
                if ds == 0:
                    suggestions.append("今日无销量产出，建议复盘客户沟通情况")
                elif ds < 5:
                    suggestions.append(f"销量偏低({ds}盒)，建议加大拜访量和活动频次")
            except ValueError:
                pass

            # 活动分析
            try:
                de = int(r["daily_events"]) if r["daily_events"] else 0
                if de > 0:
                    suggestions.append(f"开展{de}场活动，注意跟进活动中的意向客户")
            except ValueError:
                pass

            # 拜访分析
            try:
                dv = int(r["daily_visits"]) if r["daily_visits"] else 0
                if dv == 0:
                    suggestions.append("无拜访记录，建议增加客户触达")
                elif dv < 5:
                    suggestions.append(f"拜访{dv}位客户，建议提升至每日8-10位")
            except ValueError:
                pass

            # 达标情况
            if r["达标"]:
                status = r["达标"]
                if "达标" in status and "不" not in status:
                    suggestions.append("综合达标，继续保持！")
                else:
                    suggestions.append("当前未达标，需加大产出力度")

            if suggestions:
                for s in suggestions:
                    lines.append(f"  - {s}")
            else:
                lines.append(f"  - 数据正常")

            # 备注
            if r["备注"]:
                lines.append(f"  - 备注: {r['备注']}")

            lines.append("")

    # ========== Part 3: 客户跟进分析 ==========
    lines.append("## 三、意向客户跟进分析")
    lines.append("")

    for name in TEAM_MEMBERS:
        stats = customer_stats.get(name, {})
        total = stats.get("total", 0)

        if total == 0:
            lines.append(f"**{name}**: 暂无跟进客户")
            lines.append("")
            continue

        by_stage = stats.get("by_stage", {})
        closed = stats.get("closed", 0)
        lost = stats.get("lost", 0)

        lines.append(f"**{name}** — 共 {total} 位意向客户")
        lines.append("")

        # 阶段分布
        stage_order = ["待联系", "已触达", "深入沟通", "意向确认", "已成交", "已流失"]
        stage_items = []
        for s in stage_order:
            count = by_stage.get(s, 0)
            if count > 0:
                stage_items.append(f"{s} {count}人")
        lines.append(f"  阶段分布: {' | '.join(stage_items) if stage_items else '暂无分类'}")
        lines.append("")

        # 转化率
        active = total - lost
        if active > 0:
            conv_rate = closed / active * 100
            lines.append(f"  成交 {closed} 人 | 流失 {lost} 人 | 转化率 {conv_rate:.1f}%")
        lines.append("")

        # 今日跟进
        today_fus = stats.get("today_followups", [])
        if today_fus:
            lines.append(f"  今日跟进 {len(today_fus)} 位客户:")
            for fu in today_fus[:5]:
                lines.append(
                    f"    - {fu['客户姓名']} ({fu['当前跟进阶段']}) — "
                    f"{fu['跟进摘要'][:30] if fu['跟进摘要'] else '无摘要'}"
                )
            if len(today_fus) > 5:
                lines.append(f"    - ... 还有 {len(today_fus) - 5} 位")
            lines.append("")

        # 超期提醒
        overdue = stats.get("overdue", [])
        if overdue:
            lines.append(f"  超期未跟进 ({len(overdue)} 位):")
            for ov in overdue[:5]:
                lines.append(
                    f"    - {ov['客户姓名']} ({ov['当前跟进阶段']}) — "
                    f"上次跟进: {ov['最近跟进日期']} | 应于 {ov['下次跟进日期']}"
                )
            if len(overdue) > 5:
                lines.append(f"    - ... 还有 {len(overdue) - 5} 位")
            lines.append("")

    # ========== Part 4: 总结建议 ==========
    lines.append("---")
    lines.append("## 四、综合建议")
    lines.append("")

    if not_submitted:
        names = "、".join(not_submitted)
        lines.append(f"1.  {names} 请尽快补填今日工作汇报")
    else:
        lines.append("1. 全员已提交日报，数据闭环良好")

    # 统计超期总数
    total_overdue = sum(len(s.get("overdue", [])) for s in customer_stats.values())
    if total_overdue > 0:
        lines.append(f"2. 共有 {total_overdue} 位意向客户超期未跟进，需立即安排回访")
    else:
        lines.append("2. 客户跟进时效良好，无超期情况")

    # 建议
    lines.append("3. 建议明日重点关注: 已进入「意向确认」阶段客户的转化推进")
    lines.append("4. 请各销售确保每日拜访量达标 (建议 8-10 位/日)")

    lines.append("")
    lines.append("---")
    lines.append("*本报告由自动化系统生成，每晚21:00自动推送*")

    return "\n".join(lines)


# ============================================================
# 推送
# ============================================================


def send_via_pushplus(content: str):
    """通过 PushPlus 推送到微信"""
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": f"藏红曲销售日报 {date.today().strftime('%m.%d')}",
        "content": content,
        "template": "markdown",
        "channel": "wechat",
    }
    resp = requests.post(PUSHPLUS_URL, json=data, timeout=30)
    result = resp.json()
    if result.get("code") != 200:
        raise Exception(f"PushPlus 发送失败: {result}")
    print(f"PushPlus 推送成功: {result.get('msg')}")


# ============================================================
# 主流程
# ============================================================


def main():
    print(f"[{datetime.now()}] 开始执行每日总结...")

    # 1. 验证配置
    if DIRECT_MODE:
        if not OPEN_ID:
            print("错误: 直接模式需要 TENCENT_OPEN_ID")
            sys.exit(1)
        print("使用直接模式 (TENCENT_ACCESS_TOKEN)")
    elif not all([CLIENT_ID, CLIENT_SECRET, OPEN_ID, REFRESH_TOKEN]):
        print("错误: 缺少腾讯文档认证配置")
        print("请设置环境变量:")
        print("  直接模式: TENCENT_ACCESS_TOKEN + TENCENT_OPEN_ID + TENCENT_CLIENT_ID")
        print("  OAuth模式: TENCENT_CLIENT_ID + TENCENT_CLIENT_SECRET + "
              "TENCENT_OPEN_ID + TENCENT_REFRESH_TOKEN")
        sys.exit(1)

    try:
        # 2. 读取日报数据
        print("读取每日工作汇报表...")
        daily_records = read_daily_report()
        print(f"  获取到 {len(daily_records)} 条记录")

        # 3. 分析日报
        submitted, not_submitted = analyze_daily_report(daily_records)

        # 4. 读取客户跟进数据
        print("读取意向客户跟进表...")
        customer_records = read_customer_tracking()
        print(f"  获取到 {len(customer_records)} 条记录")

        # 5. 分析客户数据
        customer_stats = analyze_customer_data(customer_records)

        # 6. 生成报告
        print("生成总结报告...")
        report = generate_report(submitted, not_submitted, customer_stats)

        # 7. 推送
        print("推送报告到微信...")
        send_via_pushplus(report)

        print(f"[{datetime.now()}] 执行完成")
        print()
        print(report)

    except requests.exceptions.RequestException as e:
        print(f"网络请求错误: {e}")
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"执行失败: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
