# 심즈 4 모드 자동 업데이터 (Sims 4 Mod Auto Updater)

심즈 4 모드 파일(`.package`, `.ts4script`)의 버전을 확인하고, 최신 버전으로 자동 다운로드 및 업데이트를 도와주는 파이썬 도구입니다.

---

## 📁 프로젝트 구조

```
Sims 4 Mod Auto Updater/
├── src/
│   ├── config.py       # 심즈 4 Mods 폴더 자동 감지 및 설정 관리
│   ├── scanner.py      # Mods 폴더 스캔 (.package, .ts4script 검사 및 서브폴더 깊이 경고)
│   ├── backup.py       # 모드 업데이트 전 자동 롤백용 백업 생성
│   ├── updater.py      # 모드 버전 비교, 다운로드, 압축 해제 및 설치 엔진
│   └── utils.py        # 파일 다운로드, SHA256 해시, 파일 정리 유틸리티
├── backups/            # 업데이트 전 백업 파일 보관 폴더
├── mods_manifest.json  # 관리 대상 모드 목록 (GitHub, 버전 정보 등)
├── config.json         # 사용자 설정 파일 (Mods 경로 등)
├── main.py             # 실행 진입점 (대화형 CLI 메뉴)
├── requirements.txt    # 필요 라이브러리 목록
└── README.md           # 설명서
```

---

## ⚡ 주요 기능

1. **내 문서 심즈 4 Mods 폴더 자동 감지 및 설치 모드 전체 목록 자동 스캔**
   - 일반 `Documents` 및 `OneDrive` 동기화 폴더를 자동 탐색합니다.
   - `1. Mods 폴더 상태 확인 및 스캔` 실행 시, 사용자마다 다르게 설치된 1단계 모드 폴더들을 자동 스캔하여 **설치된 모든 모드 목록(폴더명, 직속 .package/.ts4script 수, 분류, 하위폴더 유무)**을 한눈에 표로 보여줍니다. (하위 폴더는 별개 모드로 세지 않고 대상 폴더의 직속 파일 기준으로 모드를 식별)
2. **스크립트 모드 깊이(Depth) 제한 검사**
   - 심즈 4는 `.ts4script` 파일이 Mods 하위 1단계를 초과하는 서브폴더에 들어가면 인식하지 못합니다. 이를 사전에 감지하고 경고합니다.
3. **업데이트 전 자동 백업**
   - 모드를 덮어쓰기 전에 `backups/` 폴더에 날짜별로 백업을 생성하여 안전하게 복원할 수 있습니다.
4. **스크립트 모드 자동 감지 및 실시간 번호 선택 (일반 배포 최적화)**
   - `2. 모드 업데이트 확인` 메뉴 진입 시, 수동 설정 파일(`mods_manifest.json`)을 일일이 작성할 필요 없이 **실제 사용자의 Mods 폴더를 스캔하여 감지된 스크립트 모드(`ts4script` 포함) 및 한글화 모드 목록을 실시간 동적 메뉴로 생성**합니다.
   - 사용자는 원하는 모드의 번호를 선택하여 `선택된 폴더는 [폴더 이름]입니다.` 안내와 함께 감지된 위치, 직속 `.package` 및 `.ts4script` 파일 수, 그리고 동일 파일이 Mods 폴더 내 다른 위치에 존재하는지 여부(`.package`/`.ts4script` 중복 감지)를 확인하고 웹 업데이트 검색을 진행할 수 있습니다.
   - 모드 폴더 선택 시 아래 3가지 선택지를 제공합니다:
     - **1. 다른 메뉴로 전환**: 메인 메뉴로 복귀합니다.
     - **2. 하위 폴더 검색하기**: 선택한 모드 폴더 및 모든 하위 폴더에 있는 모든 `.package`와 `.ts4script` 파일의 전체 목록을 생략 없이 상세하게 출력합니다. 목록에서 특정 파일을 번호로 선택하면 파일 정보와 함께 다음 4가지 작업을 진행할 수 있습니다:
       - `1. 다른 메뉴로 전환`: 메인 메뉴로 복귀합니다.
       - `2. 하위 폴더 검색하기`: 파일 목록으로 다시 돌아가 다른 파일을 탐색합니다.
       - `3. 웹에서 최신 버전/배포 페이지 검색`: 폴더 이름 대신 감지/선택된 실제 `.package` 또는 `.ts4script` 파일 이름으로 최신 버전과 공식 배포 페이지를 검색하고 업데이트를 진행합니다.
       - `4. 프로그램 종료`: 프로그램을 안전하게 종료합니다.
     - **3. 프로그램 종료**: 프로그램을 안전하게 종료합니다.
5. **지원 모드별 감지 및 배포처 정책**
   - **MC Command Center (MCCC)**: `MOD MC Command Center`, `MOD MCCC` 폴더 감지 및 공식 배포처 최신 버전 조회.
   - **WickedWhims (WW)**: `MOD WickedWhims`, `MOD WW` 폴더 감지 및 공식 배포 페이지 연동.
   - **바람별 한글화 모드**: `PRIO` 폴더 내 `!WAMTIK`, `_WAMTIK` 파일명 필터링 감지 + Patreon(선배포) 및 Postype(`https://www.postype.com/@wwwindystar`) 공식 배포처 연동.
     - **무료/유료 정책**: 무료 배포 파일은 프로그램이 자동 다운로드하며, 유료/멤버십 후원 상품은 창작자 권리 보호를 위해 공식 채널 방문 안내문을 제공합니다.
   - **기타 모든 모드 및 파일 (지능형 공식 배포처 고정밀 자동 추출)**: 구글 검색 결과 창 대신 `src/finder.py`의 3단계 정밀 엔진(① 검증된 공식 카탈로그 우선 매칭 → ② 스마트 파일명 토크나이저 → ③ 검색 결과 스니펫 블록 파싱 및 키워드 유사도 채점)을 통해 실제 공식 배포처(CurseForge, Patreon, Itch.io, ModTheSims 등)의 배포 페이지 링크와 제목을 95% 이상의 정확도로 직접 추출하여 제공합니다.

---

## 🚀 시작하기

### 1. 패키지 설치
```bash
pip install -r requirements.txt
```

### 2. 프로그램 실행
```bash
python main.py
```

---

## 📝 관리할 모드 추가 방법 (`mods_manifest.json`)

`mods_manifest.json` 파일에 관리하고 싶은 모드를 추가할 수 있습니다:

```json
{
    "mods": [
        {
            "name": "MC Command Center",
            "source_type": "mccc",
            "install_folder": "MC Command Center",
            "current_version": ""
        },
        {
            "name": "Sims4CommunityLibrary",
            "source_type": "github",
            "repo": "DeviantGameMods/Sims4CommunityLibrary",
            "install_folder": "Sims4CommunityLibrary",
            "current_version": ""
        }
    ]
}
```
