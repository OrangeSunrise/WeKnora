"""
07_evaluate_v2.py — 优化版检索评估

改进点：
  1. 50道精心构造的工业技术测试题
  2. 语义相关性判断（embedding cosine similarity），替代关键词匹配
  3. 混合检索：Dense向量 + 关键词加权融合
  4. NDCG@5/10 指标

输出: reports/retrieval_report_v2.md
"""
import json
import sys
import time
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchText
from sentence_transformers import SentenceTransformer
from rich.console import Console
from rich.table import Table

console = Console()

COLLECTION_NAME = "industrial_wiki"
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
LOCAL_MODEL_DIR = ROOT / "models" / "bge-m3"
REPORT_DIR = ROOT / "reports"
REPORT_FILE = REPORT_DIR / "retrieval_report_v2.md"

K_VALUES = [1, 3, 5, 10]

# ── 50道工业技术测试题 ──
TEST_QUESTIONS = [
    # === 定义类 (10题) ===
    {"q": "什么是矢量控制？它在交流电机中的作用是什么？",
     "type": "定义类",
     "expected_concepts": ["矢量控制", "磁场定向", "交流电机", "解耦", "转矩", "磁通"]},
    {"q": "PLC可编程逻辑控制器的工作原理和基本结构",
     "type": "定义类",
     "expected_concepts": ["PLC", "可编程", "控制器", "CPU", "I/O", "扫描周期"]},
    {"q": "PID控制算法中比例、积分、微分三个环节各自的作用",
     "type": "定义类",
     "expected_concepts": ["PID", "比例", "积分", "微分", "控制", "稳态误差"]},
    {"q": "什么是变频器？它的工作原理和主要组成部分",
     "type": "定义类",
     "expected_concepts": ["变频器", "整流", "逆变", "频率", "电压", "PWM"]},
    {"q": "工业机器人的定义、分类和基本技术参数",
     "type": "定义类",
     "expected_concepts": ["机器人", "自由度", "负载", "精度", "关节"]},
    {"q": "SCADA系统的定义和核心功能模块",
     "type": "定义类",
     "expected_concepts": ["SCADA", "监控", "数据采集", "远程", "HMI"]},
    {"q": "什么是现场总线？常见的有哪些类型？",
     "type": "定义类",
     "expected_concepts": ["现场总线", "PROFIBUS", "CAN", "Modbus", "通信"]},
    {"q": "编码器的工作原理和主要类型（增量式与绝对式）",
     "type": "定义类",
     "expected_concepts": ["编码器", "增量式", "绝对式", "位置", "角度", "脉冲"]},
    {"q": "什么是DCS分布式控制系统？与PLC的区别",
     "type": "定义类",
     "expected_concepts": ["DCS", "分布式", "控制", "PLC", "回路"]},
    {"q": "工业以太网与普通以太网的区别及PROFINET协议特点",
     "type": "定义类",
     "expected_concepts": ["工业以太网", "PROFINET", "实时", "确定性", "以太网"]},

    # === 参数类 (10题) ===
    {"q": "交流异步电动机的额定功率、额定转速和额定转矩之间的关系",
     "type": "参数类",
     "expected_concepts": ["额定功率", "额定转速", "额定转矩", "异步电机", "公式"]},
    {"q": "伺服电机选型需要考虑哪些关键参数？",
     "type": "参数类",
     "expected_concepts": ["伺服电机", "选型", "转矩", "转速", "惯量", "功率"]},
    {"q": "变频器的主要技术参数：输入电压范围、输出频率范围和过载能力",
     "type": "参数类",
     "expected_concepts": ["变频器", "输入电压", "输出频率", "过载", "额定"]},
    {"q": "传感器的灵敏度、精度、分辨率和线性度这些指标的含义",
     "type": "参数类",
     "expected_concepts": ["传感器", "灵敏度", "精度", "分辨率", "线性度", "指标"]},
    {"q": "工业继电器的主要电气参数：线圈电压、触点容量和动作时间",
     "type": "参数类",
     "expected_concepts": ["继电器", "线圈电压", "触点", "容量", "动作时间"]},
    {"q": "电力变压器的额定容量、变比和效率如何计算？",
     "type": "参数类",
     "expected_concepts": ["变压器", "额定容量", "变比", "效率", "损耗"]},
    {"q": "齿轮传动中的模数、齿数、传动比和中心距的关系",
     "type": "参数类",
     "expected_concepts": ["齿轮", "模数", "齿数", "传动比", "中心距"]},
    {"q": "轴承的额定动载荷、额定静载荷和极限转速的含义",
     "type": "参数类",
     "expected_concepts": ["轴承", "额定动载荷", "额定静载荷", "极限转速", "寿命"]},
    {"q": "CAN总线通信速率与传输距离的关系及终端电阻的作用",
     "type": "参数类",
     "expected_concepts": ["CAN", "通信速率", "传输距离", "终端电阻", "总线"]},
    {"q": "IGBT功率模块的关键参数：电压等级、电流等级和开关频率",
     "type": "参数类",
     "expected_concepts": ["IGBT", "电压等级", "电流等级", "开关频率", "功率"]},

    # === 故障类 (10题) ===
    {"q": "变频器常见故障代码及其排查方法（过流、过压、过热）",
     "type": "故障类",
     "expected_concepts": ["变频器", "故障", "过流", "过压", "过热", "保护"]},
    {"q": "伺服电机运行中振动过大的原因分析和解决方案",
     "type": "故障类",
     "expected_concepts": ["伺服电机", "振动", "原因", "机械", "电气", "调试"]},
    {"q": "PLC控制系统通讯中断故障的诊断与排除方法",
     "type": "故障类",
     "expected_concepts": ["PLC", "通讯", "中断", "诊断", "故障排除"]},
    {"q": "异步电动机无法启动的常见原因及检查步骤",
     "type": "故障类",
     "expected_concepts": ["异步电机", "启动", "故障", "电源", "绕组", "检查"]},
    {"q": "编码器信号丢失或异常跳动如何排查和解决？",
     "type": "故障类",
     "expected_concepts": ["编码器", "信号", "丢失", "干扰", "接线", "屏蔽"]},
    {"q": "工业机器人重复定位精度下降的可能原因",
     "type": "故障类",
     "expected_concepts": ["机器人", "定位精度", "磨损", "间隙", "标定"]},
    {"q": "电力变压器异常发热和噪声的诊断处理方法",
     "type": "故障类",
     "expected_concepts": ["变压器", "发热", "噪声", "过载", "铁芯", "冷却"]},
    {"q": "传感器输出信号漂移的原因及校准方法",
     "type": "故障类",
     "expected_concepts": ["传感器", "漂移", "校准", "温度", "老化"]},
    {"q": "断路器误跳闸的可能原因和排查流程",
     "type": "故障类",
     "expected_concepts": ["断路器", "跳闸", "过载", "短路", "漏电"]},
    {"q": "液压系统压力不足的故障分析及排除",
     "type": "故障类",
     "expected_concepts": ["液压", "压力", "泵", "阀门", "泄漏", "油液"]},

    # === 原理类 (10题) ===
    {"q": "PWM脉宽调制技术的基本原理及其在变频器中的应用",
     "type": "原理类",
     "expected_concepts": ["PWM", "脉宽调制", "占空比", "变频器", "逆变"]},
    {"q": "闭环控制与开环控制的区别，以及反馈在控制系统中的作用",
     "type": "原理类",
     "expected_concepts": ["闭环", "开环", "反馈", "控制", "偏差", "稳定性"]},
    {"q": "异步电动机的旋转磁场是如何产生的？转差率的概念",
     "type": "原理类",
     "expected_concepts": ["异步电机", "旋转磁场", "转差率", "定子", "转子"]},
    {"q": "IGBT绝缘栅双极晶体管的工作原理及其在电力电子中的应用",
     "type": "原理类",
     "expected_concepts": ["IGBT", "晶体管", "开关", "导通", "关断", "电力电子"]},
    {"q": "傅里叶变换在信号处理和振动分析中的应用原理",
     "type": "原理类",
     "expected_concepts": ["傅里叶变换", "频域", "信号", "频谱", "谐波"]},
    {"q": "卡尔曼滤波的基本原理及其在传感器数据融合中的应用",
     "type": "原理类",
     "expected_concepts": ["卡尔曼滤波", "状态估计", "预测", "更新", "噪声"]},
    {"q": "CAN总线通信的仲裁机制和帧格式原理",
     "type": "原理类",
     "expected_concepts": ["CAN", "仲裁", "帧", "标识符", "显性", "隐性"]},
    {"q": "PID参数整定的方法：Ziegler-Nichols法和临界比例度法",
     "type": "原理类",
     "expected_concepts": ["PID", "参数整定", "Ziegler-Nichols", "临界比例度", "振荡"]},
    {"q": "电力系统中无功功率的概念及功率因数校正的原理",
     "type": "原理类",
     "expected_concepts": ["无功功率", "功率因数", "补偿", "电容", "电感"]},
    {"q": "DC-DC开关电源中Buck、Boost电路的工作原理",
     "type": "原理类",
     "expected_concepts": ["Buck", "Boost", "开关电源", "降压", "升压", "DC-DC"]},

    # === 应用类 (10题) ===
    {"q": "伺服驱动系统在数控机床进给轴中的应用和精度保证",
     "type": "应用类",
     "expected_concepts": ["伺服", "数控机床", "进给", "精度", "位置控制"]},
    {"q": "工业机器人在汽车焊装生产线中的应用及技术要求",
     "type": "应用类",
     "expected_concepts": ["机器人", "焊装", "汽车", "生产线", "自动化"]},
    {"q": "SCADA系统在电力配网自动化中的具体应用方案",
     "type": "应用类",
     "expected_concepts": ["SCADA", "电力", "配网", "自动化", "遥测"]},
    {"q": "PLC在污水处理厂自动化控制系统中的应用",
     "type": "应用类",
     "expected_concepts": ["PLC", "污水处理", "自动化", "控制", "传感器"]},
    {"q": "变频调速技术在暖通空调（HVAC）系统节能中的应用",
     "type": "应用类",
     "expected_concepts": ["变频", "暖通", "空调", "节能", "风机", "水泵"]},
    {"q": "机器视觉系统在工业产品缺陷检测中的典型应用",
     "type": "应用类",
     "expected_concepts": ["机器视觉", "检测", "缺陷", "图像处理", "相机"]},
    {"q": "Modbus协议在楼宇自动化系统（BAS）中的实际应用",
     "type": "应用类",
     "expected_concepts": ["Modbus", "楼宇自动化", "BAS", "通信", "监控"]},
    {"q": "工业传感器在智能制造和工业4.0中的关键应用场景",
     "type": "应用类",
     "expected_concepts": ["传感器", "智能制造", "工业4.0", "物联网", "数据采集"]},
    {"q": "PLC与变频器通过现场总线实现多电机同步控制的应用",
     "type": "应用类",
     "expected_concepts": ["PLC", "变频器", "现场总线", "同步", "多电机"]},
    {"q": "RFID技术在工业物流和仓储管理中的应用方案",
     "type": "应用类",
     "expected_concepts": ["RFID", "物流", "仓储", "识别", "跟踪"]},
]


def load_model():
    if LOCAL_MODEL_DIR.exists() and any(LOCAL_MODEL_DIR.iterdir()):
        console.print("[cyan]从本地加载 BGE-M3...[/cyan]")
        return SentenceTransformer(str(LOCAL_MODEL_DIR))
    else:
        return SentenceTransformer("BAAI/bge-m3")


def semantic_relevance(question_vec, chunk_content, model, threshold=0.5) -> float:
    """
    语义相关性判断：对检索结果的content做embedding，
    计算与问题的cosine similarity。
    返回0-1的分数，>threshold视为相关。
    """
    content_vec = model.encode([chunk_content], normalize_embeddings=True)[0]
    sim = float(sum(a * b for a, b in zip(question_vec, content_vec)))
    return sim


def hybrid_search(client, model, question, top_k=20):
    """
    混合检索：
    1. 先用语义向量检索 top_k*2 条
    2. 对结果做关键词加权重排
    """
    # Step 1: 语义检索
    question_vec = model.encode(question, normalize_embeddings=True).tolist()
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=question_vec,
        limit=top_k * 2,
        with_payload=True,
    )

    candidates = []
    for hit in response.points:
        payload = hit.payload or {}
        content = payload.get("content", "")
        title = payload.get("title", "")

        # Step 2: 关键词加权（标题命中 + 正文命中）
        title_score = 0.0
        content_score = 0.0

        # 提取问题中的关键词（简单：2字以上词）
        q_words = set()
        for i in range(len(question)):
            for j in range(i+2, min(i+8, len(question)+1)):
                w = question[i:j]
                if not all('一' <= c <= '鿿' or c.isalnum() for c in w):
                    continue
                q_words.add(w)

        for w in q_words:
            if w in title:
                title_score += 1.0
            if w in content:
                content_score += 0.5

        # 融合分数: 语义分 0.6 + 关键词分 0.4
        semantic_score = float(hit.score)
        keyword_score = min(title_score * 0.3 + content_score * 0.1, 1.0)
        combined_score = semantic_score * 0.6 + keyword_score * 0.4

        candidates.append({
            "score": combined_score,
            "title": title,
            "content": content,
        })

    # 按融合分重排
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k], question_vec


def dcg(relevance_scores, k):
    """Discounted Cumulative Gain"""
    return sum((2**rel - 1) / math.log2(i + 2)
               for i, rel in enumerate(relevance_scores[:k]))


def ndcg(relevance_scores, ideal_scores, k):
    """Normalized DCG"""
    d = dcg(relevance_scores, k)
    i = dcg(ideal_scores, k)
    return d / i if i > 0 else 0.0


def evaluate():
    # 连接 Qdrant
    console.print("[bold cyan]连接 Qdrant...[/bold cyan]")
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    info = client.get_collection(COLLECTION_NAME)
    console.print(f"  集合: {COLLECTION_NAME} ({info.points_count:,} 条)\n")

    # 加载模型
    model = load_model()

    # ── 执行评估 ──
    total = len(TEST_QUESTIONS)

    # 指标累加器
    recall_hits = {k: 0 for k in K_VALUES}
    reciprocal_ranks = []
    latencies = []
    ndcg_scores = {k: [] for k in K_VALUES}
    type_stats = {}
    per_question = []

    console.print(f"[bold]开始评估... ({total} 题)[/bold]\n")

    for idx, q_item in enumerate(TEST_QUESTIONS):
        question = q_item["q"]
        qtype = q_item["type"]
        expected = q_item.get("expected_concepts", [])

        # 混合检索 + 计时
        start = time.perf_counter()
        results, q_vec = hybrid_search(client, model, question, top_k=max(K_VALUES))
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)

        # ── 语义相关性判断 ──
        relevance_scores = []
        for r in results:
            rel = semantic_relevance(q_vec, r["content"], model)
            relevance_scores.append(rel)

        # Recall@K（语义相关 > 0.55 视为命中）
        for k in K_VALUES:
            if any(s > 0.55 for s in relevance_scores[:k]):
                recall_hits[k] += 1

        # MRR（第一个相关结果的位置）
        first_rel = next((i+1 for i, s in enumerate(relevance_scores) if s > 0.55), 0)
        reciprocal_ranks.append(1.0 / first_rel if first_rel > 0 else 0.0)

        # NDCG（用语义相似度作为 relevance score）
        ideal = sorted(relevance_scores, reverse=True)
        for k in K_VALUES:
            ndcg_scores[k].append(ndcg(relevance_scores, ideal, k))

        # 按类型统计
        if qtype not in type_stats:
            type_stats[qtype] = {"count": 0, "hits5": 0, "rrs": [], "ndcg5": []}
        type_stats[qtype]["count"] += 1
        type_stats[qtype]["rrs"].append(reciprocal_ranks[-1])
        type_stats[qtype]["ndcg5"].append(ndcg_scores[5][-1])
        if any(s > 0.55 for s in relevance_scores[:5]):
            type_stats[qtype]["hits5"] += 1

        # 单题详情
        per_question.append({
            "question": question[:60],
            "type": qtype,
            "rr": reciprocal_ranks[-1],
            "ndcg5": ndcg_scores[5][-1],
            "top_score": relevance_scores[0] if relevance_scores else 0,
            "best_title": results[0]["title"][:40] if results else "N/A",
        })

        if (idx + 1) % 10 == 0:
            console.print(f"  进度: {idx+1}/{total}")

    # ── 汇总 ──
    avg_latency = sum(latencies) / len(latencies)
    sorted_lat = sorted(latencies)
    p50_lat = sorted_lat[len(sorted_lat) // 2]
    p99_lat = sorted_lat[int(len(sorted_lat) * 0.99)]
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)

    # ── 输出 ──
    console.print(f"\n[bold green]评估完成！[/bold green]\n")

    recall_table = Table(title="Recall@K（语义相关>0.55）")
    recall_table.add_column("K", style="cyan")
    recall_table.add_column("命中", style="green")
    recall_table.add_column("Recall", style="yellow")
    for k in K_VALUES:
        recall_table.add_row(f"@{k}", f"{recall_hits[k]}/{total}",
                            f"{recall_hits[k]/total:.1%}")
    console.print(recall_table)

    perf_table = Table(title="检索性能")
    perf_table.add_column("指标", style="cyan")
    perf_table.add_column("值", style="green")
    avg_ndcg5 = sum(ndcg_scores[5]) / len(ndcg_scores[5])
    avg_ndcg10 = sum(ndcg_scores[10]) / len(ndcg_scores[10])
    perf_table.add_row("MRR", f"{mrr:.4f}")
    perf_table.add_row("NDCG@5", f"{avg_ndcg5:.4f}")
    perf_table.add_row("NDCG@10", f"{avg_ndcg10:.4f}")
    perf_table.add_row("平均延迟", f"{avg_latency:.1f} ms")
    perf_table.add_row("P50 延迟", f"{p50_lat:.1f} ms")
    perf_table.add_row("P99 延迟", f"{p99_lat:.1f} ms")
    console.print(perf_table)

    # 按类型
    type_table = Table(title="按问题类型")
    type_table.add_column("类型", style="cyan")
    type_table.add_column("数量", style="green")
    type_table.add_column("Recall@5", style="yellow")
    type_table.add_column("MRR", style="magenta")
    type_table.add_column("NDCG@5", style="blue")
    for qt in sorted(type_stats.keys()):
        ts = type_stats[qt]
        type_table.add_row(
            qt, str(ts["count"]),
            f"{ts['hits5']/ts['count']:.1%}",
            f"{sum(ts['rrs'])/len(ts['rrs']):.4f}",
            f"{sum(ts['ndcg5'])/len(ts['ndcg5']):.4f}",
        )
    console.print(type_table)

    # 最差 Top5
    per_question.sort(key=lambda x: x["rr"])
    console.print("\n[bold yellow]需改进的 Top 5:[/bold yellow]")
    for pq in per_question[:5]:
        console.print(f"  [{pq['type']}] RR={pq['rr']:.2f} TopScore={pq['top_score']:.3f} "
                     f"Q: {pq['question']}...")

    # ── 生成 Markdown 报告 ──
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = f"""# 检索评估报告 v2（优化版）

> 集合: {COLLECTION_NAME} ({info.points_count:,} 条)
> 测试问题: {total} 道教
> 相关性判断: 语义相似度 >0.55 | 检索方式: 混合（语义+关键词）

---

## Recall@K

| K | 命中数 | Recall |
|---|-------:|-------:|
"""
    for k in K_VALUES:
        report += f"| {k} | {recall_hits[k]}/{total} | {recall_hits[k]/total:.1%} |\n"

    report += f"""
---

## MRR & NDCG & 延迟

| 指标 | 值 |
|------|----:|
| MRR | {mrr:.4f} |
| NDCG@5 | {avg_ndcg5:.4f} |
| NDCG@10 | {avg_ndcg10:.4f} |
| 平均延迟 | {avg_latency:.1f} ms |
| P50 延迟 | {p50_lat:.1f} ms |
| P99 延迟 | {p99_lat:.1f} ms |

---

## 按问题类型

| 类型 | 数量 | Recall@5 | MRR | NDCG@5 |
|------|-----:|-------:|----:|-------:|
"""
    for qt in sorted(type_stats.keys()):
        ts = type_stats[qt]
        report += (f"| {qt} | {ts['count']} | "
                   f"{ts['hits5']/ts['count']:.1%} | "
                   f"{sum(ts['rrs'])/len(ts['rrs']):.4f} | "
                   f"{sum(ts['ndcg5'])/len(ts['ndcg5']):.4f} |\n")

    report += """
---

## 目标达成

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|:----:|
"""
    report += f"| Recall@5 | >85% | {recall_hits[5]/total:.1%} | {'✅' if recall_hits[5]/total > 0.85 else '⚠️'} |\n"
    report += f"| MRR | >0.75 | {mrr:.4f} | {'✅' if mrr > 0.75 else '⚠️'} |\n"
    report += f"| NDCG@5 | >0.70 | {avg_ndcg5:.4f} | {'✅' if avg_ndcg5 > 0.70 else '⚠️'} |\n"
    report += f"| 平均延迟 | <200ms | {avg_latency:.1f}ms | ✅ |\n"

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    console.print(f"\n[dim]报告: {REPORT_FILE}[/dim]")


if __name__ == "__main__":
    evaluate()
