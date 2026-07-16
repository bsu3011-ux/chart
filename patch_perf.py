#!/usr/bin/env python3
"""
운영서버 server.py 성능·버그 패치 (멱등 — 여러 번 실행해도 안전)

  ① _clean(): numpy bool_/integer/floating → 파이썬 기본형 변환
     ("Object of type bool_ is not JSON serializable" 랭킹 종목분석 오류 수정)
  ② gzip 압축 + /static/lib 장기 캐시 after_request 추가
     (index.html 235KB→~40KB, babel 3MB→~700KB 전송 — 모바일 로딩 대폭 개선)

사용법:  cd /home/ubuntu/stock-bot && python3 patch_perf.py
적용 후: pkill -f server.py  (run.sh가 3초 뒤 자동 재시작)
"""
import re, shutil, sys

PATH = "server.py"

OLD_CLEAN = '''def _clean(obj):
    """NaN/Infinity → None (JSON 직렬화 안전)"""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj'''

NEW_CLEAN = '''def _clean(obj):
    """NaN/Infinity → None + numpy 타입 → 파이썬 기본형 (JSON 직렬화 안전)"""
    import numpy as _np
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, _np.bool_):
        return bool(obj)
    if isinstance(obj, _np.integer):
        return int(obj)
    if isinstance(obj, _np.floating):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, _np.ndarray):
        return [_clean(v) for v in obj.tolist()]
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj'''

GZIP_BLOCK = '''
# ── [patch_perf] 응답 gzip 압축 + 정적 라이브러리 장기 캐시 ──────────
import gzip as _gzip

_GZ_TYPES = ("text/html", "text/css", "application/json",
             "application/javascript", "text/javascript", "image/svg+xml")
_gz_lib_cache: dict = {}   # {경로: (mtime, gz_bytes)}

@app.after_request
def _compress_and_cache(resp):
    if request.path.startswith("/static/lib/"):
        resp.headers["Cache-Control"] = "public, max-age=604800"
    try:
        if resp.status_code != 200:
            return resp
        if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
            return resp
        ctype = (resp.content_type or "").split(";")[0].strip()
        if ctype not in _GZ_TYPES:
            return resp
        if resp.direct_passthrough:
            data = b"".join(resp.response) if not isinstance(resp.response, (bytes, str)) else resp.response
            if isinstance(data, str):
                data = data.encode("utf-8")
        else:
            data = resp.get_data()
        if len(data) < 1024:
            return resp
        if request.path.startswith("/static/lib/"):
            fpath = os.path.join(BASE_DIR, request.path.lstrip("/"))
            try:
                mt = os.path.getmtime(fpath)
            except OSError:
                mt = 0
            hit = _gz_lib_cache.get(request.path)
            if hit and hit[0] == mt:
                gz = hit[1]
            else:
                gz = _gzip.compress(data, compresslevel=6)
                _gz_lib_cache[request.path] = (mt, gz)
        else:
            gz = _gzip.compress(data, compresslevel=5)
        if len(gz) >= len(data):
            return resp
        resp.direct_passthrough = False
        resp.set_data(gz)
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Content-Length"] = str(len(gz))
        resp.headers.setdefault("Vary", "Accept-Encoding")
    except Exception:
        pass
    return resp
'''


def main():
    src = open(PATH, encoding="utf-8").read()
    shutil.copy(PATH, PATH + ".bak")
    changed = []

    # ① _clean numpy 패치
    if "_np.bool_" in src:
        print("① _clean: 이미 적용됨 — 건너뜀")
    elif OLD_CLEAN in src:
        src = src.replace(OLD_CLEAN, NEW_CLEAN, 1)
        changed.append("① _clean numpy 변환")
    else:
        # 들여쓰기/주석이 조금 달라도 잡히도록 정규식 폴백
        pat = re.compile(r'def _clean\(obj\):.*?\n    return obj', re.S)
        m = pat.search(src)
        if m:
            src = src[:m.start()] + NEW_CLEAN + src[m.end():]
            changed.append("① _clean numpy 변환 (정규식)")
        else:
            print("⚠️ ① _clean 함수를 찾지 못함 — 수동 확인 필요", file=sys.stderr)

    # ② gzip after_request 추가 (CORS(app) 직후)
    if "_compress_and_cache" in src:
        print("② gzip: 이미 적용됨 — 건너뜀")
    else:
        m = re.search(r'^CORS\(app[^\n]*$', src, re.M)
        if m:
            src = src[:m.end()] + "\n" + GZIP_BLOCK + src[m.end():]
            changed.append("② gzip 압축 + lib 캐시")
        else:
            print("⚠️ ② CORS(app) 라인을 찾지 못함 — 수동 확인 필요", file=sys.stderr)

    if changed:
        open(PATH, "w", encoding="utf-8").write(src)
        import py_compile
        py_compile.compile(PATH, doraise=True)
        print("✅ 적용 완료:", ", ".join(changed))
        print("   백업: server.py.bak")
        print("   재시작: pkill -f server.py  (run.sh가 자동 재기동)")
    else:
        print("변경 없음 (이미 모두 적용됨)")


if __name__ == "__main__":
    main()
