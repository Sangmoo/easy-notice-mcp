# 안드로이드 앱 배포 안내 (TWA)

이 Space를 그대로 감싸는 **TWA(Trusted Web Activity)** 앱으로 Google Play에 올리는 방법입니다.
웹(Space)을 고치면 앱도 업데이트 없이 바로 반영됩니다. 아이콘·이름·패키지를 바꿀 때만 앱을 다시 올립니다.

## 0. 이미 준비된 것 (Space 쪽)

| 항목 | 주소 / 파일 |
|---|---|
| 앱 정보(manifest) | `https://sangmoo-easy-notice-mcp.hf.space/manifest.json` — 이름 "고지서 쉽게 보기", 시작 주소 `/?app=1` |
| 아이콘 | `static/icon-512.png`, `static/icon-192.png`, `static/icon-maskable-512.png` (시안 B) |
| Play 대표 이미지 | `static/feature-graphic-1024x500.png` |
| 개인정보처리방침 | `https://sangmoo-easy-notice-mcp.hf.space/privacy` |
| 사이트 연결 파일 | `/.well-known/assetlinks.json` — 아래 4단계에서 Space 설정값을 넣으면 켜짐 |
| 체험 모드 | 첫 화면 "📄 예시" 버튼 — 키·횟수 없이 모든 기능 확인 (심사용) |
| 앱 기본값 | 앱(`/?app=1`)으로 처음 열면 "⚡ 빠르게" 방식 |

아이콘·대표 이미지를 다시 만들려면: `python tools/make_assets.py <NotoSansKR 글꼴 경로>`

## 1. 정할 것

- **패키지 이름**: 예) `io.github.sangmoo.easynotice` — **한 번 정하면 바꿀 수 없음**
- **앱 이름**: 고지서 쉽게 보기
- **개인정보처리방침 운영자·문의처**: 코드 기본값 전상문 · cossack275@gmail.com (Space Variable `PRIVACY_OPERATOR`·`PRIVACY_CONTACT`로 바꿀 수 있음)

## 2. 앱 파일 만들기

### 방법 A: PWABuilder (화면에서 진행, 쉬움)

1. https://www.pwabuilder.com 에 `https://sangmoo-easy-notice-mcp.hf.space/?app=1` 입력 → Start
2. **Package for stores → Android → Generate Package**
   - Package ID: `io.github.sangmoo.easynotice`
   - App name: 고지서 쉽게 보기 / Launcher name: 고지서 쉽게
   - Signing key: **Create new** (처음 한 번)
3. 받은 zip 안의 파일
   - `*.aab` — Play Console 업로드용
   - `*.apk` — 내 휴대폰 테스트용
   - `signing.keystore` + `signing-key-info.txt` — **반드시 안전한 곳에 백업** (잃으면 앱 업데이트 불가)
   - `assetlinks.json` — 4단계에서 사용

### 방법 B: Bubblewrap (명령어)

준비: Node.js, JDK 17 (Android SDK는 처음 실행 때 자동 설치)

```bash
npm install -g @bubblewrap/cli
```
```bash
bubblewrap init --manifest=https://sangmoo-easy-notice-mcp.hf.space/manifest.json
```
```bash
bubblewrap build
```

- `init`에서 패키지 이름, 앱 이름, 색(#1F4E79), 서명 키 생성(경로·별칭·비밀번호)을 물어봅니다.
- 결과: `app-release-bundle.aab`(Play용), `app-release-signed.apk`(테스트용)
- 서명 키(`android.keystore`)와 비밀번호를 **반드시 백업**하세요.

## 3. 휴대폰에서 먼저 테스트

USB 디버깅을 켠 휴대폰을 연결하고:

```bash
adb install app-release-signed.apk
```

확인할 것: 사진 찍기(카메라가 바로 열림), 예시 보기, 듣기(기기 음성), 구글 캘린더 추가, 카카오톡·문자로 보내기, 글씨 크게.
4단계 전에는 앱 위쪽에 주소창이 보이는 것이 정상입니다.

## 4. 앱과 사이트 연결 (주소창 없애기)

1. Play Console → 앱 → **설정 → 앱 무결성 → 앱 서명**에서 **앱 서명 키 인증서의 SHA-256 지문**을 복사
   (직접 만든 업로드 키 지문도 함께 넣어도 됨)
2. Space Settings → Variables에 추가
   - `ANDROID_PACKAGE` = `io.github.sangmoo.easynotice`
   - `ANDROID_SHA256` = `AA:BB:...` (여러 개면 쉼표로)
3. `https://sangmoo-easy-notice-mcp.hf.space/.well-known/assetlinks.json`이 열리는지 확인 → 앱을 다시 열면 주소창이 사라짐

## 5. Google Play Console

1. 개발자 계정 등록 (등록비 1회, 본인 인증)
2. **앱 만들기**: 이름 "고지서 쉽게 보기", 무료, 앱
3. **스토어 등록정보**
   - 짧은 설명(80자): `고지서 사진을 찍으면 언제까지, 얼마를, 무엇을 해야 하는지 쉽게 알려 드려요.`
   - 자세한 설명 예시:
     ```
     세금 고지서, 건강보험 안내문, 과태료 통지서, 관공서 공문이 어렵게 느껴지시나요?
     사진만 찍으면 무엇을, 언제까지, 얼마를 해야 하는지 큰 글씨로 쉽게 정리해 드려요.

     • 한눈에 보기: 기한(D-day)·금액·할 일을 큰 글씨로
     • 사기 의심 경고: 개인 계좌 입금 요구 등 수상한 점을 알려 주고 112·1332로 바로 전화
     • 소리로 듣기: 중요한 내용만 짧게 읽어 드려요 (천천히 읽기 가능)
     • 달력에 등록: 납부 기한을 구글 캘린더에 바로 추가
     • 가족에게 보내기: 개인정보 없는 요약을 카카오톡·문자로
     • 글씨 크게 보기, 큰 글씨 인쇄
     • 주민등록번호·휴대폰 번호는 자동으로 가려요

     ※ 정부·공공기관 앱이 아닙니다. 결과는 참고용이며, 돈을 내기 전에 원본이나 기관에 꼭 확인하세요.
     ```
   - 아이콘 512×512: `static/icon-512.png`
   - 대표 이미지 1024×500: `static/feature-graphic-1024x500.png`
   - 휴대폰 스크린샷 2장 이상: 예시 화면(자동차세, 사기 문자)을 휴대폰에서 캡처
4. **앱 콘텐츠**
   - 개인정보처리방침: `https://sangmoo-easy-notice-mcp.hf.space/privacy`
   - 앱 접근 권한: "로그인 없음. 첫 화면 '📄 예시' 버튼으로 모든 기능을 키 없이 확인할 수 있습니다. 실제 문서는 하루 5번까지 무료로 분석됩니다."
   - 광고: 없음 (광고를 넣으면 '있음'으로 바꾸고 개인정보처리방침도 수정)
   - 콘텐츠 등급 설문, 타겟층: 만 18세 이상 권장 (아동 대상 아님)
   - **데이터 보안** (실제 동작과 같게):
     - 수집: 사진(이용자가 올린 문서 사진) — 앱 기능 목적, **전송은 하되 저장 안 함**, 전송 중 암호화(HTTPS)
     - 기기 또는 기타 ID: 없음 (IP는 하루 무료 횟수 계산에만 메모리에서 사용)
     - 제3자 공유: 문서 처리를 위해 Anthropic(미국)·Hugging Face(미국)로 전송 — '서비스 제공업체 처리'에 해당
     - 데이터 삭제 요청: 서버에 저장하지 않음
5. **테스트**: 새 개인 개발자 계정은 프로덕션 전에 **비공개 테스트**(테스터 여러 명 × 일정 기간)가 필요할 수 있습니다. Play Console에 표시되는 현재 조건을 확인하세요.
6. **프로덕션 출시**

## 심사에서 자주 걸리는 점

- 심사자가 기능을 못 써 봄 → 체험 모드("📄 예시")와 '앱 접근 권한' 안내로 해결
- 정부·공공기관으로 오해 → 이름·아이콘·설명에 기관 로고·명칭을 쓰지 않고 "공식 앱 아님" 문구 유지
- 데이터 보안 양식과 실제 동작 불일치 → 위 4번처럼 작성
- 개인정보처리방침 문의처 누락 → `PRIVACY_CONTACT` 설정

## 나중에 광고를 붙일 때

- TWA 앱에는 AdMob(앱 광고)이 바로 붙지 않고 웹 광고(AdSense)를 써야 합니다.
- AdSense는 **본인 소유 도메인**이 필요해 `hf.space` 주소로는 승인이 어려울 수 있습니다 → 자체 도메인 연결 후 진행.
- 큰 버튼 근처에 광고를 두면 어르신이 잘못 누르기 쉬우니 결과 아래쪽에 배치하세요.
- 광고를 넣으면 개인정보처리방침 6번과 Play 데이터 보안 양식을 함께 고칩니다.
