"""Pure text formatting for shareable weekly/monthly health reports."""
from __future__ import annotations

from services.units import format_weight


def format_health_report(summary: dict, weight_unit: str = "斤") -> str:
    title = summary.get("title") or "健康报告"
    lines = [f"体重追踪助手 · {title}", f"统计范围：{summary.get('start_date', '--')} 至 {summary.get('end_date', '--')}", ""]
    lines.append("【体重】")
    lines.append(f"有效记录：{summary.get('weight_count', 0)} 条")
    lines.append(f"记录平均：{format_weight(summary.get('weight_average_jin'), weight_unit)}")
    lines.append(f"7 日平均：{format_weight(summary.get('seven_day_average_jin'), weight_unit)}（覆盖 {summary.get('seven_day_days', 0)} 个有记录的日期）")
    change = summary.get("daily_average_change_jin")
    if change is not None:
        # Convert a delta with the same factor as an absolute weight.
        from services.units import jin_to_display
        delta = jin_to_display(change, weight_unit)
        lines.append(f"首末日均变化：{delta:+.1f} {weight_unit}")
    else:
        lines.append("首末日均变化：记录不足，暂不可计算")
    trends = summary.get("grouped_trend") or []
    if trends:
        lines.append("趋势（每日平均体重；月报按 ISO 周聚合）：")
        for key, value in trends:
            lines.append(f"  {key}：{jin_to_display(value, weight_unit):.1f} {weight_unit}")
    target = summary.get("target_weight_jin")
    current = summary.get("current_weight_jin")
    progress = summary.get("goal_progress_percent")
    if target is not None:
        lines.append(f"当前体重：{format_weight(current, weight_unit)}；目标：{format_weight(target, weight_unit)}")
        if progress is not None:
            lines.append(f"目标进度：{max(0.0, min(100.0, progress)):.0f}%（按第一条历史体重到目标的线性进度估算）")
    lines.extend(["", "【饮食】", f"记录条目：{summary.get('food_entries', 0)} 条",
                  f"总摄入：{summary.get('calories_total', 0):.0f} kcal",
                  f"记录日均：{summary.get('calories_daily_average', 0) or 0:.0f} kcal（仅按有饮食记录的日期平均）",
                  f"蛋白质合计：{summary.get('protein_total_g', 0):.1f} g", "",
                  "【训练】", f"结构化训练项目：{summary.get('training_entries', 0)} 项",
                  f"有训练日志的日期：{summary.get('training_days', 0)} 天",
                  f"日历打卡天数：{summary.get('workout_days', 0)} 天",
                  f"记录训练时长：{summary.get('training_minutes', 0):.0f} 分钟", "",
                  "【身体变化】", f"本期照片：{summary.get('photo_count', 0)} 张"])
    measurement = summary.get("latest_measurement")
    if measurement:
        values = []
        for key, label, unit in (("waist_cm", "腰围", "cm"), ("hip_cm", "臀围", "cm"),
                                 ("chest_cm", "胸围", "cm"), ("body_fat_pct", "体脂率", "%")):
            if measurement.get(key) is not None:
                values.append(f"{label} {float(measurement[key]):.1f}{unit}")
        lines.append(f"最近测量（{measurement.get('measured_at', '--')}）：" + ("、".join(values) or "无数据"))
    else:
        lines.append("还没有身体围度记录")
    lines.extend(["", "提示：本报告是本机记录的汇总，不是医疗诊断。饮食热量和训练数据取决于手动记录。"])
    return "\n".join(lines)
