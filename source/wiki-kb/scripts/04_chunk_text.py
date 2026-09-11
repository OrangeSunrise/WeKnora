"""
04_chunk_text.py — 对筛选后的文档进行文本分块

使用 RecursiveCharacterTextSplitter，为后续 Embedding 做准备。
参数：chunk_size=800, chunk_overlap=150（适合中文技术文档）

输入: data/filtered/industrial_wiki_clean.jsonl
输出: data/chunks/wiki_chunks.jsonl
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_text_splitters import RecursiveCharacterTextSplitter
from rich.console import Console
from rich.table import Table

console = Console()

INPUT_FILE = ROOT / "data" / "filtered" / "industrial_wiki_clean.jsonl"
CHUNKS_DIR = ROOT / "data" / "chunks"
OUTPUT_FILE = CHUNKS_DIR / "wiki_chunks.jsonl"

# ── 分块参数 ──
# 选择 800 / 150 是为了匹配未来 S120 手册参数描述的长度（500-1000 字）
CHUNK_SIZE = 800
CHUNK_OVERLAP = 300


def chunk_documents():
    # 检查输入文件
    input_file = INPUT_FILE
    if not input_file.exists():
        # 回退到未清洗版本
        fallback = ROOT / "data" / "filtered" / "industrial_wiki.jsonl"
        if fallback.exists():
            input_file = fallback
            console.print("[yellow]未找到清洗结果，使用筛选结果[/yellow]")
        else:
            console.print("[red]未找到任何输入数据，请先运行 02_filter_wiki.py[/red]")
            sys.exit(1)

    console.print(f"[bold cyan]加载文档: {input_file}[/bold cyan]")
    docs = []
    with open(input_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))

    console.print(f"  文档数: {len(docs):,}")

    # ── 初始化分块器 ──
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "；", "！", "？", "，", " ", ""],
    )

    # ── 分块 ──
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    all_chunks = []
    chunk_lengths = []
    skipped_short = 0

    console.print(f"\n[bold]开始分块... (chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})[/bold]")

    for doc in docs:
        content = doc.get("content", "")
        title = doc.get("title", "")

        raw_chunks = splitter.split_text(content)

        for i, chunk_text in enumerate(raw_chunks):
            chunk_text = chunk_text.strip()
            if len(chunk_text) < 50:  # 过滤碎片
                skipped_short += 1
                continue

            chunk_lengths.append(len(chunk_text))
            all_chunks.append({
                "chunk_id": f"wiki-{doc.get('id', 'unknown')}-{i:04d}",
                "title": title,
                "content": chunk_text,
                "char_count": len(chunk_text),
                "chunk_index": i,
                "source": doc.get("source", "wikipedia.zh2307"),
                "source_id": doc.get("id", ""),
            })

    # ── 保存 ──
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # ── 统计 ──
    avg_chunk_len = sum(chunk_lengths) / len(chunk_lengths) if chunk_lengths else 0
    avg_chunks_per_doc = len(all_chunks) / len(docs) if docs else 0

    console.print(f"\n[bold green]分块完成！[/bold green]")
    console.print(f"  Chunk总数: {len(all_chunks):,}")
    console.print(f"  平均每文档: {avg_chunks_per_doc:.1f} chunks")
    console.print(f"  平均Chunk长度: {avg_chunk_len:.0f} 字")
    console.print(f"  碎片过滤: {skipped_short} 条")
    console.print(f"  输出文件: {OUTPUT_FILE}")

    # ── Chunk长度分布 ──
    if chunk_lengths:
        chunk_lengths.sort()
        dist_ranges = [
            (0, 200), (200, 400), (400, 600), (600, 800),
            (800, 1000), (1000, 1200), (1200, float("inf"))
        ]
        table = Table(title="Chunk 长度分布")
        table.add_column("长度范围", style="cyan")
        table.add_column("数量", style="green")
        table.add_column("占比", style="yellow")
        for lo, hi in dist_ranges:
            cnt = sum(1 for x in chunk_lengths if lo <= x < hi)
            table.add_row(f"{lo}-{int(hi) if hi != float('inf') else '∞'}",
                         f"{cnt:,}",
                         f"{cnt/len(chunk_lengths)*100:.1f}%")
        console.print(table)


if __name__ == "__main__":
    chunk_documents()
