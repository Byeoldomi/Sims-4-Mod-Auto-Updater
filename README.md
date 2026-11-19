# 심즈 4 모드 자동 업데이터 (Sims 4 Mod Auto Updater) v0.1.5

심즈 4 모드 파일(`.package`, `.ts4script`)의 버전을 자동으로 조회하고, 최신 버전 다운로드 및 안전한 백업·업데이트를 지원하는 **데스크톱 GUI 도구**입니다.

---

## 📁 프로젝트 구조

```text
Sims 4 Mod Auto Updater/
├── src/
│   ├── config.py       # 심즈 4 Mods 폴더 자동 감지 및 설정 관리
│   ├── scanner.py      # Mods 폴더 스캔 (.package, .ts4script 검사 및 중복/깊이 경고)
│   ├── finder.py       # 공식 카탈로그 및 지능형 배포처/버전 탐색 엔진
│   ├── backup.py       # 모드 업데이트 전 자동 롤백용 백업 생성
│   ├── updater.py      # 모드 버전 비교, 다운로드, 압축 해제 및 설치 엔진
│   └── utils.py        # HTTPS 안전 요청, 파일 검증, SHA-256 유틸리티
├── ui/
│   ├── index.html      # 데스크톱 Web UI 레이아웃
│   ├── styles.css      # 심즈 4 테마 스타일
│   └── app.js          # 프론트엔드 상태·필터·진행률 컨트롤러
├── backups/            # 업데이트 전 백업 파일 보관 폴더
├── mods_manifest.json  # 관리 대상 모드 및 고정 배포 URL/버전 정보
├── config.json         # 사용자 설정 파일 (Mods 경로 등)
├── main.py             # GUI 전용 실행 진입점 (pywebview 데스크톱 앱)
├── app.py              # 하위 호환용 진입점 래퍼
├── requirements.txt    # 필요 라이브러리 목록
└── README.md           # 설명서
```

---

## ⚡ 주요 기능

1. **원클릭 데스크톱 GUI 및 Mods 폴더 자동 감지**
   - 일반 `Documents` 및 `OneDrive` 동기화 폴더의 `The Sims 4\Mods` 경로를 자동 탐색하며, 필요 시 `[폴더 변경]` 버튼으로 직접 지정할 수 있습니다.
   - 설치된 스크립트·패키지 모드를 카드 형태로 한눈에 표시하며, 상태별 필터(`전체`, `업데이트 필요`, `충돌/오류`, `최신 상태`)와 실시간 검색을 지원합니다.

2. **당일 스캔 캐시 유지 및 자정 자동 초기화**
   - 하루에 한 번 전체 스캔을 완료하면 결과를 당일 캐시(`scan_cache.json`)로 보관하여, 같은 날 프로그램을 껐다 켜도 처음부터 다시 스캔하지 않고 즉시 이어서 작업할 수 있습니다.
   - 자정이 지나 날짜가 바뀌면 캐시가 자동으로 초기화되어 새 스캔을 진행합니다.

3. **개별·일괄 자동 업데이트 및 즉시 상태 반영**
   - 선택한 모드 또는 업데이트 가능한 모드를 한 번에 백업 후 최신 버전으로 덮어씁니다.
   - 업데이트가 완료된 모드는 즉시 최신 버전 표기와 함께 **최신 상태**로 전환됩니다.
   - 유료/얼리 액세스/회원 전용 모드는 창작자 권리 보호를 위해 공식 배포 페이지 열기 버튼을 제공합니다.

4. **EA / Steam 클라이언트 자동 판별 게임 실행**
   - 로컬 PC의 심즈 4 설치 경로(`EA Games` / `Origin Games` vs `steamapps\common`)를 자동 감지하여, **EA App** 또는 **Steam 클라이언트**를 통해 바로 게임을 실행합니다.

5. **핵심 모드 빠른 백업 및 중복 파일 감지**
   - 대용량 CC 폴더를 제외한 핵심 스크립트/게임플레이 모드만 빠르게 백업할 수 있습니다.
   - Mods 폴더 내 중복 설치된 `.package` / `.ts4script` 파일을 감지하고 탐색기에서 해당 위치를 바로 열 수 있습니다.

---

## 🚀 시작하기

### 실행 파일로 바로 사용하기 (Windows)
1. GitHub Releases에서 최신 `Sims4ModUpdater_v0.1.5.exe`(및 동봉된 `mods_manifest.json`)를 내려받습니다.
2. 원하는 폴더에 압축을 풀거나 파일을 둔 뒤 `Sims4ModUpdater_v0.1.5.exe`를 실행합니다.
3. 필요 시 `checksum.txt` 또는 `release_hash.txt`의 SHA-256 해시로 파일 무결성을 확인할 수 있습니다.

### 소스 코드로 실행하기
```bash
pip install -r requirements.txt
python main.py
```
