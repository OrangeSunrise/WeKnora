"""
03_quality_check.py — 文档质量检查与报告生成

对筛选后的文档做进一步质量分析，生成统计报告。
输出: data/filtered/industrial_wiki_clean.jsonl（清洗后）
      reports/dataset_report.md（数据集报告）
"""
import json
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.table import Table

console = Console()

FILTERED_FILE = ROOT / "data" / "filtered" / "industrial_wiki.jsonl"
CLEAN_FILE = ROOT / "data" / "filtered" / "industrial_wiki_clean.jsonl"
REPORT_DIR = ROOT / "reports"
REPORT_FILE = REPORT_DIR / "dataset_report.md"

# ── 质量控制参数 ──
MIN_CONTENT_LENGTH = 300   # 最小正文字符数
MAX_CONTENT_LENGTH = 3000  # 最大正文字符数（过滤超长异常）
MAX_WHITESPACE_RATIO = 0.3  # 最大空白/乱码比例


def quality_check():
    if not FILTERED_FILE.exists():
        console.print("[red]未找到筛选结果，请先运行 02_filter_wiki.py[/red]")
        sys.exit(1)

    # 加载数据
    console.print("[bold cyan]加载筛选结果...[/bold cyan]")
    docs = []
    with open(FILTERED_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))

    total = len(docs)
    console.print(f"  输入文档: {total:,}\n")

    # ── 质量检查 ──
    stats = {
        "total_input": total,
        "too_short": 0,
        "too_long": 0,
        "high_whitespace": 0,
        "empty_content": 0,
        "passed": 0,
    }

    clean_docs = []
    length_dist = []

    for doc in docs:
        content = doc.get("content", "")

        # 空内容
        if not content or not content.strip():
            stats["empty_content"] += 1
            continue

        # 过短
        if len(content) < MIN_CONTENT_LENGTH:
            stats["too_short"] += 1
            continue

        # 过长
        if len(content) > MAX_CONTENT_LENGTH:
            stats["too_long"] += 1
            continue

        # 高空白/乱码
        whitespace_ratio = content.count(" ") / len(content) if content else 0
        # 中文乱码特征：大量拉丁扩展字符
        garbage_chars = sum(1 for c in content if '' <= c <= 'ÿ' and not c.isascii())
        garbage_ratio = garbage_chars / len(content)
        if whitespace_ratio > MAX_WHITESPACE_RATIO or garbage_ratio > 0.3:
            stats["high_whitespace"] += 1
            continue

        # 通过
        stats["passed"] += 1
        length_dist.append(len(content))
        clean_docs.append(doc)

    # ── 长度分析 ──
    if length_dist:
        length_dist.sort()
        avg_len = sum(length_dist) / len(length_dist)
        p50 = length_dist[len(length_dist) // 2]
        p95 = length_dist[int(len(length_dist) * 0.95)]
    else:
        avg_len = p50 = p95 = 0

    # ── 保存清洗结果 ──
    CLEAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CLEAN_FILE, "w", encoding="utf-8") as f:
        for doc in clean_docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    # ── 生成报告 ──
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = f"""# 数据集质量报告

> 生成时间: 自动生成
> 数据来源: pleisto/wikipedia-cn-20230720-filtered

---

## 质量过滤统计

| 阶段 | 数量 | 占比 |
|------|-----:|-----:|
| 筛选输入 | {stats['total_input']:,} | 100.0% |
| 空内容 | {stats['empty_content']:,} | {stats['empty_content']/stats['total_input']*100:.1f}% |
| 过短 (<{MIN_CONTENT_LENGTH}字) | {stats['too_short']:,} | {stats['too_short']/stats['total_input']*100:.1f}% |
| 过长 (>{MAX_CONTENT_LENGTH}字) | {stats['too_long']:,} | {stats['too_long']/stats['total_input']*100:.1f}% |
| 高乱码率 | {stats['high_whitespace']:,} | {stats['high_whitespace']/stats['total_input']*100:.1f}% |
| **通过** | **{stats['passed']:,}** | **{stats['passed']/stats['total_input']*100:.1f}%** |

---

## 文档长度分布

| 指标 | 值 |
|------|----:|
| 平均长度 | {avg_len:.0f} 字 |
| P50 中位数 | {p50} 字 |
| P95 | {p95} 字 |
| 最小 | {length_dist[0] if length_dist else 0} 字 |
| 最大 | {length_dist[-1] if length_dist else 0} 字 |

---

## 输出文件

- 筛选结果: `data/filtered/industrial_wiki.jsonl`
- 清洗结果: `data/filtered/industrial_wiki_clean.jsonl`

## 质量指标达标情况

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|:----:|
| 平均长度 | 300-1500字 | {avg_len:.0f}字 | {'✅' if 300 <= avg_len <= 1500 else '⚠️'} |
| 空文档率 | <0.5% | {stats['empty_content']/stats['total_input']*100:.1f}% | {'✅' if stats['empty_content']/stats['total_input'] < 0.005 else '⚠️'} |
| 最终数量 | ~10000篇 | {stats['passed']:,}篇 | {'✅' if 8000 <= stats['passed'] <= 12000 else '⚠️'} |
"""

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    # ── 终端输出 ──
    console.print(f"\n[bold green]质量检查完成！[/bold green]")
    console.print(f"  通过: {stats['passed']:,} / {total:,} ({stats['passed']/total*100:.1f}%)")
    console.print(f"  平均长度: {avg_len:.0f} 字")
    console.print(f"  清洗输出: {CLEAN_FILE}")
    console.print(f"  数据集报告: {REPORT_FILE}")


if __name__ == "__main__":
    quality_check()
