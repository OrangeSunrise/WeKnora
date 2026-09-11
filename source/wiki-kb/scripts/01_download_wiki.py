"""
01_download_wiki.py — 下载中文维基百科数据集到本地

数据源: pleisto/wikipedia-cn-20230720-filtered
实际规模: ~25万条中文条目（字段: completion, source）
输出: data/raw/wikipedia-cn/（本地 Arrow 格式）

首次运行需联网下载；下载完成后所有后续脚本可离线使用。
"""
import os
import sys
from pathlib import Path

# 确保能从 wiki-industrial-kb 根目录运行
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datasets import load_dataset

DATASET_NAME = "pleisto/wikipedia-cn-20230720-filtered"
RAW_DIR = ROOT / "data" / "raw" / "wikipedia-cn"


def download():
    """下载数据集并保存到本地磁盘"""

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # 检查是否已下载
    if (RAW_DIR / "dataset_info.json").exists():
        print(f"[01] 数据集已存在于 {RAW_DIR}")
        print("[01] 如需重新下载，请删除该目录后重试")
        return

    print(f"[01] 开始下载数据集：{DATASET_NAME}")
    print("[01] 预计 25万条记录，约 500 MB，请耐心等待...")

    dataset = load_dataset(DATASET_NAME, split="train")

    print(f"[01] 下载完成，共 {len(dataset):,} 条记录")
    print(f"[01] 正在保存到本地：{RAW_DIR}")

    dataset.save_to_disk(str(RAW_DIR))

    print(f"[01] 数据集已保存到：{RAW_DIR}")

    # 打印基本信息
    print(f"\n[01] === 数据集概览 ===")
    print(f"  记录数: {len(dataset):,}")
    print(f"  字段:   {dataset.column_names}")
    if len(dataset) > 0:
        completion = dataset[0].get("completion", "")
        # 取第一行作为标题
        first_line = completion.split("\n")[0][:80] if completion else "N/A"
        print(f"  示例首行: {first_line}")
        print(f"  示例长度: {len(completion)} 字符")
        print(f"  来源:     {dataset[0].get('source', 'N/A')}")


if __name__ == "__main__":
    download()
