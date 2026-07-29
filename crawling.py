"""
1단계 — 인스타그램 계정·게시물 정보를 모아 data/posts.csv 에 저장합니다.
(2단계 download_media.py 가 그 CSV 의 URL 로 실제 이미지·영상을 내려받습니다.)

Meta 의 Business Discovery 기능을 씁니다. 내 인스타 비즈니스 계정으로 요청하면서
요청 안에 "보고 싶은 상대 계정의 아이디"를 적어 넣으면, 그 계정의 공개 정보
(팔로워 수·게시물·좋아요 수 등)를 돌려주는 방식입니다.
    - 내 계정과 상대 계정 모두 비즈니스/크리에이터 계정이어야 합니다.
      (개인 계정은 이 방식으로 조회되지 않습니다.)

준비물:
    pip install requests python-dotenv
    같은 폴더에 .env 파일:
        ig_user_id=17841400000000000   # 내 인스타 비즈니스 계정 ID
        access_token=EAAG...           # Instagram Graph API 액세스 토큰
    두 값을 받는 방법과 필요한 권한은 meta_api_setup.txt 에 정리되어 있습니다.

용어 (아래 주석에서 계속 나옵니다):
    페이지    API 는 게시물을 한 번에 다 주지 않고 PAGE_SIZE 개씩 끊어서 준다.
              그 한 묶음. 90개를 받으려면 30개짜리 페이지를 3번 요청한다.
    커서      다음 페이지가 어디서 시작하는지 가리키는 문자열. 응답에 딸려 온다.
              사람이 읽을 수 없고, 순서대로만 따라갈 수 있다 — 3페이지 커서는
              2페이지 응답에만 들어 있어서 중간 페이지 하나만 골라 받을 수 없다.
    이어받기  중간에 끊겼을 때 마지막 커서부터 다시 받는 것.

사용법:
    python3 crawling.py                  # MAX_MEDIA 설정값만큼 (기본 계정당 30건)
    python3 crawling.py failed           # 실패한 계정만 다시 (원래 요청량 그대로)
    python3 crawling.py --max N          # 이번 실행만 계정당 N건씩 (테스트용)
    python3 crawling.py --max all        # 계정의 게시물 전부
    python3 crawling.py failed --max N   # 별칭과 --max 를 함께 쓸 수도 있다
    python3 crawling.py <csv경로>        # 별칭 대신 파일 경로를 직접 지정
    python3 crawling.py --help           # 전체 옵션 (기본값도 함께 알려줍니다)
"""

import argparse
import csv
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from csv_store import append_csv, clear_csv, save_csv

load_dotenv()

IG_USER_ID = os.getenv("ig_user_id")
ACCESS_TOKEN = os.getenv("access_token")

# Meta 는 API 버전을 주기적으로 새로 내고 옛 버전은 언젠가 막는다.
GRAPH_API_VERSION = "v25.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# 응답이 오지 않을 때 포기하기까지 기다리는 시간(초)
TIMEOUT = 20

# ─────────────────────────────────────────────
# 여기만 수정해서 테스트하세요
# ─────────────────────────────────────────────

# 조회할 계정 목록 CSV (ig_username 컬럼을 읽어서 순서대로 수집).
# 명령줄 인자로 다른 파일을 넘기면 그쪽이 우선한다 (아래 INPUT_ALIASES 참고).
INPUT_CSV = "input/accounts.csv"

# 학습 데이터로 수집할 게시물 수 (계정당).
#   숫자 → 그 개수만큼 (최신 게시물부터)
#   None → 계정의 모든 게시물. 계정당 1000~2000건이면 PAGE_SIZE 로 나눈 만큼
#          호출이 들어가므로(예: 30씩이면 60회) 시간당 한도를 먼저 계산해 볼 것.
#   0    → 하나도 받지 않음 (전체가 아님. 전체는 None)
MAX_MEDIA = 30

# 한 번의 API 호출로 받아올 게시물 수 = 페이지 크기. MAX_MEDIA 와는 별개다.
# (MAX_MEDIA 를 그대로 쓰면 전체 수집 설정에서 media.limit(None) 이라는
#  말이 안 되는 요청이 만들어진다.)
# 크게 잡을수록 같은 개수를 받는 데 드는 호출이 줄지만(90건: 30이면 3회, 90이면 1회),
# Graph API 가 그 크기를 받아주는지는 한 계정에 먼저 돌려보고 올릴 것.
PAGE_SIZE = 30

# 수집 결과를 저장할 폴더 (없으면 자동 생성)
OUTPUT_DIR = "data"

# 실패한 계정 목록을 저장할 파일. 컬럼이 accounts.csv 와 같으므로
# 그대로 인자로 넘겨 재수집할 수 있다.
# (2단계 download_media.py 에는 이런 목록이 없다 — 이미 받은 파일을 건너뛰므로
#  그냥 다시 실행하면 못 받은 것만 시도한다. 이쪽은 API 호출이 시간당 200회로
#  제한돼 있어 전체 재실행이 비싸기 때문에 목록을 남긴다.)
FAILED_DIR = os.path.join(OUTPUT_DIR, "failed")
FAILED_CSV = os.path.join(FAILED_DIR, "accounts.csv")

# 수집 결과 CSV. 실행할 때마다 새 파일을 만들지 않고 이 파일 하나에 누적한다.
# 같은 media_id 를 다시 수집하면 새 행으로 갱신되므로, 만료된 URL 이 새 URL 로 교체된다.
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "posts.csv")

# 호출할 때마다 API 사용량을 화면에 찍을지 여부
SHOW_API_USAGE = True

# Meta 가 정한 시간당 호출 한도. 남은 횟수를 어림잡아 보여주는 데만 쓴다
# (Business Discovery 기준 시간당 200회 × 앱 사용자 수).
HOURLY_CALL_LIMIT = 200

# 호출과 호출 사이에 두는 최소 간격(초).
# 짧은 시간에 몰아서 부르면 한도가 남아 있어도 한동안 차단당한다.
REQUEST_DELAY = 2.0

# Meta 는 응답 헤더로 "지금까지 한도의 몇 %를 썼는지"를 알려준다
# (호출 수 / 응답시간 / CPU 세 가지). 그 중 가장 높은 값이 이 %를 넘으면
# 다음 호출 전에 쉰다. 셋 중 하나만 100% 에 닿아도 차단되기 때문이다.
USAGE_PAUSE_PCT = 85

# 쉬는 시간(초). 사용량 집계 구간이 1시간이라 그보다 조금 길게 잡아 확실히 비운다.
# 쉬는 동안 중단하면 그때까지 받은 것은 저장되고 남은 계정은 failed 로 간다.
USAGE_PAUSE_SECONDS = 70 * 60

# 이어받기용 커서를 몇 시간까지 믿을지. 실패 시각(failed_at)이 이보다 오래됐으면
# 커서를 버리고 처음부터 다시 받는다.
# 좋아요 수가 계속 변하기 때문이다(실측: 4일 된 게시물이 하루 +2.6%, 오래된
# 게시물도 +0.1%). 1페이지를 어제, 2페이지를 오늘 받으면 같은 계정 안에서도
# 행마다 측정 시점이 달라진다. 팔로워 수도 변해 참여율의 분모까지 흔들린다.
RESUME_MAX_AGE_HOURS = 12

# ─────────────────────────────────────────────

# 명령줄 인자로 쓸 수 있는 짧은 별칭 → 실제 경로.
# 경로를 외우지 않아도 되게 하려는 것이며, 별칭이 아니면 그대로 파일 경로로 본다.
#   python3 crawling.py           → input/accounts.csv (기본값)
#   python3 crawling.py failed    → data/failed/accounts.csv
#   python3 crawling.py 그밖의값  → 그 값을 경로로 사용
INPUT_ALIASES = {
    "input": INPUT_CSV,
    "failed": FAILED_CSV,
}


# 요청할 때 아래 목록에 적은 항목만 응답에 담겨 온다. 적지 않은 항목은 오지 않는다.

# 계정 단위로 받아올 항목
# - followers_count: 참여율(like_count/followers_count) 계산에 필수
# - follows_count(팔로잉 수) / media_count(총 게시물 수): 계정 성격을 나타내는 값
# 항목을 더 적어도 호출 수는 늘지 않는다. 반대로 빼 두면 나중에 필요해졌을 때
# 전 계정을 다시 크롤링해야 하니 신중히 뺄 것.
ACCOUNT_FIELDS = "username,name,followers_count,follows_count,media_count"


# 게시물 단위로 받아올 항목
# - like_count: 우리가 예측하려는 값(라벨). 계정이 좋아요 수를 숨기면 응답에서
#   아예 빠지므로, 0 이 아니라 "없음"으로 다뤄야 한다.
# - caption / media_type / media_product_type / timestamp: 예측에 쓸 입력값
# - view_count: 릴스·영상 조회수 (사진엔 없고, 광고 조회수도 섞여 들어온다)
# - media_url: 사진·영상 파일 주소. 며칠이면 만료되니 수집 직후 내려받아야 한다.
# - thumbnail_url: 영상의 표지 사진(.jpg). VIDEO 에만 오고 그 외에는 없다.
#   이게 없으면 릴스는 표지 이미지가 아예 없어 이미지 학습에서 빠진다.
# - children: 여러 장 넘기는 게시물(캐러셀)의 슬라이드 하나하나.
#   영상이 섞여 있다 (실측 210장 중 10장이 .mp4).
#   ↳ 개선 여지: media_type 을 함께 받아 놓고도 _media_to_row 가 media_url 만
#     쓰고 버린다. 그래서 download_media.py 는 URL 확장자로 영상인지 추측한다.
#     children_types 컬럼을 추가하면 추측이 없어지고, 이미 받아오는 값이라
#     호출도 안 늘고 재크롤링도 필요 없다.
MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,"
    "like_count,comments_count,view_count,"
    "media_url,thumbnail_url,permalink,timestamp,"
    "children{media_type,media_url}"
)


# "호출 한도를 넘었다"는 뜻의 오류 코드.
# 4/17/32/613 은 Meta 플랫폼 공통 한도, 80002 는 인스타그램 자체 한도다.
RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613, 80002}


def _header_json(response, header: str):
    """응답 헤더에 담긴 JSON 을 파싱합니다. 없거나 깨져 있으면 None.

    헤더가 이상해도 수집 자체는 계속되어야 하므로 예외를 삼킵니다.
    """
    raw = response.headers.get(header)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _print_app_usage(response) -> None:
    """지금까지 한도의 몇 %를 썼는지 화면에 보여줍니다.

    Graph API 는 "몇 번 더 부를 수 있다"를 알려주지 않고 사용률(%)만 줍니다.
    그래서 HOURLY_CALL_LIMIT 을 기준으로 남은 횟수를 거꾸로 계산해 함께 보여줍니다.
    호출/응답시간/CPU 중 하나만 100% 에 닿아도 막히므로 셋 다 출력합니다.
    """
    usage = _header_json(response, "X-App-Usage")
    if not isinstance(usage, dict):
        return

    used_pct = usage.get("call_count", 0)
    remaining = int(HOURLY_CALL_LIMIT * (100 - used_pct) / 100)
    print(
        f"[API 사용량] 호출 {used_pct}% (추정 잔여 ~{remaining}회/시간) | "
        f"응답시간 {usage.get('total_time', 0)}% | "
        f"CPU {usage.get('total_cputime', 0)}%"
    )


def _warn_if_throttled(response) -> None:
    """이미 한도를 넘어 차단된 상태면 경고를 출력합니다.

    X-Business-Use-Case-Usage 헤더는 {"<계정id>": [{...}, ...]} 형태로 오고,
    차단 중이면 estimated_time_to_regain_access 에 남은 분(minute)이 들어 있습니다.
    """
    buc = _header_json(response, "X-Business-Use-Case-Usage")
    if not isinstance(buc, dict):
        return

    groups = [g for g in buc.values() if isinstance(g, list)]
    for entry in [e for g in groups for e in g if isinstance(e, dict)]:
        wait_min = entry.get("estimated_time_to_regain_access", 0)
        if wait_min > 0:
            print(f"[경고] 요율 제한 — 접근 회복까지 약 {wait_min}분")


# 사용자가 q 를 눌러 중단을 요청했는지 나타내는 깃발.
# 아래 감시 스레드가 세우고, _get() 과 대기 함수가 확인한다.
_stop_event = threading.Event()


def _start_quit_watcher() -> bool:
    """입력을 지켜보다 q 가 들어오면 중단 깃발을 세웁니다. 감시를 시작했으면 True.

    Ctrl+C 는 파이썬이 알아서 KeyboardInterrupt 를 던져 주지만, q 는 누군가
    입력을 읽고 있어야 알 수 있어 별도 스레드를 띄웁니다. daemon=True 라
    본 작업이 끝나면 이 스레드도 같이 사라집니다.
    터미널이 아닌 곳에서 실행하면(파이프·크론 등) 받을 입력이 없어 감시하지 않습니다.
    """
    if not sys.stdin or not sys.stdin.isatty():
        return False

    def watch():
        for line in sys.stdin:
            if line.strip().lower() == "q":
                print("\n[중단 요청] q 입력 — 진행 중인 요청을 마치고 저장한 뒤 종료합니다")
                _stop_event.set()
                return

    threading.Thread(target=watch, daemon=True).start()
    return True


def _sleep_unless_stopped(seconds: float) -> None:
    """기다리되, 중간에 중단 요청이 오면 즉시 KeyboardInterrupt 로 빠져나옵니다.

    70분 대기를 time.sleep(4200) 한 번으로 처리하면 그동안 q 를 눌러도 반응이
    없습니다. 그래서 1초씩 나눠 자면서 깃발을 확인합니다.
    """
    end = time.monotonic() + seconds
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return
        if _stop_event.is_set():
            raise KeyboardInterrupt
        time.sleep(min(1.0, left))


def _pause_if_usage_high(response) -> None:
    """사용률이 높으면 집계가 비워질 때까지 미리 쉽니다.

    차단당한 뒤에는 어차피 최대 1시간을 기다려야 하므로, 그 전에 스스로 쉬는 편이
    낫습니다. 호출/응답시간/CPU 중 하나만 100% 에 닿아도 막히므로 최대값을 봅니다.
    """
    usage = _header_json(response, "X-App-Usage")
    if not isinstance(usage, dict):
        return

    def as_pct(value) -> float:
        # Meta 가 숫자를 문자열("90")로 주기도 해서 비교 전에 형을 맞춰 둔다
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    worst = max(as_pct(usage.get(k)) for k in ("call_count", "total_time", "total_cputime"))
    if worst < USAGE_PAUSE_PCT:
        return

    resume_at = (datetime.now() + timedelta(seconds=USAGE_PAUSE_SECONDS)).strftime("%H:%M")
    print(
        f"[대기] API 사용률 {worst:.0f}% (기준 {USAGE_PAUSE_PCT}%) — "
        f"{USAGE_PAUSE_SECONDS // 60}분 쉬었다가 {resume_at} 에 재개합니다. "
        f"중단하려면 q + Enter 또는 Ctrl+C (지금까지 받은 것은 저장됩니다)"
    )
    _sleep_unless_stopped(USAGE_PAUSE_SECONDS)
    print("[재개] 대기 완료 — 수집을 계속합니다")


# 마지막으로 API 를 부른 시각. REQUEST_DELAY 간격을 지키는 데 쓴다.
_last_call_at = 0.0


def _get(path: str, params: dict) -> dict:
    """Graph API 를 호출하는 공통 함수. access_token 은 여기서 자동으로 붙입니다.

    직전 호출로부터 REQUEST_DELAY 초를 반드시 띄워, 몰아서 부르다 차단되는 일을
    막습니다.

    실패해도 자동으로 다시 시도하지 않습니다. 그 계정의 수집을 멈추고 failed
    목록에 남기면, 사람이 원인을 보고 `crawling.py failed` 로 다시 돌립니다.
    (일시적인 오류인지는 실패 목록의 error_message 안 is_transient 로 판단합니다.)
    """
    global _last_call_at
    # 요청을 보내기 직전이 중단하기 가장 좋은 지점이다. 이미 받은 것은 그대로
    # 살아 있고, 호출을 새로 쓰지 않은 채 빠져나갈 수 있다.
    if _stop_event.is_set():
        raise KeyboardInterrupt

    params = {**params, "access_token": ACCESS_TOKEN}
    url = f"{BASE_URL}/{path}"

    wait = REQUEST_DELAY - (time.monotonic() - _last_call_at)
    if wait > 0:
        _sleep_unless_stopped(wait)

    response = requests.get(url, params=params, timeout=TIMEOUT)
    _last_call_at = time.monotonic()

    if SHOW_API_USAGE:
        _print_app_usage(response)
    _warn_if_throttled(response)  # 차단 경고는 설정과 무관하게 항상 알린다
    # 이번 응답은 이미 받아 뒀으므로, 쉬는 것은 실질적으로 "다음 호출 전"이 된다
    _pause_if_usage_high(response)

    if response.ok:
        return response.json()

    try:
        error = response.json().get("error", {})
    except ValueError:
        error = {"message": response.text}

    if error.get("code") in RATE_LIMIT_ERROR_CODES:
        raise RuntimeError(
            f"요율 제한 초과 — 최대 1시간 후 재시도하세요. "
            f"Instagram API 오류 ({response.status_code}): {error}"
        )
    raise RuntimeError(f"Instagram API 오류 ({response.status_code}): {error}")


class CrawlInterrupted(RuntimeError):
    """수집이 도중에 끊겼다는 예외. 끊긴 지점의 커서를 함께 실어 나른다.

    페이지를 여러 장 넘기다 실패하면 이미 받아 둔 게시물이 있는데, 그냥 예외만
    던지면 부르는 쪽이 "어디까지 받았는지" 알 길이 없다. 그래서 다음 요청에
    쓰려던 커서를 붙여 보낸다. 첫 페이지에서 실패하면 커서가 없어 None 이다.
    """

    def __init__(self, cause: Exception, resume_after):
        super().__init__(str(cause))
        self.cause = cause
        self.resume_after = resume_after


def _business_discovery_fields(username: str, media_expr: str) -> str:
    """요청에 넣을 fields 문자열을 만듭니다.

    business_discovery.username(대상아이디){계정항목, media.limit(30){게시물항목}}
    형태로, "누구의 무엇을 달라"를 한 줄에 담는 Graph API 특유의 문법입니다.
    """
    return (
        "business_discovery.username(" + username + ")"
        "{" + ACCOUNT_FIELDS + ","
        + media_expr + "{" + MEDIA_FIELDS + "}"
        "}"
    )


def iter_business_discovery_media(
    username: str, page_size: int = PAGE_SIZE, max_count=None, start_after=None
):
    """페이지를 한 장씩 넘겨가며 (계정정보, 게시물) 을 하나씩 내보냅니다.

    max_count:   None 이면 전부, 0 이면 하나도 가져오지 않습니다.
    start_after: 이 커서 다음부터 시작합니다(이어받기). 커서는 순서대로만 따라갈
                 수 있어서, 실패한 페이지 하나만 골라 받지는 못하고 끊긴 지점부터
                 끝까지 쭉 이어집니다.

    팔로워 수 같은 계정 정보가 페이지마다 응답에 같이 딸려 옵니다. 그래서 계정
    정보를 얻으려고 따로 호출할 필요가 없고, 게시물과 짝지어 함께 내보냅니다.
    """
    if max_count is not None and max_count <= 0:
        return

    fetched = 0
    after = start_after

    while True:
        if after:
            media_expr = f"media.after({after}).limit({page_size})"
        else:
            media_expr = f"media.limit({page_size})"

        fields = _business_discovery_fields(username, media_expr)
        try:
            bd = _get(IG_USER_ID, {"fields": fields}).get("business_discovery", {})
        except (RuntimeError, requests.RequestException) as e:
            # 어느 지점에서 끊겼는지 실어 보낸다 (after 는 이번 요청이 쓰려던 커서)
            raise CrawlInterrupted(e, after) from e
        media = bd.get("media", {})

        # 게시물이 하나도 없으면 커서가 남아 있어도 여기서 끝낸다.
        # "커서가 없을 때만 종료"로 두면, API 가 빈 응답과 커서를 계속 주는 경우
        # 요청을 무한히 보내 한 계정이 시간당 한도를 다 써 버린다.
        items = media.get("data", [])
        if not items:
            return

        for item in items:
            yield bd, item
            fetched += 1
            if max_count is not None and fetched >= max_count:
                return

        after = media.get("paging", {}).get("cursors", {}).get("after")
        if not after:
            return


def _parse_timestamp(ts):
    """Graph API 의 '2024-01-15T12:34:56+0000' 형식을 datetime 으로 변환합니다."""
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None


def _media_to_row(media: dict, account: dict, country: str, crawled_at: datetime) -> dict:
    """게시물 1개를 학습용 CSV 행(dict)으로 변환합니다."""
    followers = account.get("followers_count")

    # 좋아요 수를 숨긴 계정은 like_count 가 응답에 아예 없다.
    # 이때 0 으로 바꾸면 "좋아요 0개"와 구분이 안 되므로 None 그대로 둔다.
    like_count = media.get("like_count")

    # 참여율 = 좋아요 / 팔로워. 팔로워 수가 제각각인 계정을 한 데이터셋에 섞을 때,
    # 좋아요 수 자체보다 서로 비교하기 좋다.
    engagement_rate = None
    if like_count is not None and followers:
        engagement_rate = round(like_count / followers, 6)

    posted_at = _parse_timestamp(media.get("timestamp"))
    children = media.get("children", {}).get("data", [])

    return {
        # 이름이 ig_ 로 시작하면 계정 단위 값이라는 뜻이다. 게시물 단위 값
        # (media_*, like_count 등)과 구분하려는 규칙이고, 같은 계정의 행에는
        # 같은 값이 반복해서 들어간다.
        # ig_username 과 country 의 이름은 accounts.csv 와 똑같이 맞춰 두었다.
        # 그래야 이 출력 CSV 를 다음 실행의 입력으로 그대로 쓸 수 있다.
        "ig_username": account.get("username"),
        # 프로필에 보이는 이름. 계정이 설정하지 않았으면 응답에 없어 None 이 된다
        "ig_name": account.get("name"),
        "ig_followers_count": followers,
        "ig_follows_count": account.get("follows_count"),
        # 계정이 올린 전체 게시물 수. 게시물 단위 값과 헷갈리지 않도록 ig_ 를 붙였다
        "ig_media_count": account.get("media_count"),
        "country": country,
        "media_id": media.get("id"),
        "media_type": media.get("media_type"),
        "media_product_type": media.get("media_product_type"),
        "caption": media.get("caption"),
        "like_count": like_count,
        "comments_count": media.get("comments_count"),
        "view_count": media.get("view_count"),
        "engagement_rate": engagement_rate,
        "timestamp": media.get("timestamp"),
        "posted_hour": posted_at.hour if posted_at else None,
        "posted_weekday": posted_at.strftime("%a") if posted_at else None,
        "post_age_days": (crawled_at - posted_at).days if posted_at else None,
        "permalink": media.get("permalink"),
        "media_url": media.get("media_url"),
        # 영상의 표지 사진. VIDEO 가 아니면 응답에 없어 None 이 된다
        "thumbnail_url": media.get("thumbnail_url"),
        "children_count": len(children),
        "children_urls": ";".join(c.get("media_url", "") for c in children),
        "crawled_at": crawled_at.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def _is_usable(media: dict) -> bool:
    """CSV 행으로 쓸 수 있는 게시물인지 확인합니다. media_id 만 봅니다.

    media_id 는 파일 이름이자 중복 판정 기준이자 두 CSV 를 잇는 열쇠라, 이게
    없으면 그 행은 쓸모가 없습니다 (파일 이름이 "_cover.jpg" 로 다 같아져 서로
    덮어써 버립니다). 다른 값이 비어 있는 건 좋아요를 숨긴 계정처럼 정상적인
    경우도 있어서 여기서 막지 않습니다.
    """
    return bool(str(media.get("id") or "").strip())


def _collect_once(username: str, country: str, max_count, start_after) -> tuple:
    """수집을 한 번 시도합니다. 반환: (수집한 행들, 실패 정보 dict 또는 None)

    중간에 끊겨도 그때까지 받은 행을 함께 돌려주는 것이 핵심입니다. 예외를 그냥
    밖으로 던지면 이미 받아 둔 게시물이 통째로 버려지고, 거기 쓴 API 호출도
    함께 날아갑니다.
    """
    crawled_at = datetime.now(timezone.utc)

    rows = []
    account = None
    failure = None
    skipped = 0
    # 언제 중단되더라도 이어받을 수 있도록, 다 받은 페이지의 "다음 커서"를 계속 갱신한다
    next_cursor = start_after

    try:
        for page_account, media in iter_business_discovery_media(
            username, max_count=max_count, start_after=start_after
        ):
            # 계정 정보는 페이지마다 새로 오지만, 참여율의 분모(팔로워 수)가 행마다
            # 달라지면 안 되므로 첫 페이지에서 받은 값으로 고정한다
            if account is None:
                account = page_account
            if not _is_usable(media):
                skipped += 1
                continue
            rows.append(_media_to_row(media, account, country, crawled_at))
            next_cursor = (
                page_account.get("media", {}).get("paging", {}).get("cursors", {}).get("after")
                or next_cursor
            )
    except CrawlInterrupted as e:
        failure = {
            "error_type": type(e.cause).__name__,
            "error_message": str(e.cause),
            # 끊긴 요청이 쓰려던 커서. 다음 실행이 이걸 start_after 로 넘기면
            # 실패한 페이지부터 다시 이어진다.
            "resume_after": e.resume_after or "",
        }
    except KeyboardInterrupt:
        # 여기서 잡지 않으면 예외가 main() 밖으로 빠져나가 저장 코드에 닿지 못하고,
        # 이미 받아 둔 행이 통째로 버려진다 (70분 대기 중 중단이 특히 흔하다).
        how = "q 입력" if _stop_event.is_set() else "Ctrl+C"
        failure = {
            "error_type": "KeyboardInterrupt",
            "error_message": f"사용자가 중단했습니다 ({how})",
            "resume_after": next_cursor or "",
            # main() 이 남은 계정까지 기록하고 루프를 끝내도록 알린다
            "interrupted": True,
        }

    if skipped:
        print(f"       [경고] media_id 가 없어 쓸 수 없는 게시물 {skipped}건을 건너뛰었습니다")

    return rows, failure


def collect_training_data(
    username: str, country: str = "", max_count: int = MAX_MEDIA,
    start_after=None, already: int = 0,
) -> tuple:
    """계정 하나에서 학습용 데이터 행들을 수집합니다.

    반환: (수집한 행들, 실패 정보 dict 또는 None)

    start_after 가 있으면 그 커서부터 이어받고, 이미 확보한 already 개를 뺀
    나머지만 받습니다. 커서가 아직 통하는지는 써 보기 전에는 알 수 없으므로,
    커서로 보낸 첫 요청이 실패하면 커서를 버리고 처음부터 다시 받습니다
    (헛수고는 호출 1회로 끝납니다).

    실패 정보의 collected_count 에는 already 를 더해 둡니다. 그래야 다음 재개가
    "지금까지 총 몇 개"를 이어서 계산합니다. 처음부터 다시 받은 경우엔 더하지
    않습니다.
    """
    if start_after:
        remaining = None if max_count is None else max(max_count - already, 0)
        rows, failure = _collect_once(username, country, remaining, start_after)
        # 행이 하나라도 왔으면 커서는 통한 것이므로 그 결과를 그대로 쓴다.
        # 아예 성공했거나 사용자가 중단한 경우에도 처음부터 다시 받지 않는다.
        if rows or failure is None or failure.get("interrupted"):
            if failure:
                failure["collected_count"] = already + len(rows)
            print(f"@{username}: 이어받아 {len(rows)}개 수집 (누적 {already + len(rows)}개)"
                  + (" — 중단됨" if failure else ""))
            return rows, failure
        print("       커서가 유효하지 않아 처음부터 받습니다")

    rows, failure = _collect_once(username, country, max_count, None)
    if failure:
        failure["collected_count"] = len(rows)
    print(f"@{username}: 게시물 {len(rows)}개 수집" + (" (중단됨)" if failure else ""))
    return rows, failure


def load_accounts(path: str = INPUT_CSV) -> list:
    """입력 CSV 에서 계정 목록을 읽어 dict 리스트로 돌려줍니다.

    ig_username 과 country 는 항상 채워집니다. 이어받기 정보(resume_after /
    collected_count / failed_at)는 failed CSV 를 넘겼을 때만 값이 있고,
    input/accounts.csv 에는 그 컬럼 자체가 없어 빈 값 → 처음부터 수집합니다.

    계정 이름은 입력받지 않습니다 — 인스타 프로필에 적힌 이름을 API 응답에서
    그대로 가져와 출력 CSV 의 ig_name 에 담습니다.
    """
    accounts = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            username = (row.get("ig_username") or "").strip()
            if not username:  # 빈 줄은 건너뜀
                continue
            try:
                collected = int(row.get("collected_count") or 0)
            except ValueError:  # 손으로 고치다 값이 깨진 경우 → 처음부터 받는다
                collected = 0
            accounts.append(
                {
                    "ig_username": username,
                    "country": (row.get("country") or "").strip(),
                    "resume_after": (row.get("resume_after") or "").strip(),
                    "collected_count": collected,
                    # 그때 목표로 했던 수집량. 재시도할 때 --max 를 다시 치지
                    # 않아도 원래 요청량을 그대로 이어가려고 남겨 둔다.
                    "max_media": (row.get("max_media") or "").strip(),
                    "failed_at": (row.get("failed_at") or "").strip(),
                    # 값이 잘못됐을 때 "몇 행"인지 알려주려고 기록해 둔다.
                    # 빈 줄을 건너뛰는 탓에 목록 순번과 실제 행 번호가 어긋난다.
                    "csv_line": reader.line_num,
                }
            )
    return accounts


# "--max 를 아예 주지 않았다"를 나타내는 전용 값.
# None 은 이미 "전체"라는 뜻으로 쓰고 있어서 대신 쓸 수 없다.
_UNSET = object()


def _parse_max(value: str):
    """--max 로 받았거나 CSV 에 적힌 문자열을 수집 개수로 바꿉니다.

    "all" → None(전체), "30" → 30. 그 밖의 값이면 그 자리에서 중단합니다.
    """
    text = (value or "").strip().lower()
    if text == "all":
        return None
    try:
        number = int(text)
    except ValueError:
        raise SystemExit(f"수집 개수는 숫자이거나 'all' 이어야 합니다: {value!r}")
    if number < 0:
        raise SystemExit(f"수집 개수는 0 이상이어야 합니다: {number}")
    return number


def _format_max(max_count) -> str:
    """_parse_max 의 반대. 수집 개수를 CSV 에 적을 문자열로 바꿉니다 (None → "all")."""
    return "all" if max_count is None else str(max_count)


def _resume_cursor(account: dict):
    """이 계정을 어느 커서부터 이어받을지 정합니다. 없거나 오래됐으면 None(처음부터).

    오래된 커서를 버리는 이유는 RESUME_MAX_AGE_HOURS 설명을 보세요 —
    좋아요 수가 계속 변해서, 며칠에 걸쳐 모은 행은 서로 비교할 수 없게 됩니다.
    """
    cursor = account.get("resume_after")
    if not cursor:
        return None

    failed_at = _parse_timestamp(account.get("failed_at"))
    if failed_at is None:  # 실패 시각을 못 읽으면 커서가 언제 것인지 모르니 처음부터
        return None

    age_hours = (datetime.now(timezone.utc) - failed_at).total_seconds() / 3600
    if age_hours > RESUME_MAX_AGE_HOURS:
        print(f"       커서가 {age_hours:.0f}시간 전 것이라 버리고 처음부터 받습니다")
        return None
    return cursor


def _resolve_max_counts(accounts: list, cli_max) -> None:
    """계정마다 몇 개를 받을지 미리 정해 account["max_count"] 에 넣어 둡니다.

    우선순위: ① --max 로 직접 준 값  ② failed CSV 의 max_media(재시도 때 물려받음)
              ③ MAX_MEDIA 설정값

    수집 루프에 들어가기 "전에" 검사하는 것이 핵심입니다. 루프 안에서 검사하면
    값이 깨진 계정 하나 때문에 프로그램이 멈추고, 앞 계정에서 받아 메모리에만
    있던 행이 저장되지 못한 채 사라집니다. 여기라면 API 호출 전이라 잃을 게 없습니다.
    """
    for account in accounts:
        if cli_max is not _UNSET:
            account["max_count"] = cli_max
        elif account["max_media"]:
            try:
                account["max_count"] = _parse_max(account["max_media"])
            except SystemExit as e:
                raise SystemExit(f"{account['csv_line']}행 @{account['ig_username']} — {e}")
        else:
            account["max_count"] = MAX_MEDIA


def _parse_args():
    """명령줄 인자를 해석합니다. --help 는 argparse 가 만들어 줍니다."""
    parser = argparse.ArgumentParser(
        description="Instagram Business Discovery 로 계정·게시물 정보를 수집합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        # 기본값을 직접 적지 않고 MAX_MEDIA 에서 읽어 온다. 설정을 바꿔도
        # --help 가 늘 실제 값을 보여주게 하려는 것.
        epilog=(
            "예시:\n"
            f"  python3 crawling.py                # MAX_MEDIA 설정값만큼 "
            f"(현재 계정당 {_format_max(MAX_MEDIA)})\n"
            "  python3 crawling.py failed         # 실패한 계정만 다시 (원래 요청량 그대로)\n"
            "  python3 crawling.py --max N        # 이번 실행만 계정당 N건씩 (테스트용)\n"
            "  python3 crawling.py --max all      # 계정의 게시물 전부\n"
            "  python3 crawling.py failed --max N # 별칭과 --max 를 함께 쓸 수도 있다\n"
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        help=f"별칭({' / '.join(INPUT_ALIASES)}) 또는 CSV 경로. 생략하면 {INPUT_CSV}",
    )
    parser.add_argument(
        "--max",
        dest="max_media",
        metavar="N",
        help=(
            "계정당 수집할 게시물 수. N 은 숫자, 'all' 이면 전체. "
            "생략하면 failed CSV 에 적힌 값을, 그것도 없으면 "
            f"MAX_MEDIA 설정값(기본 {_format_max(MAX_MEDIA)})을 씁니다."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if not IG_USER_ID or not ACCESS_TOKEN:
        raise SystemExit(".env 에 ig_user_id 와 access_token 을 설정하세요.")

    # 별칭이면 실제 경로로 바꾸고, 별칭이 아니면 받은 값을 그대로 경로로 본다.
    # download_media.py 도 같은 방식이라 두 스크립트의 사용법이 똑같다.
    input_csv = INPUT_ALIASES.get(args.source, args.source) if args.source else INPUT_CSV
    if not os.path.exists(input_csv):
        raise SystemExit(
            f"입력 파일이 없습니다: {input_csv}\n"
            f"  쓸 수 있는 별칭: {', '.join(INPUT_ALIASES)}"
        )

    # --max 를 준 경우에만 값이 담기고, 안 주면 계정마다 따로 정한다
    # (_resolve_max_counts 의 우선순위 참고)
    cli_max = _parse_max(args.max_media) if args.max_media is not None else _UNSET

    accounts = load_accounts(input_csv)
    if not accounts:
        raise SystemExit(
            f"{input_csv} 에서 계정을 하나도 읽지 못했습니다 — "
            f"'ig_username' 컬럼명이 정확한지 확인하세요."
        )

    # 값이 깨져 있으면 API 를 한 번도 쓰지 않은 채 여기서 중단된다
    _resolve_max_counts(accounts, cli_max)

    print(f"{input_csv} 에서 계정 {len(accounts)}개 로드")
    keys = "q + Enter 또는 Ctrl+C" if _start_quit_watcher() else "Ctrl+C"
    print(f"  중단하려면 {keys} — 받은 것까지 저장하고 나머지는 failed 로 갑니다")

    all_rows = []
    failed = []
    for i, account in enumerate(accounts, start=1):
        username, country = account["ig_username"], account["country"]
        print(f"\n[{i}/{len(accounts)}] @{username} 수집 중...")

        max_count = account["max_count"]  # _resolve_max_counts 가 미리 정해 둔 값

        # failed CSV 를 넘겼을 때만 커서가 있다. 너무 오래된 커서면 None(처음부터).
        start_after = _resume_cursor(account)
        already = account["collected_count"] if start_after else 0
        if start_after:
            left = "전부" if max_count is None else f"{max(max_count - already, 0)}개"
            print(f"       이어받기: 이미 {already}개 확보, 나머지 {left} 요청")

        rows, failure = collect_training_data(
            username, country, max_count=max_count, start_after=start_after, already=already
        )
        # 중단됐더라도 받은 만큼은 항상 저장한다 (거기 쓴 API 호출을 버리지 않으려고)
        all_rows.extend(rows)

        if failure:
            # 아이디 오타, 개인 계정, 연령 제한, 네트워크 오류 등 → 적어 두고 다음 계정으로
            failed.append(
                {
                    "ig_username": username,
                    "country": country,
                    # 0 이면 계정에 아예 닿지 못한 것(오타·비공개),
                    # 0 보다 크면 받다가 끊긴 것(대개 일시적인 장애)
                    "collected_count": failure["collected_count"],
                    "max_media": _format_max(max_count),
                    "resume_after": failure["resume_after"],
                    "error_type": failure["error_type"],
                    "error_message": failure["error_message"],
                    "failed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
            )
            print(f"[실패] @{username}: {failure['error_message']}")

            if failure.get("interrupted"):
                # 아직 손도 못 댄 계정까지 실패 목록에 넣어야 다음 실행이 이어간다.
                # 여기서 break 하지 않으면 "중단하겠다"는 의도를 무시하고 계속 돈다.
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
                for rest in accounts[i:]:
                    failed.append(
                        {
                            "ig_username": rest["ig_username"],
                            "country": rest["country"],
                            "collected_count": rest["collected_count"],
                            "max_media": _format_max(rest["max_count"]),
                            "resume_after": rest["resume_after"],
                            "error_type": "NotAttempted",
                            "error_message": "이전 실행이 중단되어 시도하지 못했습니다",
                            "failed_at": now,
                        }
                    )
                print(f"       → {len(rows)}개는 저장하고 중단합니다 "
                      f"(남은 계정 {len(accounts) - i}개도 실패 목록에 기록)")
                break

            print(f"       → {len(rows)}개는 저장하고 다음 계정으로 넘어갑니다")

    append_csv(all_rows, OUTPUT_CSV)

    print(f"\n=== 완료: 성공 {len(accounts) - len(failed)}개 / 실패 {len(failed)}개 ===")
    if failed:
        os.makedirs(FAILED_DIR, exist_ok=True)
        save_csv(failed, FAILED_CSV)
        print(f"실패한 계정: {', '.join('@' + f['ig_username'] for f in failed)}")
        print(f"  재시도: python3 {os.path.basename(__file__)} failed")
    else:
        # 전부 성공했으면 예전 실패 목록을 지운다 — 남겨 두면 다음 'failed' 실행이
        # 이미 성공한 계정을 다시 긁는다.
        clear_csv(FAILED_CSV, "실패 계정 목록")


if __name__ == "__main__":
    main()
