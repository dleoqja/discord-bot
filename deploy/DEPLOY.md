# 오라클 무료 클라우드에 디스코드 봇 24시간 올리기

노트북을 꺼도 봇이 계속 돌아가게 하는 전체 순서. 오라클 **Always Free** VM(평생 무료)에 올린다.

---

## 0. 준비물
- 신용/체크카드 1장 (가입 본인인증용, **요금 청구 안 됨**)
- 이메일, 휴대폰

---

## 1. 오라클 클라우드 계정 만들기
1. https://www.oracle.com/kr/cloud/free/ → **무료로 시작하기**
2. 이메일/국가(South Korea) 입력 → 카드 인증 → 가입 완료
3. 지역(Home Region)은 **Seoul** 또는 **Chuncheon** 선택 (한국이 지연 낮음)

## 2. 무료 VM 인스턴스 생성
1. 콘솔 좌측 메뉴 → **Compute → Instances → Create Instance**
2. **Image**: Ubuntu 22.04 (or 24.04)
3. **Shape**: `VM.Standard.E2.1.Micro` (AMD, Always Free, 1GB RAM — 이 봇엔 충분)
   - 더 넉넉하게 쓰려면 `VM.Standard.A1.Flex` (ARM, 최대 4코어/24GB 무료). 단 용량 부족(Out of capacity) 뜨면 AMD micro 로.
4. **SSH keys**: "Generate a key pair for me" → **개인키(.key) 꼭 다운로드** 해서 보관
5. **Create** 클릭 → 인스턴스의 **Public IP** 메모

## 3. 방화벽(디스코드는 아웃바운드라 포트 오픈 불필요)
- 봇은 밖으로만 연결하므로 인바운드 포트 열 필요 없음. 기본값 그대로 OK.

---

## 4. SSH 접속 (Windows / PowerShell)
다운받은 개인키가 예: `C:\Users\dlwkd\Downloads\ssh-key.key` 라고 하면:

```powershell
# 키 권한 정리 (최초 1회) — 안 하면 접속 거부될 수 있음
icacls "C:\Users\dlwkd\Downloads\ssh-key.key" /inheritance:r
icacls "C:\Users\dlwkd\Downloads\ssh-key.key" /grant:r "$($env:USERNAME):(R)"

# 접속 (아래 IP를 본인 Public IP로)
ssh -i "C:\Users\dlwkd\Downloads\ssh-key.key" ubuntu@<PUBLIC_IP>
```

---

## 5. 코드 올리기 (노트북 → VM)
로컬 PowerShell 에서 (`.venv` 는 윈도우용이라 **빼고** 올림 — VM에서 새로 만든다):

```powershell
# 코드 압축 (venv/캐시 제외)
cd C:\Users\dlwkd
tar --exclude='.venv' --exclude='__pycache__' --exclude='assets/champions' -czf discord-bot.tar.gz discord-bot

# VM으로 전송
scp -i "C:\Users\dlwkd\Downloads\ssh-key.key" discord-bot.tar.gz ubuntu@<PUBLIC_IP>:/home/ubuntu/
```

`.env` 와 `data.sqlite3` 는 `.gitignore` 대상이지만 `tar` 는 그대로 포함하니 함께 넘어간다(토큰/DB 유지됨).

---

## 6. VM에서 세팅 (SSH 접속한 상태)

```bash
# 압축 풀기
cd /home/ubuntu
tar -xzf discord-bot.tar.gz

# 파이썬 + venv 준비
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
cd /home/ubuntu/discord-bot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# .env 확인 (DISCORD_TOKEN 들어있는지)
cat .env

# 한번 직접 실행해서 정상 로그인 되는지 테스트 (Ctrl+C 로 종료)
.venv/bin/python -m bot.main
```

`Logged in as ...` 로그가 뜨면 성공. Ctrl+C 로 멈춘다.

---

## 7. 자동 실행 등록 (재부팅해도 자동 시작 + 죽으면 자동 재시작)

```bash
# 서비스 파일 설치
sudo cp /home/ubuntu/discord-bot/deploy/mhbot.service /etc/systemd/system/mhbot.service
sudo systemctl daemon-reload
sudo systemctl enable mhbot     # 부팅 시 자동 시작
sudo systemctl start mhbot      # 지금 시작

# 상태 확인
systemctl status mhbot
```

이제 **노트북/SSH 다 꺼도** 봇이 VM에서 24시간 돌아간다.

---

## 자주 쓰는 관리 명령

```bash
sudo systemctl restart mhbot        # 재시작
sudo systemctl stop mhbot           # 정지
journalctl -u mhbot -f              # 실시간 로그 보기
journalctl -u mhbot -n 100          # 최근 100줄 로그
```

## 코드 업데이트할 때
1. 로컬에서 다시 `tar` + `scp` (5번)
2. VM에서:
   ```bash
   cd /home/ubuntu && tar -xzf discord-bot.tar.gz
   cd discord-bot && .venv/bin/pip install -r requirements.txt   # 의존성 바뀐 경우만
   sudo systemctl restart mhbot
   ```

---

## 참고 / 주의
- **g4f(gpt4free)**: 무료 웹 제공자를 크롤링하는 방식이라, 데이터센터 IP를 일부 제공자가 차단할 수 있음. `/ai` 응답이 안 오면 g4f 버전을 올려보거나(`pip install -U g4f`) 다른 provider 로 바꾸면 됨.
- **비용**: 위 구성(AMD E2.1.Micro)은 Always Free 라 카드에서 빠지지 않음. 단 "유료 업그레이드(Upgrade to Paid)" 버튼은 누르지 말 것.
- **데이터(DB)**: `data.sqlite3` 는 VM 안에 있으니, 나중에 백업하려면 `scp` 로 반대로 내려받으면 됨.
