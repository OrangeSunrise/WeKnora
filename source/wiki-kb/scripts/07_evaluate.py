"""
07_evaluate.py — 检索评估

评估指标：
  - Recall@K (K=1,3,5,10)
  - MRR (Mean Reciprocal Rank)
  - 平均检索延迟

需先在 data/evaluation/test_questions.json 准备测试问题集。

输入: Qdrant 中的 industrial_wiki 集合
输出: reports/retrieval_report.md
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from rich.console import Console
from rich.table import Table

console = Console()

COLLECTION_NAME = "industrial_wiki"
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
TEST_FILE = ROOT / "data" / "evaluation" / "test_questions.json"
REPORT_DIR = ROOT / "reports"
REPORT_FILE = REPORT_DIR / "retrieval_report.md"

LOCAL_MODEL_DIR = ROOT / "models" / "bge-m3"

# 评价值的 K 值列表
K_VALUES = [1, 3, 5, 10]


def load_model():
    """加载 BGE-M3"""
    if LOCAL_MODEL_DIR.exists() and any(LOCAL_MODEL_DIR.iterdir()):
        model = SentenceTransformer(str(LOCAL_MODEL_DIR))
    else:
        console.print("[yellow]本地模型未找到，在线加载...[/yellow]")
        model = SentenceTransformer("BAAI/bge-m3")
    return model


def generate_sample_questions() -> list[dict]:
    """生成示例测试问题（如果没有测试文件）"""
    questions = [
        # 定义类
        {"question": "什么是矢量控制？", "keywords": ["矢量控制", "电机"], "type": "定义类"},
        {"question": "PLC的工作原理是什么？", "keywords": ["PLC", "可编程逻辑控制器"], "type": "定义类"},
        {"question": "什么是PID控制？", "keywords": ["PID", "比例积分微分"], "type": "定义类"},
        {"question": "变频器的作用是什么？", "keywords": ["变频器", "变频"], "type": "定义类"},
        {"question": "什么是编码器？", "keywords": ["编码器", "encoder"], "type": "定义类"},
        # 参数类
        {"question": "电机的额定功率如何计算？", "keywords": ["额定功率", "电机"], "type": "参数类"},
        {"question": "伺服电机的转速范围是多少？", "keywords": ["伺服电机", "转速"], "type": "参数类"},
        {"question": "变频器的输入电压规格？", "keywords": ["变频器", "电压"], "type": "参数类"},
        {"question": "PROFINET的通信速率？", "keywords": ["PROFINET", "通信"], "type": "参数类"},
        {"question": "接触器的额定电流等级？", "keywords": ["接触器", "额定电流"], "type": "参数类"},
        # 故障类
        {"question": "电机过载保护如何实现？", "keywords": ["过载", "保护", "电机"], "type": "故障类"},
        {"question": "变频器常见故障有哪些？", "keywords": ["变频器", "故障"], "type": "故障类"},
        {"question": "伺服电机振动过大的原因？", "keywords": ["伺服", "振动", "电机"], "type": "故障类"},
        {"question": "PLC通讯故障如何排查？", "keywords": ["PLC", "通讯", "故障"], "type": "故障类"},
        {"question": "编码器信号丢失怎么办？", "keywords": ["编码器", "信号"], "type": "故障类"},
        # 原理类
        {"question": "PWM调制的基本原理？", "keywords": ["PWM", "脉宽调制"], "type": "原理类"},
        {"question": "闭环控制和开环控制的区别？", "keywords": ["闭环", "开环", "控制"], "type": "原理类"},
        {"question": "CAN总线通信原理？", "keywords": ["CAN", "总线"], "type": "原理类"},
        {"question": "异步电机的工作原理？", "keywords": ["异步电机", "感应电机"], "type": "原理类"},
        {"question": "IGBT的工作原理？", "keywords": ["IGBT", "绝缘栅"], "type": "原理类"},
        # 应用类
        {"question": "伺服系统在数控机床中的应用？", "keywords": ["伺服", "数控机床"], "type": "应用类"},
        {"question": "SCADA系统在电力行业的应用？", "keywords": ["SCADA", "电力"], "type": "应用类"},
        {"question": "机器视觉在工业检测中的应用？", "keywords": ["机器视觉", "检测"], "type": "应用类"},
        {"question": "Modbus协议在楼宇自动化中的应用？", "keywords": ["Modbus", "楼宇自动化"], "type": "应用类"},
        {"question": "传感器在智能工厂中的应用？", "keywords": ["传感器", "智能工厂"], "type": "应用类"},
    ]
    return questions


def load_test_questions() -> list[dict]:
    """加载测试问题集"""
    if TEST_FILE.exists():
        with open(TEST_FILE, encoding="utf-8") as f:
            questions = json.load(f)
        console.print(f"[green]加载测试问题: {len(questions)} 条[/green]")
        return questions
    else:
        console.print("[yellow]未找到测试文件，使用自动生成的示例问题[/yellow]")
        questions = generate_sample_questions()
        # 保存以便用户编辑
        TEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TEST_FILE, "w", encoding="utf-8") as f:
            json.dump(questions, f, ensure_ascii=False, indent=2)
        console.print(f"[dim]示例问题已保存至: {TEST_FILE}[/dim]")
        return questions


def evaluate():
    # 连接 Qdrant
    console.print(f"[bold cyan]连接 Qdrant ({QDRANT_HOST}:{QDRANT_PORT})...[/bold cyan]")
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        info = client.get_collection(COLLECTION_NAME)
        console.print(f"  集合 '{COLLECTION_NAME}': {info.points_count:,} 条记录\n")
    except Exception as e:
        console.print(f"[red]连接失败: {e}[/red]")
        console.print("[yellow]请先启动 Qdrant 并运行 06_qdrant_import.py[/yellow]")
        sys.exit(1)

    # 加载模型
    console.print("[bold cyan]加载 BGE-M3 模型...[/bold cyan]")
    model = load_model()

    # 加载问题
    questions = load_test_questions()

    # ── 执行评估 ──
    console.print(f"\n[bold]开始检索评估... (共 {len(questions)} 个问题)[/bold]\n")

    max_k = max(K_VALUES)
    latencies = []
    recall_hits = {k: 0 for k in K_VALUES}
    reciprocal_ranks = []
    total = len(questions)

    for i, q in enumerate(questions):
        question = q["question"]
        keywords = q.get("keywords", [])
        qtype = q.get("type", "未知")

        # 向量化查询
        query_vec = model.encode(question, normalize_embeddings=True).tolist()

        # 计时检索
        start = time.perf_counter()
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vec,
            limit=max_k,
            with_payload=True,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)

        # 检查命中
        hits = response.points
        hit_positions = []

        for rank, hit in enumerate(hits):
            title = (hit.payload or {}).get("title", "")
            content = (hit.payload or {}).get("content", "")

            # 判断是否相关：标题或正文包含任一关键词
            relevant = any(
                kw.lower() in title.lower() or kw.lower() in content.lower()
                for kw in keywords
            )
            if relevant:
                hit_positions.append(rank + 1)  # 1-indexed

        # 计算 Recall@K
        for k in K_VALUES:
            if any(pos <= k for pos in hit_positions):
                recall_hits[k] += 1

        # 计算 RR
        if hit_positions:
            reciprocal_ranks.append(1.0 / hit_positions[0])
        else:
            reciprocal_ranks.append(0.0)

        # 进度
        if (i + 1) % 5 == 0 or i == total - 1:
            console.print(f"  进度: {i + 1}/{total}")

    # ── 汇总指标 ──
    avg_latency = sum(latencies) / len(latencies)
    p50_latency = sorted(latencies)[len(latencies) // 2]
    p99_latency = sorted(latencies)[int(len(latencies) * 0.99)]

    recall_results = {}
    for k in K_VALUES:
        recall_results[k] = recall_hits[k] / total

    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)

    # ── 终端输出 ──
    console.print(f"\n[bold green]评估完成！[/bold green]\n")

    # Recall 表
    recall_table = Table(title="Recall@K")
    recall_table.add_column("K", style="cyan")
    recall_table.add_column("命中数", style="green")
    recall_table.add_column("Recall", style="yellow")
    for k in K_VALUES:
        recall_table.add_row(
            f"@{k}", f"{recall_hits[k]}/{total}",
            f"{recall_results[k]:.1%}"
        )
    console.print(recall_table)

    # MRR & 延迟
    perf_table = Table(title="检索性能")
    perf_table.add_column("指标", style="cyan")
    perf_table.add_column("值", style="green")
    perf_table.add_row("MRR", f"{mrr:.4f}")
    perf_table.add_row("平均延迟", f"{avg_latency:.1f} ms")
    perf_table.add_row("P50 延迟", f"{p50_latency:.1f} ms")
    perf_table.add_row("P99 延迟", f"{p99_latency:.1f} ms")
    console.print(perf_table)

    # ── 按类型统计 ──
    type_stats = {}
    for q, rr in zip(questions, reciprocal_ranks):
        qtype = q.get("type", "未知")
        if qtype not in type_stats:
            type_stats[qtype] = {"count": 0, "hits": 0, "rrs": []}
        type_stats[qtype]["count"] += 1
        type_stats[qtype]["rrs"].append(rr)
        if rr > 0:
            type_stats[qtype]["hits"] += 1

    type_table = Table(title="按问题类型统计")
    type_table.add_column("类型", style="cyan")
    type_table.add_column("数量", style="green")
    type_table.add_column("MRR", style="yellow")
    type_table.add_column("命中率", style="magenta")
    for qtype in sorted(type_stats.keys()):
        ts = type_stats[qtype]
        type_mrr = sum(ts["rrs"]) / len(ts["rrs"])
        type_table.add_row(
            qtype, str(ts["count"]), f"{type_mrr:.4f}",
            f"{ts['hits']/ts['count']:.1%}"
        )
    console.print(type_table)

    # ── 生成报告 ──
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = f"""# 检索评估报告

> 数据来源: pleisto/wikipedia-cn-20230720-filtered
> 集合: {COLLECTION_NAME} ({info.points_count:,} 条)
> 测试问题: {total} 条

---

## Recall@K

| K | 命中数 | Recall |
|---|-------:|-------:|
"""
    for k in K_VALUES:
        report += f"| {k} | {recall_hits[k]}/{total} | {recall_results[k]:.1%} |\n"

    report += f"""
---

## MRR & 延迟

| 指标 | 值 |
|------|----:|
| MRR | {mrr:.4f} |
| 平均延迟 | {avg_latency:.1f} ms |
| P50 延迟 | {p50_latency:.1f} ms |
| P99 延迟 | {p99_latency:.1f} ms |

---

## 按问题类型

| 类型 | 数量 | MRR | 命中率 |
|------|-----:|----:|-------:|
"""
    for qtype in sorted(type_stats.keys()):
        ts = type_stats[qtype]
        type_mrr = sum(ts["rrs"]) / len(ts["rrs"])
        report += f"| {qtype} | {ts['count']} | {type_mrr:.4f} | {ts['hits']/ts['count']:.1%} |\n"

    report += f"""
---

## 目标达成情况

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|:----:|
| Recall@5 | >85% | {recall_results[5]:.1%} | {'✅' if recall_results[5] > 0.85 else '⚠️'} |
| MRR | >0.75 | {mrr:.4f} | {'✅' if mrr > 0.75 else '⚠️'} |
| 平均延迟 | <200ms | {avg_latency:.1f}ms | {'✅' if avg_latency < 200 else '⚠️'} |
"""

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    console.print(f"\n[dim]报告已保存至: {REPORT_FILE}[/dim]")


if __name__ == "__main__":
    evaluate()
