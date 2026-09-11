"""
05_embedding.py — 用 BGE-M3 对 chunk 进行向量化（增量写入版）

优先从本地 models/bge-m3/ 加载模型，不存在则从 HuggingFace 下载并缓存。

优化：逐批写入，避免内存溢出（22K chunks × 1024维 × JSON膨胀 ≈ 500MB+ 峰值）

输入: data/chunks/wiki_chunks.jsonl
输出: data/chunks/wiki_chunks_embedded.jsonl（每行一个 JSON，含 embedding 字段）
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["TOKENIZERS_PARALLELISM"] = "false"

from sentence_transformers import SentenceTransformer

INPUT_FILE = ROOT / "data" / "chunks" / "wiki_chunks.jsonl"
OUTPUT_FILE = ROOT / "data" / "chunks" / "wiki_chunks_embedded.jsonl"
PROGRESS_FILE = ROOT / "data" / "chunks" / ".embed_progress"
LOCAL_MODEL_DIR = ROOT / "models" / "bge-m3"

BATCH_SIZE = 16
SAVE_EVERY_N_BATCHES = 50  # 每50批写一次文件，避免频繁IO


def load_model():
    if LOCAL_MODEL_DIR.exists() and any(LOCAL_MODEL_DIR.iterdir()):
        print(f"[05] 从本地加载 BGE-M3: {LOCAL_MODEL_DIR}")
        return SentenceTransformer(str(LOCAL_MODEL_DIR))
    else:
        print("[05] 本地模型未找到，从 HuggingFace 下载...")
        model = SentenceTransformer("BAAI/bge-m3")
        LOCAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        model.save(str(LOCAL_MODEL_DIR))
        print(f"[05] 模型已缓存到: {LOCAL_MODEL_DIR}")
        return model


def embed_chunks():
    if not INPUT_FILE.exists():
        print("[05] ❌ 未找到 chunk 文件，请先运行 04_chunk_text.py")
        sys.exit(1)

    # ── 加载所有 chunks ──
    print(f"[05] 加载 chunks: {INPUT_FILE}")
    chunks = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    total = len(chunks)
    print(f"[05] Chunk数: {total:,}")

    # ── 加载模型 ──
    print("[05] 加载 BGE-M3 模型...")
    t0 = time.time()
    model = load_model()
    print(f"[05] 模型加载完成 ({time.time() - t0:.0f}s)")

    # ── 检查是否断点续传 ──
    start_idx = 0
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            start_idx = int(f.read().strip())
        if start_idx > 0 and start_idx < total:
            print(f"[05] 🔄 断点续传：从 {start_idx:,} / {total:,} 开始")
        elif start_idx >= total:
            print("[05] ✅ 上次已完成，跳过")
            return

    # ── 打开输出文件（追加模式用于续传） ──
    mode = "a" if start_idx > 0 else "w"
    out_f = open(OUTPUT_FILE, mode, encoding="utf-8")

    # ── 分批向量化 + 增量写入 ──
    texts = [c["content"] for c in chunks]
    batch_count = 0
    processed = start_idx

    print(f"[05] 开始向量化... (batch_size={BATCH_SIZE}, 共 {total:,} chunks)")
    print(f"[05] 进度将每 {SAVE_EVERY_N_BATCHES * BATCH_SIZE} 条更新一次")
    t_start = time.time()

    try:
        i = start_idx
        while i < total:
            batch_end = min(i + BATCH_SIZE, total)
            batch_texts = texts[i:batch_end]

            vecs = model.encode(
                batch_texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

            # 写入当前批次
            for j, vec in enumerate(vecs):
                chunk = chunks[i + j].copy()
                chunk["embedding"] = vec.tolist()
                out_f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

            processed = batch_end
            batch_count += 1

            # 定期刷盘 + 保存进度
            if batch_count % SAVE_EVERY_N_BATCHES == 0:
                out_f.flush()
                os.fsync(out_f.fileno())
                with open(PROGRESS_FILE, "w") as pf:
                    pf.write(str(processed))

                elapsed = time.time() - t_start
                rate = processed / elapsed
                remaining = (total - processed) / rate if rate > 0 else 0
                print(f"[05] 进度: {processed:,}/{total:,} "
                      f"({processed/total*100:.1f}%) | "
                      f"速率: {rate:.0f} chunks/s | "
                      f"预计剩余: {remaining/60:.0f} 分钟")

            i = batch_end

    except KeyboardInterrupt:
        print(f"\n[05] ⚠️ 中断！已保存 {processed:,} 条，下次自动续传")
        out_f.flush()
        os.fsync(out_f.fileno())
        with open(PROGRESS_FILE, "w") as pf:
            pf.write(str(processed))
        out_f.close()
        sys.exit(1)
    except Exception as e:
        print(f"\n[05] ❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        print(f"[05] 已保存 {processed:,} 条，可断点续传")
        out_f.flush()
        os.fsync(out_f.fileno())
        with open(PROGRESS_FILE, "w") as pf:
            pf.write(str(processed))
        out_f.close()
        sys.exit(1)

    out_f.close()

    # 清理进度文件
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()

    elapsed = time.time() - t_start
    dim = len(chunks[0].get("embedding", []))
    out_size_mb = OUTPUT_FILE.stat().st_size / 1024 / 1024

    print(f"\n[05] ✅ Embedding 完成！")
    print(f"[05]   向量总数: {total:,}")
    print(f"[05]   向量维度: {dim}")
    print(f"[05]   总耗时:   {elapsed/60:.0f} 分钟")
    print(f"[05]   平均速率: {total/elapsed:.0f} chunks/s")
    print(f"[05]   输出文件: {OUTPUT_FILE} ({out_size_mb:.0f} MB)")


if __name__ == "__main__":
    embed_chunks()
