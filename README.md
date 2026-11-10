# Instagram 게시물 데이터 수집기

---

## 무엇을 할 수 있나

계정 아이디 목록만 있으면 됩니다.

```
nike, adidas, musinsa ...
        ↓
게시물 정보 + 이미지 파일이 담긴 데이터셋
```

Meta 가 제공하는 **Business Discovery** 라는 기능을 씁니다.
내 인스타 계정으로 로그인해서 다른 계정의 공개 정보를 조회하는 방식입니다.

> **양쪽 다 비즈니스/크리에이터 계정이어야 합니다.**
> 내 계정도, 조회할 상대 계정도 마찬가지입니다. 개인 계정은 조회되지 않습니다.

---

## 시작하기

### 1. 설치

Python 3.9 이상이 필요합니다.

```bash
pip install -r requirements.txt
```

### 2. 인증 정보 (`.env`)

Meta 에서 받은 값 두 개를 적어 둡니다.

```bash
cp .env.example .env
```

```dotenv
ig_user_id=17841400000000000     # 내 인스타 비즈니스 계정의 숫자 ID
access_token=EAAG...             # Meta 가 발급한 토큰 (60일마다 갱신)
```

**이 두 값을 받는 방법은 [meta_api_setup.txt](meta_api_setup.txt) 에
단계별로 정리되어 있습니다.** 처음이면 20~30분 걸립니다.

> `.env` 는 비밀번호와 같습니다. 공유하거나 커밋하지 마세요
> (`.gitignore` 에 이미 등록돼 있습니다).

### 3. 조회할 계정 목록 (`input/accounts.csv`)

직접 만드는 유일한 파일입니다. 예시를 복사해 쓰세요.

```bash
cp input/accounts.example.csv input/accounts.csv
```

`ig_username` 은 필수, `country` 는 비워도 됩니다.

```csv
ig_username,country
nike,US
adidas,DE
musinsa,KR
```

> 첫 줄 헤더가 `ig_username` 인지 확인하세요.
> 철자가 다르면 계정을 0개 읽고 그대로 멈춥니다.

> `input/accounts.csv` 는 `.gitignore` 에 등록돼 있습니다 —
> 어떤 계정을 조회하는지는 저장소에 올라가지 않습니다.

### 4. 실행

```bash
python3 crawling.py         # 1단계: 정보 수집
python3 download_media.py   # 2단계: 이미지·영상 다운로드
```

두 단계를 마치면 `output/dataset.csv` 와 `output/images/` 가 생깁니다.
**학습에 쓸 것은 이 둘뿐입니다.**

> 1단계와 2단계는 **되도록 바로 이어서** 실행하세요.
> 이미지 주소가 며칠이면 만료됩니다 (아래 "주의할 점" 참고).

---

## 어떻게 동작하나

```
input/accounts.csv               ① 조회할 계정 목록 (직접 작성)
      │
      │  python3 crawling.py                    실패 → data/failed/accounts.csv
      ▼
data/posts.csv                   ② 계정·게시물 정보 + 이미지 주소
      │
      │  python3 download_media.py              실패 → 그냥 다시 실행하면 됨
      ▼
output/images/, output/videos/   ③ 실제 이미지·영상 파일
output/dataset.csv               ④ 파일까지 확보된 행 + 파일 경로
```

| 단계 | 하는 일 |
|---|---|
| `crawling.py` | API 를 불러 숫자·글·이미지 **주소**를 CSV 로 모음 |
| `download_media.py` | 그 주소로 실제 **파일**을 내려받음 |

**두 단계는 실패를 다르게 다룹니다.** 1단계는 API 호출이 시간당 200회로 제한돼
전체 재실행이 비싸므로 실패한 계정을 `data/failed/accounts.csv` 에 남깁니다.
2단계는 이미 받은 파일을 건너뛰므로, **같은 명령을 그냥 다시 실행하면** 됩니다.

---

## 자세한 사용법

### 1단계 — 정보 수집

```bash
python3 crawling.py                 # 계정당 30건 (MAX_MEDIA 기본값)
python3 crawling.py --max N         # 이번 실행만 계정당 N건
python3 crawling.py --max all       # 계정의 모든 게시물
python3 crawling.py failed --max N  # 별칭과 --max 를 함께 쓸 수도 있음
python3 crawling.py --help          # 전체 옵션 (기본값도 함께 표시)
```

`--max` 는 **이번 실행에만** 적용되고 코드의 설정값은 그대로입니다.
지정한 값은 실패 목록에도 함께 기록되므로, `crawling.py failed` 로 재시도할 때
같은 옵션을 다시 칠 필요가 없습니다.

몇 건을 받을지는 이 순서로 정해집니다.

| 순위 | 출처 |
|---|---|
| ① | `--max` — 지정하면 항상 이깁니다 |
| ② | `data/failed/accounts.csv` 의 `max_media` — 재시도할 때 자동으로 물려받음 |
| ③ | `crawling.py` 의 `MAX_MEDIA` 설정값 |

결과는 `data/posts.csv` **한 파일에 쌓입니다.**
계정을 나눠 여러 번 돌려도 한곳에 모이고, 같은 게시물을 다시 수집하면
`media_id` 기준으로 기존 행이 갱신됩니다 — 중복이 쌓이지 않고,
만료된 이미지 주소가 새 주소로 바뀝니다.

### 2단계 — 파일 다운로드

```bash
python3 download_media.py            # data/posts.csv (기본값)
python3 download_media.py <csv경로>  # 다른 CSV 를 지정
```

실패했거나 `q`·`Ctrl+C` 로 멈췄으면 **같은 명령을 다시 실행**하면 됩니다.
이미 받아 둔 파일은 건너뛰므로 못 받은 것만 다시 시도합니다.
남은 개수는 실행이 끝날 때 알려줍니다.

파일은 `output/` 아래에 게시물 ID로 이름이 붙어 저장되고,
**받아야 할 파일을 하나도 빠짐없이 확보한 행만** `output/dataset.csv` 로 모입니다.

`dataset.csv` 는 수집 CSV 의 컬럼 전부에 두 개를 더한 형태입니다.

| 컬럼 | 내용 |
|------|------|
| `cover_path` | 학습에 쓸 표지 이미지 (`images/<media_id>_cover.jpg`) |
| `local_files` | 이 게시물에서 받은 모든 파일 (`;` 로 구분) |

경로는 `output/` 기준 상대경로라 폴더째 옮겨도 동작합니다.
이미지 주소는 만료되지만 이 경로는 만료되지 않으므로,
**학습 코드는 `dataset.csv` 하나만 읽으면 됩니다.**

### 실패한 계정 다시 하기 (1단계)

수집에 실패한 계정은 `data/failed/accounts.csv` 에 기록됩니다.
`input/accounts.csv` 와 같은 형식이라 그대로 다시 넘기면 됩니다.

```bash
python3 crawling.py failed   # 실패한 계정만 다시 수집
```

`failed` 는 경로를 외우지 않아도 되게 만든 별칭입니다
(`input` 도 있고, 별칭이 아닌 값은 파일 경로로 취급합니다).

#### 끊긴 지점부터 이어받기

게시물은 한 번에 다 오지 않고 30개씩 나눠 옵니다.
90건을 받다가 두 번째 묶음에서 끊기면, 먼저 받은 30건은 `posts.csv` 에 저장되고
실패 목록에 어디까지 받았는지가 남습니다.

```
collected_count=30   여기까지 확보함
max_media=all        원래 목표했던 수집량
resume_after=...     끊긴 지점 표시 (커서)
```

`crawling.py failed` 를 돌리면 **두 번째 묶음부터** 이어받습니다.
다만 이 표시는 순서대로만 따라갈 수 있어서, 실패한 묶음 하나만 골라
받지는 못하고 끊긴 지점부터 끝까지 이어집니다.

다음 두 경우에는 이어받지 않고 **처음부터 다시** 받습니다. 코드가 알아서 판단합니다.

| 상황 | 동작 |
|---|---|
| 표시가 이미 무효해짐 | 한 번 시도해 보고 실패하면 처음부터 |
| 실패한 지 12시간 넘음 (`RESUME_MAX_AGE_HOURS`) | 시도하지 않고 바로 처음부터 |

시간 제한을 두는 이유는 **좋아요 수가 계속 변하기 때문**입니다.
실측하니 하루 사이 게시물 30건 전부 값이 바뀌었고, 최근 게시물은 하루 +2.6% 였습니다.
앞부분을 어제, 뒷부분을 오늘 받으면 한 계정 안에서도 측정 시점이 어긋납니다.

> **실패 목록은 이번 실행의 결과만 남깁니다.**
> 실패가 있으면 덮어쓰고, 하나도 없으면 파일을 지웁니다.
> 전부 성공한 뒤 `failed` 를 또 돌리면 `입력 파일이 없습니다` 가 뜨는데,
> 그게 "다시 할 게 없다"는 뜻입니다. 이력을 남기려면 미리 복사해 두세요.

### 처음 상태로 되돌리기

다른 계정 목록으로 새로 시작할 때 씁니다.
폴더 안의 **파일만** 지우고 폴더 자체는 남기며, `.env` 와 파이썬 파일은 건드리지 않습니다.

```bash
python3 clean.py       # data/ output/ 을 지우고, input/ 은 물어본 뒤 결정
python3 clean.py --y   # 묻지 않고 input/ 까지 전부
```

`data/` 와 `output/` 은 다시 만들 수 있으므로 그냥 지웁니다.
되돌릴 수 없는 건 직접 쓴 `input/accounts.csv` 하나뿐이라 그것만 물어봅니다.

```
input/accounts.csv 도 지울까요? (아니오면 계정 목록만 남깁니다) [y/N]:
```

엔터만 치면 계정 목록은 남습니다.
질문이 삭제보다 먼저 나오므로, 아예 그만두려면 여기서 Ctrl+C 를 누르세요.

---

## 주의할 점

### 이미지 주소는 며칠이면 만료됩니다

`data/posts.csv` 의 `media_url` 은 Meta 가 임시로 발급하는 주소입니다.
실측 결과 **짧으면 1.3일, 보통 4.4일** 이었습니다 (60개 기준).

만료된 뒤에는 다운로드가 `expired` 로 실패하고, **재시도해도 계속 실패합니다.**
`crawling.py` 를 다시 돌려 새 주소를 받아야 합니다.

→ **1단계를 마치면 바로 2단계를 실행하세요.**

### 영상 주소를 아예 주지 않는 게시물이 있습니다

저작권 있는 음원이 포함된 영상(릴스)은 API 가 `media_url` 을 비운 채로 줍니다.
실측 결과 **영상 게시물의 약 13%** (569건 중 76건) 였습니다.
`thumbnail_url` 은 정상적으로 오므로 표지는 받아지지만, 영상은 받을 방법이 없습니다.

이런 행은 다운로드 요약에 `주소 없음` 으로 집계되고, 영상을 확보하지 못했으므로
`dataset.csv` 에는 들어가지 않습니다. 만료(expired)와 달리 `crawling.py` 를
다시 돌려도 해결되지 않습니다 — API 가 원래 주지 않는 값입니다.

### 시간당 호출 한도가 있습니다

Meta 는 시간당 200회로 제한합니다. 계정 하나에서 30건을 받는 데 1회를 씁니다.

`crawling.py` 는 사용률이 85% 를 넘으면 **스스로 70분 쉬었다가 재개**합니다.
기다리는 동안 `q + Enter` 나 `Ctrl+C` 를 누르면 그때까지 받은 것은 저장되고
남은 계정은 실패 목록으로 넘어갑니다.

### 조회되지 않는 계정이 있습니다

개인 계정과 연령 제한 계정은 Business Discovery 로 조회되지 않습니다.
권한 문제가 아니라 Meta 의 정책이라 우회할 방법이 없습니다.

---

## 이용 시 주의

이 저장소는 **도구만** 담고 있습니다. 수집한 데이터는 들어 있지 않고,
쓰려면 각자 Meta 개발자 계정과 토큰을 발급받아야 합니다
([meta_api_setup.txt](meta_api_setup.txt)).

### 인증 정보

- `access_token` 은 **비밀번호와 같습니다.** 노출되면 그 토큰으로 누구나
  내 계정 권한을 쓸 수 있으니, 실수로 커밋했다면 파일만 지우지 말고
  [Meta 앱 설정](https://developers.facebook.com/apps)에서 **새로 발급**받으세요.
- `.env` 는 `.gitignore` 에 등록돼 있습니다. 이 파일을 지우거나 옮기지 마세요.

### Meta 플랫폼 약관

[Meta 플랫폼 약관](https://developers.facebook.com/terms/)을 따라야 합니다.
직접 관련된 조항은 다음과 같습니다.

| 조항 | 내용 |
|---|---|
| 3.a.iv | 수집한 데이터를 **팔거나 라이선스**할 수 없습니다 |
| 3.a.viii | 개발자 문서에 설명된 **용도로만** 처리해야 합니다 |
| 3.d.i.2 | **더 이상 필요 없어지면 삭제**해야 합니다 (이용자가 요청한 경우 포함) |

Business Discovery 로 얻는 것은 **비즈니스·크리에이터 계정이 스스로 공개한 정보**
뿐입니다. 개인 계정과 연령 제한 계정은 애초에 조회되지 않습니다.

### 수집한 데이터

- `data/` 와 `output/` 도 `.gitignore` 에 있습니다. 실수로 올라가지 않습니다.
- 게시물 이미지·영상의 **저작권은 원 게시자에게 있습니다.** 내려받은 파일을
  재배포하거나 공개하지 마세요.
- 쓸 일이 끝나면 `python3 clean.py` 로 지우세요 (위 3.d.i.2).
- 지역에 따라 개인정보 보호법(GDPR, 국내 개인정보보호법 등)이 함께 적용될 수
  있습니다. 상업적으로 쓸 계획이라면 미리 확인하세요.

### 호출 한도

시간당 200회 제한을 지켜야 합니다. `crawling.py` 가 자동으로 조절하지만,
`REQUEST_DELAY` 를 줄이거나 여러 개를 동시에 돌리면 계정이 일시 차단될 수 있습니다.

---

## 설정값과 컬럼

값을 이 문서에 옮겨 적지 않습니다 — 코드가 바뀌면 문서만 낡기 때문입니다.

- **설정값** — [`crawling.py`](crawling.py) 상단 `여기만 수정해서 테스트하세요` 구획.
  각 값이 왜 그 숫자인지 주석과 함께 있습니다.
- **출력 컬럼** — `head -1 data/posts.csv` 로 확인. 각 컬럼의 의미는
  [`crawling.py`](crawling.py) 의 `_media_to_row()` 주석에 있습니다.
- **게시물 종류별 다운로드 규칙** — [`download_media.py`](download_media.py) 맨 위 설명.

---

## 파일 구성

```
.
├── LICENSE                    # MIT
├── crawling.py                # 1단계: 정보 수집
├── download_media.py          # 2단계: 파일 다운로드
├── csv_store.py               # CSV 저장 공용 함수 (덮어쓰기 / 쌓기)
├── clean.py                   # 세 폴더를 비워 처음 상태로 되돌림
├── meta_api_setup.txt         # .env 값 받는 방법 (단계별 안내)
├── requirements.txt           # 필요한 패키지
├── .env.example               # 인증 정보 서식 (.env 로 복사해 사용)
│
├── input/                     # 사람이 직접 작성
│   ├── accounts.example.csv   #   형식 예시 (이것만 저장소에 포함)
│   └── accounts.csv           #   조회할 계정 목록 (gitignore)
│
├── data/                      # 중간 결과 — 언제든 다시 만들 수 있음
│   ├── posts.csv              #   한 파일에 쌓임 (media_id 기준 갱신)
│   └── failed/
│       └── accounts.csv       #   수집 실패한 계정 (input/accounts.csv 와 같은 컬럼)
│
└── output/                    # 최종 데이터셋
    ├── dataset.csv            #   파일까지 확보된 행 + 경로 컬럼
    ├── images/
    └── videos/
```

---

## 라이선스

[MIT](LICENSE) — 자유롭게 쓰고 고치고 배포할 수 있습니다. 저작권 표시만 남겨 주세요.

이 라이선스는 **이 저장소의 코드에만** 적용됩니다.
수집한 데이터와 내려받은 이미지·영상에는 해당하지 않습니다 —
그쪽은 위 "이용 시 주의" 와 Meta 플랫폼 약관을 따릅니다.
