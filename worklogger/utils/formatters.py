from __future__ import annotations


def format_quick_logs(logs: list[dict], lang: str = "en", mode: str = "summary") -> str:
    if not logs:
        return ""
    if mode == "daily":
        lines = []
        for lg in logs:
            t_str = lg["time"]
            if lg.get("end_time"):
                t_str += f"–{lg['end_time']}"
            lines.append(f"- {t_str}  {lg['description']}")
        return "\n".join(lines)

    by_date: dict[str, list[dict]] = {}
    for lg in logs:
        by_date.setdefault(lg.get("date", ""), []).append(lg)

    def _join_items(items: list[str]) -> str:
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            sep = {
                "ja": "と",
                "zh": "和",
                "zh_tw": "和",
                "ko": "와",
            }.get(lang, " and ")
            return f"{items[0]}{sep}{items[1]}" if lang in {"ja", "zh", "zh_tw", "ko"} else f"{items[0]} and {items[1]}"
        if lang in {"ja", "zh", "zh_tw", "ko"}:
            return "、".join(items[:-1]) + "、" + items[-1]
        return ", ".join(items[:-1]) + f", and {items[-1]}"

    lines = []
    for d in sorted(by_date):
        day_logs = by_date[d]
        details = []
        times = []
        for lg in day_logs:
            desc = (lg.get("description") or "").strip()
            if desc:
                details.append(desc)
            start = lg.get("time") or ""
            end = lg.get("end_time") or ""
            if start and end:
                times.append(f"{start}–{end}")
            elif start:
                times.append(start)
        shown = details[:3]
        extra = len(details) - len(shown)
        summary = _join_items(shown)
        if extra > 0:
            more = {
                "ja": f"ほか{extra}件",
                "zh": f"等{extra}项",
                "zh_tw": f"等{extra}項",
                "ko": f"외 {extra}건",
            }.get(lang, f"{extra} more")
            summary = f"{summary}、{more}" if lang in {"ja", "zh", "zh_tw"} else (
                f"{summary}, {more}" if lang == "ko" else f"{summary}, and {more}"
            )
        if not summary:
            summary = {
                "ja": "作業記録",
                "zh": "工作记录",
                "zh_tw": "工作記錄",
                "ko": "작업 기록",
            }.get(lang, "work updates")
        times_text = " / ".join(times[:3])
        if lang == "ja":
            line = f"- {d}: {summary}に対応。"
            if times_text:
                line += f" 記録時刻: {times_text}。"
        elif lang == "zh":
            line = f"- {d}：主要处理了{summary}。"
            if times_text:
                line += f" 记录时间：{times_text}。"
        elif lang == "zh_tw":
            line = f"- {d}：主要處理了{summary}。"
            if times_text:
                line += f" 記錄時間：{times_text}。"
        elif lang == "ko":
            line = f"- {d}: {summary} 작업을 진행했습니다."
            if times_text:
                line += f" 기록 시간: {times_text}."
        else:
            line = f"- {d}: Worked on {summary}."
            if times_text:
                line += f" Logged around {times_text}."
        lines.append(line)
    return "\n".join(lines)


def format_cal_events(events: list[dict]) -> str:
    if not events:
        return ""
    lines = []
    for ev in events:
        t_str = ""
        if ev.get("start_time"):
            t_str = ev["start_time"]
            if ev.get("end_time"):
                t_str += f"–{ev['end_time']}"
            t_str += "  "
        loc = f"  [{ev['location']}]" if ev.get("location") else ""
        lines.append(f"- {t_str}{ev['summary']}{loc}")
    return "\n".join(lines)
