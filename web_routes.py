"""안드로이드 앱(TWA) 준비용 웹 경로.

- /manifest.json : 설치형 웹앱 정보 (Gradio 기본 manifest를 덮어씀 — 이름·색·시작 주소·마스커블 아이콘)
- /app-static/<파일> : 앱 아이콘
- /privacy : 개인정보처리방침
- /.well-known/assetlinks.json : 앱과 사이트 연결 (Play 서명 지문을 받은 뒤 Space 설정값으로 켬)

Gradio를 띄운 뒤(launch) 경로를 Gradio 경로보다 앞에 끼워 넣는다.
ZeroGPU는 gr.Blocks.launch를 감싸 GPU 함수를 등록하므로 FastAPI 앱을 따로 띄우지 않고 이 방식을 쓴다.
"""
from __future__ import annotations

import html
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

STATIC = Path(__file__).resolve().parent / "static"
APP_NAME = "고지서 쉽게 보기"
SHORT_NAME = "고지서 쉽게"
THEME = "#1F4E79"
ICON_FILES = {"icon-192.png", "icon-512.png", "icon-maskable-512.png", "feature-graphic-1024x500.png"}


def manifest() -> dict:
    return {
        "id": "/?app=1",
        "name": APP_NAME,
        "short_name": SHORT_NAME,
        "description": "고지서·공문 사진을 찍으면 무엇을, 언제까지, 얼마를 해야 하는지 쉽게 알려 줘요.",
        "lang": "ko",
        "start_url": "/?app=1",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": THEME,
        "theme_color": THEME,
        "icons": [
            {"src": "/app-static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/app-static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/app-static/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }


def assetlinks() -> list | None:
    """Space 설정값 ANDROID_PACKAGE(예: io.github.sangmoo.easynotice)와
    ANDROID_SHA256(Play Console의 앱 서명 키 SHA-256, 여러 개면 쉼표)이 있을 때만 만든다."""
    package = (os.getenv("ANDROID_PACKAGE") or "").strip()
    prints = [p.strip().upper() for p in (os.getenv("ANDROID_SHA256") or "").split(",") if p.strip()]
    if not package or not prints:
        return None
    return [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {"namespace": "android_app", "package_name": package, "sha256_cert_fingerprints": prints},
    }]


def privacy_html() -> str:
    operator = html.escape(os.getenv("PRIVACY_OPERATOR", "전상문"))
    contact = os.getenv("PRIVACY_CONTACT", "cossack275@gmail.com")
    if contact.startswith("http"):
        contact_html = f'<a href="{html.escape(contact, quote=True)}">{html.escape(contact)}</a>'
    elif "@" in contact:
        contact_html = f'<a href="mailto:{html.escape(contact, quote=True)}">{html.escape(contact)}</a>'
    else:
        contact_html = html.escape(contact)
    effective = html.escape(os.getenv("PRIVACY_EFFECTIVE", "2026-11-07"))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>개인정보처리방침 - {APP_NAME}</title>
<style>
body{{font-family:-apple-system,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;max-width:760px;margin:0 auto;padding:24px 16px 64px;
line-height:1.7;font-size:17px;color:#1a1a1a;background:#fff}}
h1{{font-size:26px}} h2{{font-size:20px;margin-top:2em}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:8px;text-align:left;vertical-align:top}} th{{background:#f3f5f7}}
.note{{background:#fff6e0;border:1px solid #e8b84a;padding:12px;border-radius:8px}}
@media (prefers-color-scheme: dark){{body{{background:#121212;color:#eee}} th{{background:#222}} td,th{{border-color:#444}}
.note{{background:#3a2a19;border-color:#8a6a2a}} a{{color:#8ab4f8}}}}
</style></head><body>
<h1>개인정보처리방침</h1>
<p>{APP_NAME}(이하 "서비스")는 이용자의 개인정보를 소중히 다루며, 「개인정보 보호법」에 따라 다음과 같이 처리합니다.</p>
<p class="note">이 서비스는 정부·공공기관이 운영하는 서비스가 아닙니다. 정리 결과는 참고용이며, 돈을 내기 전에는 고지서 원본이나 기관에 꼭 확인하세요.</p>

<h2>1. 처리하는 정보</h2>
<table>
<tr><th>정보</th><th>언제</th><th>어떻게 다루나요</th></tr>
<tr><td>이용자가 올리거나 찍은 고지서·공문 사진, PDF</td><td>'쉽게 풀어주세요'를 누를 때</td>
<td>내용을 정리하는 동안만 처리하고 서버에 저장하지 않습니다. 처리용 임시 파일은 1시간 안에 자동 삭제됩니다.</td></tr>
<tr><td>접속 IP 주소</td><td>무료 사용 횟수를 셀 때</td>
<td>하루 무료 사용 횟수(1인당 하루 몇 번)를 세는 데만 쓰며, 서버 메모리에만 두고 날짜가 바뀌면 지웁니다. 기록이나 로그로 남기지 않습니다.</td></tr>
<tr><td>이용자가 직접 넣은 Anthropic API 키 (선택)</td><td>'더보기 설정'에 넣었을 때</td>
<td>그 요청을 처리하는 데만 쓰고 서버에 저장하지 않습니다. '이 기기에 키 기억하기'를 켜면 <b>이용자 기기의 브라우저에만</b> 암호화해 저장되며, 끄면 지워집니다.</td></tr>
<tr><td>화면 설정 (글씨 크기, 처리 방식 등)</td><td>설정을 바꿀 때</td><td>이용자 기기의 브라우저에만 저장됩니다.</td></tr>
</table>
<p>회원가입이 없으며, 이름·전화번호·주소·위치 정보를 따로 수집하지 않습니다. 다만 이용자가 올린 문서 안에 이런 정보가 들어 있을 수 있습니다.</p>

<h2>2. 이용 목적</h2>
<p>문서 내용을 쉬운 말로 정리하고, 기한(D-day)·금액·사기 의심 신호를 알려 드리기 위해서만 이용합니다. 광고나 마케팅에 쓰지 않습니다.</p>

<h2>3. 처리 위탁 및 국외 이전</h2>
<table>
<tr><th>받는 곳 (국가)</th><th>보내는 정보</th><th>목적</th><th>보관</th></tr>
<tr><td>Anthropic, PBC (미국)</td><td>문서 이미지·PDF와 정리 요청</td><td>AI(Claude)로 문서 내용 정리</td>
<td>Anthropic의 정책에 따릅니다 (<a href="https://www.anthropic.com/legal/privacy">Anthropic 개인정보처리방침</a>)</td></tr>
<tr><td>Hugging Face, Inc. (미국)</td><td>문서 이미지·PDF, 접속 정보</td><td>서비스가 실행되는 서버 제공</td>
<td>처리하는 동안만 (<a href="https://huggingface.co/privacy">Hugging Face 개인정보처리방침</a>)</td></tr>
</table>
<p>정보는 '쉽게 풀어주세요'를 누를 때 암호화된 통신(HTTPS)으로 전송됩니다. 키 없이 무료로 쓰면 운영자의 Anthropic 계정으로, 직접 키를 넣으면 이용자 본인의 계정으로 처리됩니다.
'구글 캘린더에 추가', '카카오톡·문자로 보내기', 전화 걸기는 이용자가 버튼을 누를 때만 해당 서비스로 이동하며, 그때 개인정보가 없는 요약만 전달됩니다.</p>

<h2>4. 개인정보 자동 가림</h2>
<p>주민등록번호·휴대전화 번호는 결과 글에서 자동으로 가립니다. '자동' 처리 방식에서는 이름·주소·주민번호·휴대전화·계좌번호를 이미지에서 먼저 가린 뒤 보냅니다.
'빠르게' 방식에서는 원본 이미지가 전송됩니다. 자동 가림은 완벽하지 않을 수 있으니, 민감한 부분은 미리 가리고 찍는 것을 권합니다.</p>

<h2>5. 카메라 사용</h2>
<p>'사진 찍기'를 누를 때만 휴대폰 카메라를 사용하며, 찍은 사진은 위 1번과 같이 처리합니다.</p>

<h2>6. 광고</h2>
<p>현재 광고를 표시하지 않습니다. 광고를 넣게 되면 광고 회사와 처리하는 정보를 이 방침에 추가하고 미리 알려 드립니다.</p>

<h2>7. 만 14세 미만 아동</h2>
<p>이 서비스는 만 14세 미만 아동을 대상으로 하지 않습니다.</p>

<h2>8. 이용자의 권리와 기기에 저장된 정보 지우기</h2>
<p>서버에는 이용자를 알아볼 수 있는 정보를 저장하지 않습니다. 기기에 저장된 키·설정은 '이 기기에 키 기억하기'를 끄거나, 브라우저(또는 앱)의 저장 데이터를 지우면 삭제됩니다.
궁금한 점이나 요청은 아래 문의처로 알려 주세요.</p>

<h2>9. 안전성 확보 조치</h2>
<p>모든 통신은 HTTPS로 암호화합니다. 문서 내용과 결과를 로그로 남기지 않으며, 서버의 로컬 파일이나 내부 네트워크 주소는 외부 요청으로 읽을 수 없게 막아 두었습니다.</p>

<h2>10. 개인정보 보호책임자 및 문의</h2>
<p>운영자: {operator}<br>문의: {contact_html}</p>

<h2>11. 시행일</h2>
<p>이 방침은 {effective}부터 적용됩니다. 내용이 바뀌면 이 페이지에 알립니다.</p>
</body></html>"""


def install(app: FastAPI) -> None:
    """Gradio 경로보다 앞에 위의 경로를 끼워 넣는다 (같은 /manifest.json도 이쪽이 먼저)."""
    router = APIRouter()

    @router.get("/manifest.json", include_in_schema=False)
    def _manifest():
        return JSONResponse(manifest(), media_type="application/manifest+json")

    @router.get("/app-static/{name}", include_in_schema=False)
    def _static(name: str):
        if name not in ICON_FILES:
            return Response(status_code=404)
        return FileResponse(STATIC / name, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @router.get("/privacy", include_in_schema=False)
    def _privacy():
        return HTMLResponse(privacy_html())

    @router.get("/.well-known/assetlinks.json", include_in_schema=False)
    def _assetlinks():
        data = assetlinks()
        return JSONResponse(data) if data is not None else Response(status_code=404)

    before = len(app.router.routes)
    app.include_router(router)
    ours = app.router.routes[before:]
    del app.router.routes[before:]
    app.router.routes[0:0] = ours
