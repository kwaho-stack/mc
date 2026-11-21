# 인줌 강의 자동 녹화기

[인줌 강의실](https://edu.inzeum.com/classRoom/goContentsList) 차시 목록에서 **학습하기 → Kollus 재생창 → F11 전체화면 → OBS 녹화 → 재생 끝나면 녹화 중지·재생창 닫기**를 차시마다 순서대로 자동으로 반복합니다.
개인 소장용으로만 사용하세요.

```
모든 주차를 펼쳐 목록 읽기 → (해당 주차 펼치고) [학습하기] 클릭 → Kollus 재생창 뜸 → F11 → ● 녹화 시작
   → 재생 끝 (재생창이 닫히거나 '종료' 알림) → ■ 녹화 중지 → 재생창 닫기
   → recordings\007_(3주차) 마음근력훈련의 의미 5차시 ….mkv 로 저장 → 다음 차시 (주차도 자동으로 넘어감)
```

## 준비물

| 항목 | 비고 |
|---|---|
| Windows 11 | |
| [Python 3.11 이상](https://www.python.org/downloads/) | 설치할 때 **"Add python.exe to PATH" 체크** |
| Google Chrome | 이미 설치된 크롬을 사용 |
| [OBS Studio 28 이상](https://obsproject.com/) | 녹화 담당 |
| Kollus 플레이어 | 강의를 한 번 재생해 봤다면 이미 설치되어 있음 |

## 1. 설치 (처음 한 번)

1. 이 폴더를 PC에 내려받습니다 (GitHub → Code → Download ZIP → 압축 풀기).
2. `install.bat` 더블클릭 → 필요한 파이썬 패키지가 설치됩니다.

## 2. OBS 설정 (처음 한 번)

1. **WebSocket 켜기**: OBS → `도구` → `WebSocket 서버 설정` → **WebSocket 서버 사용** 체크.
   - 비밀번호(인증)를 켜 두었다면 `config.yaml` 의 `recorder.obs.password` 에 같은 값을 넣습니다. 끄면 비워 두면 됩니다.
   - 포트는 기본 `4455`.
2. **화면 소스**: 장면의 소스 `+` → `디스플레이 캡처` → 주 모니터 선택.
3. **소리**: 오디오 믹서에 `데스크톱 오디오`가 켜져 있는지 확인. 마이크는 음소거 권장.
4. **저장 형식**: `설정 → 출력 → 녹화` 에서 형식 선택 (mkv 권장. mp4 를 원하면 `설정 → 고급 → 녹화 → 자동으로 mp4로 다시 담기`).
5. OBS 는 켜 둔 상태로 두면 됩니다. (꺼져 있으면 프로그램이 `config.yaml` 의 경로로 자동 실행)

## 3. 실행

1. `start.bat` 더블클릭.
2. **프로그램 전용 크롬 창**이 뜹니다. 처음에는 이 창에서 **로그인 → 녹화할 강좌의 차시 목록 화면**까지 이동한 뒤, 검은 창(명령 창)에서 Enter.
   - 접힌 주차는 프로그램이 하나씩 눌러 펼치면서 전체 차시를 읽습니다.
   - 로그인 정보는 `chrome-profile` 폴더에 남아서 다음부터는 바로 목록이 열립니다.
3. 차시 목록이 표로 나옵니다.
   ```
    번호  사이트  녹화   시청시간    제목

    ■ (3주차) 마음근력훈련의 의미
       5  완료    -     14/15분     3차시 호흡 명상 - 빛 시각화
       7  -       -     0/30분      5차시 질문과 답변: 호흡 알아차리기에 관하여
   ```
   - `사이트` = 인줌의 파란 체크(수강 완료), `녹화` = 이 프로그램으로 이미 녹화함
   - 번호는 전체 주차를 통틀어 매긴 번호입니다.
4. 질문에 답합니다.
   - **완료된 차시도 녹화할지** (기본: 건너뜀, `y` 로 바꿈)
   - **녹화할 번호** (`1-5,8` 처럼, Enter = 전체)
5. Enter 로 시작. **녹화하는 동안에는 마우스·키보드를 건드리지 마세요.**
6. 처음 재생할 때 크롬에 **"Kollus 을(를) 여시겠습니까?"** 창이 뜨면 **'항상 허용' 체크 → 열기**. (한 번만 하면 됨)

녹화 파일은 `recordings` 폴더에 `001_차시제목.mkv` 형식으로 저장됩니다.
중간에 멈춰도(Ctrl+C, 오류, 재부팅) 다시 실행하면 **녹화 안 된 차시부터** 이어서 합니다. (`recordings\progress.json`)

### 명령 옵션 (`start.bat` 뒤에 붙이기, 또는 `python run.py ...`)

| 옵션 | 설명 |
|---|---|
| `--list` | 차시 목록만 보기 |
| `--only 1-5,8` | 해당 번호만 녹화 |
| `--include-completed` / `--skip-completed` | 사이트 완료 차시 포함 / 건너뛰기 |
| `--redo` | 이미 녹화한 차시도 다시 녹화 |
| `-y` | 묻지 않고 바로 시작 |
| `--probe` | 목록 인식 결과 + 페이지 HTML 을 `probe` 폴더에 저장 (문제 확인용) |
| `--probe-player 3` | 3번 차시를 **녹화 없이** 열어 재생창·알림창 정보 출력 (문제 확인용) |

## 4. 설정 (`config.yaml`)

메모장으로 열어 수정 → 저장 → 다시 실행.

| 항목 | 기본값 | 설명 |
|---|---|---|
| `lessons.skip_completed` | `true` | 사이트 완료 차시 건너뛰기 (시작할 때 다시 물어봄) |
| `lessons.study_button_texts` | 학습하기, 복습하기, 다시보기 | 재생 버튼 글자 |
| `lessons.section_pattern` | `(N주차)` | 주차 제목 찾기. 접힌 주차는 자동으로 펼침 |
| 완료 판단 | 자동 | 다 본 차시(57분/57분)와 안 본 차시(0분/30분)를 비교해 **체크 아이콘 모양을 스스로 학습**. 안 되면 `completed_patterns`(글자) → 시청시간 비율(`completed_time_ratio`) 순 |
| `player.window_mode` | `key` | 재생창이 뜬 뒤 `fullscreen_key` 를 눌러 전체화면 |
| `player.fullscreen_key` | `F11` | 전체화면 키 |
| `player.max_minutes_per_lesson` | `240` | 한 차시 최대 녹화 시간(분) |
| `player.dialogs` | | 재생 중 알림창 처리 규칙 (이어보기→아니오, 종료 알림→확인 후 녹화 종료 등) |
| `recorder.type` | `obs` | `obs` 또는 `snipping`(윈도우 캡처 도구, 실험적) |
| `recorder.start_before_click` | `false` | `true` 면 학습하기 누르기 전부터 녹화 (앞부분 안 빠짐) |
| `output_dir` | `./recordings` | 저장 폴더 |

## 차시 종료 판단 방법

1. Kollus 재생창이 **스스로 닫히면** → 종료
2. **'완료/종료' 알림창**이 뜨면 → 확인을 누르고 종료
3. 최대 시간(`max_minutes_per_lesson`)을 넘으면 → 강제 종료

종료 후 재생창이 남아 있으면 프로그램이 닫고, 그래도 안 닫히면 Kollus 프로세스를 종료합니다.

## 문제 해결

| 증상 | 해결 |
|---|---|
| "차시 목록을 찾지 못했습니다" | 크롬 창에서 차시 목록 화면까지 이동 후 Enter. 계속 안 되면 `start.bat --probe` 실행 후 `probe` 폴더의 html 파일을 보내 주세요 |
| 제목이 이상하게 잡힘 | `config.yaml` 의 `lessons.title_selector` 지정 (probe 결과로 맞춰 드림) |
| "재생창이 뜨지 않았습니다" | 크롬의 Kollus 열기 확인창에서 '항상 허용'. 또는 `start.bat --probe-player 1` 로 재생창 프로세스 이름 확인 후 `player.process_names` 에 추가 |
| 전체화면이 안 됨 | `player.fullscreen_key` 변경, 또는 `window_mode: maximize` |
| "OBS 에 연결하지 못했습니다" | OBS 켜기 + `도구 → WebSocket 서버 설정` 확인, 비밀번호 일치 확인 |
| 재생이 차단됨 (-1015, 1002 등) | Kollus 가 녹화 프로그램을 감지한 것입니다. 이 경우 자동 녹화는 진행하지 않습니다 |

## 주의

- 녹화 중에는 PC 를 사용하지 마세요. (알림·팝업도 녹화됩니다 → Windows `방해 금지` 켜기 권장)
- 모니터가 여러 대면 **주 모니터** 기준으로 녹화됩니다.
- 실행 기록은 `logs` 폴더에 남습니다.

## 폴더 구조

```
run.py                 실행 진입점 (목록 표시, 선택, 전체 진행)
config.yaml            설정
install.bat, start.bat 설치 / 실행
recorder/
  browser.py           크롬 제어: 로그인 유지, 차시 목록 인식, 학습하기 클릭
  player.py            Kollus 재생창: 찾기, F11 전체화면, 알림창 처리, 종료 감지, 닫기
  capture.py           녹화: OBS(obs-websocket) / 윈도우 캡처 도구
  pipeline.py          차시 하나 녹화, 전체 순서 진행, 재시도
  files.py             녹화 파일 이름 정리·이동
  state.py             진행 기록(progress.json)
  winutil.py           Windows 창·키보드·마우스·절전 방지
```
