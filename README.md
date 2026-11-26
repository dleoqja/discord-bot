# Discord Bot

Cog 기반으로 확장 가능한 디스코드 봇. 슬래시 커맨드 기반으로 롤 전적·자동 분석, MHXX 도우미, AI 대화 기능을 제공합니다.

## 기능

| 명령어 | 설명 |
|--------|------|
| `/lol` | 롤 전적 카드 조회 (숙련도/모스트/승률/라인별/분당 지표/최근 전적) |
| `/링크` | 내 디스코드에 롤 계정 연결 |
| `/내전적` | 연결된 내 계정 전적 바로 조회 |
| `/자동분석` | 이 채널에 게임 시작 시 참가자 정보 + 게임 종료 시 분석(AI 한마디) 자동 게시 (on/off) |
| `/인게임` | 진행 중인 게임 참가자 10명의 티어/승률 (이름 생략 시 연결된 내 계정) |
| `/모집` | 게임·시간·인원을 정해 파티 모집 (참가/나가기 버튼, 다 차면 전원 멘션) |

롤 기능은 `RIOT_API_KEY`가 필요합니다 (https://developer.riotgames.com).

## 실행 방법

### 1. 봇 생성 & 토큰 발급
1. https://discord.com/developers/applications 에서 New Application
2. **Bot** 탭 → Reset Token으로 토큰 복사
3. **Bot** 탭 → `MESSAGE CONTENT INTENT` 활성화
4. **OAuth2 → URL Generator** → `bot`, `applications.commands` 스코프 선택 → 생성된 URL로 서버에 초대

### 2. 환경 설정
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt

copy .env.example .env         # 그 후 .env 안에 토큰 입력
```

`.env`의 `GUILD_ID`에 테스트 서버 ID를 넣으면 슬래시 명령어가 즉시 반영됩니다.

### 3. 실행
```bash
python -m bot.main
```

## 프로젝트 구조
```
discord-bot/
├── bot/
│   ├── main.py          # 진입점: 봇 생성, Cog 로드, 명령어 동기화
│   ├── config.py        # 환경 변수 / 설정
│   ├── database.py      # SQLite 데이터 계층
│   └── cogs/
├── requirements.txt
├── .env.example
└── README.md
```

## 다음 단계 (로드맵)
- [x] 롤 전적 조회 (전적 카드 이미지 생성)
- [x] 롤 계정 링크 + 게임 종료 자동 분석
- [ ] 끝말잇기 / 퀴즈 등 미니게임 추가
- [ ] 리마인더 / 정기 공지
- [ ] PostgreSQL 전환 + 배포 (Railway / Fly.io)
- [ ] 웹 대시보드 (FastAPI)
