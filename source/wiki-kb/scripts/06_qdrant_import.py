import uuid
"""
06_qdrant_import.py — 将向量化后的 chunks 导入 Qdrant

需先启动 Qdrant：
  docker run -d -p 6333:6333 -v ${PWD}/qdrant:/qdrant/storage qdrant/qdrant

输入: data/chunks/wiki_chunks_embedded.jsonl
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    PayloadSchemaType,
)
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn

console = Console()

INPUT_FILE = ROOT / "data" / "chunks" / "wiki_chunks_embedded.jsonl"
COLLECTION_NAME = "industrial_wiki"

# Qdrant 连接参数
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333


def get_client() -> QdrantClient:
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        # 测试连接
        client.get_collections()
        return client
    except Exception as e:
        console.print(f"[red]无法连接 Qdrant ({QDRANT_HOST}:{QDRANT_PORT})[/red]")
        console.print(f"[red]错误: {e}[/red]")
        console.print("\n[yellow]请先启动 Qdrant：[/yellow]")
        console.print("  docker run -d -p 6333:6333 -v ${PWD}/qdrant:/qdrant/storage qdrant/qdrant")
        sys.exit(1)


def init_collection(client: QdrantClient):
    """初始化集合"""

    if client.collection_exists(COLLECTION_NAME):
        existing = client.get_collection(COLLECTION_NAME)
        count = existing.points_count
        console.print(f"[yellow]集合 '{COLLECTION_NAME}' 已存在 ({count:,} 条记录)[/yellow]")
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )

    # 为常用过滤字段建索引
    for field in ("source", "title"):
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )

    console.print(f"[green]集合 '{COLLECTION_NAME}' 创建完成[/green]")


def import_to_qdrant():
    if not INPUT_FILE.exists():
        console.print("[red]未找到 embedding 文件，请先运行 05_embedding.py[/red]")
        sys.exit(1)

    # 加载数据
    console.print("[bold cyan]加载 embedded chunks...[/bold cyan]")
    chunks = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))

    total = len(chunks)
    console.print(f"  Chunk数: {total:,}")

    # 连接 Qdrant
    console.print(f"\n[bold cyan]连接 Qdrant ({QDRANT_HOST}:{QDRANT_PORT})...[/bold cyan]")
    client = get_client()
    init_collection(client)

    # ── 批量导入 ──
    BATCH_SIZE = 500
    console.print(f"\n[bold]开始导入... (batch_size={BATCH_SIZE})[/bold]\n")

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
    ) as progress:
        task = progress.add_task("[cyan]导入 Qdrant", total=total)

        for i in range(0, total, BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            points = []

            for c in batch:
                # Payload: 除 embedding 外的所有字段
                payload = {k: v for k, v in c.items() if k != "embedding"}
                points.append(PointStruct(
                    id=str(uuid.uuid4()),
                    vector=c["embedding"],
                    payload=payload,
                ))

            client.upsert(collection_name=COLLECTION_NAME, points=points)
            progress.update(task, advance=len(batch))

    # ── 验证 ──
    info = client.get_collection(COLLECTION_NAME)
    console.print(f"\n[bold green]导入完成！[/bold green]")
    console.print(f"  集合名称: {COLLECTION_NAME}")
    console.print(f"  向量总数: {info.points_count:,}")
    console.print(f"  向量维度: 1024")
    console.print(f"  状态:     {info.status}")

    # ── Qdrant 磁盘用量 ──
    console.print(f"\n[dim]提示：Qdrant 数据持久化在 ./qdrant/ 目录[/dim]")


if __name__ == "__main__":
    import_to_qdrant()
