#!/usr/bin/env python3
"""批量把目录下的文档导入 WeKnora 知识库，并可选等待索引完成。

只用标准库，不需要 pip 安装任何东西。中文文件名通过 multipart 的 fileName 字段
以显式 UTF-8 传递，避开 Windows 命令行 argv 按 ANSI 代码页传参导致的
「文件名包含非法字符」问题（见 document/问题与解决.md 第三章）。

用法：
    python delivery/scripts/import_kb.py --kb <知识库ID> --dir delivery/kb-corpus/imported-300
    python delivery/scripts/import_kb.py --kb <知识库ID> --dir <目录> --wait

取知识库 ID：GET /api/v1/knowledge-bases，或在界面地址栏中查看。
导入前请确认 WEKNORA_MODEL_MAX_CONCURRENCY 已调小（单机建议 2），否则摘要任务
会把 Ollama 队列堵满，期间任何提问都要排队数分钟。
"""
import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request

BOUNDARY = "----WeKnoraImportBoundary7MA4YWxkTrZu0gW"


def call(base, path, data=None, token=None, method=None, content_type=None, timeout=300):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if content_type:
        headers["Content-Type"] = content_type
    elif data is not None:
        headers["Content-Type"] = "application/json"
    body = data
    if isinstance(data, (dict, list)):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + path, data=body, headers=headers,
                                method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip().startswith(("{", "[")) else {"raw": raw}


def get_token(base):
    """Lite 形态用 /auth/auto-setup 免密取令牌。"""
    d = call(base, "/api/v1/auth/auto-setup", {})

    def find(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("token", "access_token") and isinstance(v, str) and len(v) > 20:
                    return v
                r = find(v)
                if r:
                    return r
        if isinstance(o, list):
            for v in o:
                r = find(v)
                if r:
                    return r
        return None
    tok = find(d)
    if not tok:
        sys.exit("取令牌失败，请确认服务已启动且为 lite 版本：%s" % json.dumps(d)[:200])
    return tok


def build_multipart(path, filename):
    """手工拼 multipart，filename 以 UTF-8 字节写入，避免编码转换。"""
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        content = f.read()
    parts = []
    parts.append(("--%s\r\n" % BOUNDARY).encode())
    parts.append(('Content-Disposition: form-data; name="file"; filename="%s"\r\n'
                  % filename).encode("utf-8"))
    parts.append(("Content-Type: %s\r\n\r\n" % ctype).encode())
    parts.append(content)
    parts.append(("\r\n--%s\r\n" % BOUNDARY).encode())
    parts.append(b'Content-Disposition: form-data; name="fileName"\r\n\r\n')
    parts.append(filename.encode("utf-8"))
    parts.append(("\r\n--%s--\r\n" % BOUNDARY).encode())
    return b"".join(parts)


def wait_until_indexed(base, token, poll=15):
    """轮询直到所有文档 summary_status 为 completed。"""
    print("等待索引完成（每 %ds 查询一次，Ctrl+C 可中断，中断不影响后台任务）" % poll)
    while True:
        d = call(base, "/api/v1/knowledge-bases", token=token)
        items = d.get("data") or []
        total = pending = 0
        for kb in items if isinstance(items, list) else []:
            kid = kb.get("id")
            k = call(base, "/api/v1/knowledge-bases/%s/knowledge?page=1&page_size=1000" % kid,
                     token=token)
            for row in (k.get("data") or []):
                total += 1
                if row.get("summary_status") != "completed":
                    pending += 1
        print("  共 %d 篇，未完成 %d 篇" % (total, pending))
        if total and pending == 0:
            print("索引全部完成。")
            return
        time.sleep(poll)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", required=True, help="知识库 ID")
    ap.add_argument("--dir", required=True, help="待导入目录")
    ap.add_argument("--base", default="http://127.0.0.1:8080", help="服务地址")
    ap.add_argument("--token", default="", help="手动指定令牌，默认走免密取令牌")
    ap.add_argument("--ext", default=".md", help="只导入该扩展名，默认 .md")
    ap.add_argument("--wait", action="store_true", help="导入后等待索引完成")
    a = ap.parse_args()

    token = a.token or get_token(a.base)
    files = sorted(f for f in os.listdir(a.dir) if f.endswith(a.ext))
    if not files:
        sys.exit("目录中没有 %s 文件：%s" % (a.ext, a.dir))
    print("准备导入 %d 个文件到知识库 %s" % (len(files), a.kb))

    ok = fail = 0
    for i, name in enumerate(files, 1):
        body = build_multipart(os.path.join(a.dir, name), name)
        try:
            call(a.base, "/api/v1/knowledge-bases/%s/knowledge/file" % a.kb, data=body,
                 token=token, content_type="multipart/form-data; boundary=%s" % BOUNDARY)
            ok += 1
            print("  [%d/%d] OK   %s" % (i, len(files), name))
        except urllib.error.HTTPError as e:
            fail += 1
            print("  [%d/%d] FAIL %s -> HTTP %s %s"
                  % (i, len(files), name, e.code, e.read().decode("utf-8", "replace")[:160]))
        except Exception as e:
            fail += 1
            print("  [%d/%d] FAIL %s -> %s" % (i, len(files), name, e))

    print("导入完成：成功 %d，失败 %d" % (ok, fail))
    if a.wait:
        wait_until_indexed(a.base, token)


if __name__ == "__main__":
    main()
