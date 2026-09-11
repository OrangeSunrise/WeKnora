"""
02_filter_wiki.py — 正文评分优先 + 垃圾标题过滤 → 工业技术文档筛选

策略（适配通用中文维基，标题多为专有名词）：
  ① 正文关键词评分（主要）→ ② 垃圾标题过滤 → ③ 长度/质量过滤 → ④ 去重排序

实际数据格式：completion（全文）, source（wikipedia.zh2307）

输入: data/raw/wikipedia-cn/
输出: data/filtered/industrial_wiki.jsonl
"""
import json
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datasets import load_from_disk
from rich.console import Console
from rich.table import Table
from rich.progress import track

console = Console()

# ── 路径 ──
RAW_DIR = ROOT / "data" / "raw" / "wikipedia-cn"
FILTERED_DIR = ROOT / "data" / "filtered"
OUTPUT_FILE = FILTERED_DIR / "industrial_wiki.jsonl"

# ── 阈值 ──
MIN_SCORE = 5          # 正文评分最低阈值
MIN_CONTENT_LEN = 300  # 最小正文字符数
TARGET_COUNT = 12000   # 目标保留数（质量检查后会再裁减）

# ── 加载配置 ──
with open(ROOT / "config" / "keywords.json", encoding="utf-8") as f:
    kw_config = json.load(f)

TITLE_KEYWORDS = kw_config["title_keywords"]
CONTENT_KEYWORDS = kw_config["content_keywords"]
GARBAGE_PATTERNS = kw_config["garbage_patterns"]


# ── 辅助函数 ──

def extract_title(completion: str) -> str:
    """从 completion 提取标题（首行 ≤80字则为首行，否则首句）"""
    text = completion.strip()
    if not text:
        return ""
    first_line = text.split("\n")[0].strip()
    if len(first_line) <= 80:
        return first_line
    match = re.match(r"^(.+?[。！？])", text)
    if match:
        return match.group(1)
    return first_line[:80]


def count_keywords(text: str, keywords: list[str]) -> int:
    """命中关键词种类数（去重）"""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def has_any_garbage(title: str) -> bool:
    """标题匹配垃圾模式 → 排除"""
    return any(p in title for p in GARBAGE_PATTERNS)


def content_score(content: str) -> int:
    """
    正文评分 = keyword_count * 2 + length_bonus
    length_bonus: <300→0, 300-600→1, 600-1000→2, 1000-2000→3, >2000→4
    """
    kw_count = count_keywords(content, CONTENT_KEYWORDS)
    length = len(content)
    if length < 300:
        lb = 0
    elif length < 600:
        lb = 1
    elif length < 1000:
        lb = 2
    elif length < 2000:
        lb = 3
    else:
        lb = 4
    return kw_count * 2 + lb


def keyword_bonus(title: str) -> int:
    """标题命中关键词的额外加分"""
    return sum(1 for kw in TITLE_KEYWORDS if kw.lower() in title.lower())


# ── 主流程 ──

def filter_pipeline():
    if not RAW_DIR.exists():
        console.print("[red]未找到本地数据集，请先运行 01_download_wiki.py[/red]")
        sys.exit(1)

    console.print("[bold cyan]加载本地数据集...[/bold cyan]")
    dataset = load_from_disk(str(RAW_DIR))
    total = len(dataset)
    console.print(f"  原始记录: {total:,}")
    console.print(f"  字段:     {dataset.column_names}\n")

    console.print(f"[bold]正文评分筛选（阈值≥{MIN_SCORE}）...[/bold]\n")

    results = []
    stats = {"raw": total, "scored": 0, "garbage_drop": 0,
             "length_drop": 0, "final": 0}

    for i in track(range(total), description="评分中"):
        item = dataset[i]
        completion = item.get("completion", "") or ""
        if not completion.strip():
            continue

        title = extract_title(completion)

        # ── 正文评分 ──
        score = content_score(completion)
        if score < MIN_SCORE:
            continue
        stats["scored"] += 1

        # ── 标题加分 ──
        title_bonus = keyword_bonus(title)
        total_score = score + title_bonus

        # ── 垃圾过滤 ──
        if has_any_garbage(title):
            stats["garbage_drop"] += 1
            continue

        # ── 长度过滤 ──
        if len(completion) < MIN_CONTENT_LEN:
            stats["length_drop"] += 1
            continue

        doc_id = hashlib.md5(title.encode()).hexdigest()[:12]
        results.append({
            "id": doc_id,
            "title": title,
            "content": completion,
            "source": item.get("source", "wikipedia.zh2307"),
            "quality_score": total_score,
        })

    stats["final"] = len(results)

    console.print(f"\n[bold]各阶段统计:[/bold]")
    console.print(f"  原始总数:    {stats['raw']:,}")
    console.print(f"  评分≥{MIN_SCORE}:  {stats['scored']:,}")
    console.print(f"  垃圾过滤:    {stats['garbage_drop']:,}")
    console.print(f"  长度过滤:    {stats['length_drop']:,}")
    console.print(f"  通过:        {stats['final']:,}")

    # ── 去重 ──
    console.print(f"\n[bold]去重处理...[/bold]")
    seen = set()
    unique_results = []
    for r in results:
        h = hashlib.md5(r["content"].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique_results.append(r)
    dup_count = len(results) - len(unique_results)
    console.print(f"  重复: {dup_count}")

    # ── 排序取 Top ──
    unique_results.sort(key=lambda x: x["quality_score"], reverse=True)
    final_count = min(TARGET_COUNT, len(unique_results))
    results = unique_results[:final_count]

    # ── 保存 ──
    FILTERED_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ── 统计 ──
    avg_len = sum(len(r["content"]) for r in results) / len(results) if results else 0
    avg_score = sum(r["quality_score"] for r in results) / len(results) if results else 0

    console.print(f"\n[bold green]筛选完成！[/bold green]")
    console.print(f"  最终保留: {len(results):,} 篇")
    console.print(f"  过滤率:   {(1 - len(results)/total)*100:.1f}%")
    console.print(f"  平均长度: {avg_len:.0f} 字")
    console.print(f"  平均评分: {avg_score:.1f}")
    console.print(f"  输出文件: {OUTPUT_FILE}")

    # ── 分数分布 ──
    if results:
        score_dist = {}
        for r in results:
            bucket = (r["quality_score"] // 5) * 5
            score_dist[bucket] = score_dist.get(bucket, 0) + 1
        table = Table(title="质量评分分布")
        table.add_column("分数段", style="cyan")
        table.add_column("数量", style="green")
        table.add_column("占比", style="yellow")
        for bucket in sorted(score_dist.keys()):
            cnt = score_dist[bucket]
            table.add_row(f"{bucket}-{bucket+4}", f"{cnt:,}",
                         f"{cnt/len(results)*100:.1f}%")
        console.print(table)

    # ── 打印几个示例标题 ──
    console.print(f"\n[bold]示例文档（Top 10）:[/bold]")
    for r in results[:10]:
        console.print(f"  [{r['quality_score']:2d}] {r['title'][:80]}")


if __name__ == "__main__":
    filter_pipeline()
