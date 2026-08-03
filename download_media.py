"""
2단계 — data/posts.csv 에 적힌 주소에서 실제 이미지·영상 파일을 내려받습니다.
(1단계 crawling.py 가 그 CSV 를 만듭니다.)

파일 이름은 게시물 ID(media_id)로 붙입니다. 그래야 나중에 CSV 의 한 행과
내려받은 파일을 서로 짝지을 수 있습니다.

산출물:
  output/images/, output/videos/  내려받은 파일
  output/dataset.csv              받아야 할 파일을 하나도 빠짐없이 받은 행 + 파일 경로
                                  (media_url 은 며칠이면 만료되지만 이 경로는 남는다)

게시물 종류(media_type)마다 받아야 할 파일이 다릅니다.
실측한 60행의 구성은 CAROUSEL 29 / VIDEO 24 / IMAGE 7 이었습니다.

  IMAGE           사진 한 장.
                  media_url          → images/{media_id}_cover.jpg

  CAROUSEL_ALBUM  옆으로 넘기는 여러 장짜리 게시물. 슬라이드 주소가
                  children_urls 에 ";" 로 이어 붙어 있다.
                  첫 장이 _cover, 그다음부터 _child_1, _child_2...
                  슬라이드에 영상이 섞여 있을 수 있어 확장자로 갈라 저장한다.

  VIDEO (릴스)    media_url 이 영상 파일.
                  media_url          → videos/{media_id}.mp4
                  thumbnail_url      → images/{media_id}_cover.jpg  (표지 사진)
                  thumbnail_url 컬럼이 없는 옛 CSV 는 표지 없이 영상만 받는다.

                  저작권 음원이 포함된 영상은 API 가 media_url 을 아예 비워서
                  준다 (실측 영상 569건 중 76건, 13%). thumbnail_url 은 정상이라
                  표지는 받아지지만 영상은 받을 방법이 없다. 이런 행은 "주소
                  없음(no_url)"으로 집계하고, 영상을 확보하지 못했으므로
                  dataset.csv 에는 넣지 않는다. 재수집해도 해결되지 않는다.

주소는 며칠이면 만료되므로, 받기 전에 만료 여부를 먼저 확인합니다(is_expired).
같은 파일을 두 번 받지 않도록 주소 전체가 아니라 파일 이름으로 중복을 판단합니다
— 같은 파일이라도 요청할 때마다 주소 뒤의 서명 값이 달라지기 때문입니다.

실패하거나 중간에 멈춘 경우, 재시도 목록 같은 것 없이 **같은 명령을 다시 실행하면**
됩니다. 이미 받아 둔 파일은 건너뛰므로(skip) 못 받은 것만 다시 시도하게 됩니다.
crawling.py 와 달리 재실행 비용이 사실상 0 이라 실패 목록을 따로 두지 않습니다.

q + Enter 나 Ctrl+C 로 중간에 멈출 수 있습니다. 받은 파일과 dataset.csv 는
그대로 남고, 다시 실행하면 멈춘 지점부터 이어집니다.

사용법:
    python3 download_media.py            # data/posts.csv (기본값)
    python3 download_media.py <csv경로>  # 다른 CSV 를 지정
"""

import csv
import os
import sys
import threading
import time
from urllib.parse import urlparse, parse_qs

import requests

from csv_store import append_csv

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# 중간 산출물 — crawling.py 가 여기에 수집 결과를 누적한다
DATA_DIR = os.path.join(ROOT_DIR, "data")
POSTS_CSV = os.path.join(DATA_DIR, "posts.csv")

# 최종 산출물 — 내려받은 파일과, 그 파일이 모두 확보된 행만 담은 dataset.csv
OUTPUT_DIR = os.path.join(ROOT_DIR, "output")
IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")
VIDEOS_DIR = os.path.join(OUTPUT_DIR, "videos")
DATASET_CSV = os.path.join(OUTPUT_DIR, "dataset.csv")

TIMEOUT = 30       # 응답이 오지 않을 때 포기하기까지 기다리는 시간(초)
RETRIES = 3        # 한 파일을 최대 몇 번까지 다시 시도할지
RETRY_WAIT = 2     # 재시도 전 대기(초). 시도할수록 늘어난다 (2초 → 4초 → …)

# 세션을 하나 만들어 재사용하면 매번 연결을 새로 맺지 않아 빠르다.
# 인스타 CDN 이 낯선 프로그램의 요청을 막기도 해서 브라우저처럼 보이게 해 둔다.
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})


# 사용자가 q 를 눌러 중단을 요청했는지 나타내는 깃발.
# 아래 감시 스레드가 세우고, 다운로드 반복문이 행마다 확인한다.
_stop_event = threading.Event()


def start_quit_watcher() -> bool:
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
                print("\n[중단 요청] q 입력 — 받던 파일을 마치고 저장한 뒤 종료합니다")
                _stop_event.set()
                return

    threading.Thread(target=watch, daemon=True).start()
    return True


def default_csv() -> str:
    """인자를 안 줬을 때 쓸 CSV 경로. crawling.py 가 여기 한 파일에 계속 쌓는다."""
    if not os.path.exists(POSTS_CSV):
        sys.exit(
            f"[에러] 수집 CSV 가 없습니다: {os.path.relpath(POSTS_CSV, ROOT_DIR)}\n"
            f"        먼저 crawling.py 를 실행하세요."
        )
    return POSTS_CSV


def url_basename(url: str) -> str:
    """주소에서 파일 이름만 뽑아냅니다. 뒤에 붙은 서명 값은 버립니다.

    같은 파일이라도 주소는 매번 달라지므로, 중복 판단은 이 이름으로 합니다.
    """
    return os.path.basename(urlparse(url).path)


def url_ext(url: str) -> str:
    """저장할 확장자를 정합니다. 영상(.mp4)만 구분하고 이미지는 전부 ".jpg" 입니다.

    주소 경로의 확장자는 업로드된 "원본" 파일 기준이라 .heic(아이폰 원본)나
    .webp 가 섞여 있습니다. 하지만 주소에 붙은 stp=dst-jpg 값이 CDN 에게
    JPEG 로 변환해 보내라는 지시여서, 실제 받는 내용물은 항상 JPEG 입니다.
    경로의 확장자를 그대로 쓰면 내용은 JPEG 인데 이름만 .heic 인 파일이
    생기므로, 경로로는 영상 여부만 가리고 이미지는 .jpg 로 통일합니다.
    """
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ".mp4" if ext == ".mp4" else ".jpg"


def is_expired(url: str) -> bool:
    """주소가 이미 만료됐는지 확인합니다.

    인스타 주소에는 oe= 라는 값이 붙어 있고, 그게 만료 시각입니다
    (16진수로 적힌 Unix timestamp). 받아 보기 전에 미리 걸러낼 수 있습니다.
    """
    oe = parse_qs(urlparse(url).query).get("oe", [None])[0]
    if not oe:
        return False
    try:
        return int(oe, 16) < time.time()
    except ValueError:
        return False


def download(url: str, dest_path: str) -> str:
    """파일 하나를 내려받아 dest_path 에 저장합니다. 이미 있으면 건너뜁니다.

    반환값은 아래 다섯 중 하나이며, main() 의 집계 딕셔너리 키와 같습니다.
    "ok"(받음) / "skip"(이미 있음) / "no_url"(주소 없음) / "expired"(주소 만료)
    / "fail"(재시도해도 실패)
    """
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        return "skip"
    if not url:
        # 저작권 음원이 포함된 영상은 API 가 media_url 을 주지 않는다 (파일 맨 위
        # 설명 참고). 빈 주소로 요청하면 어차피 실패하는데 재시도 3회에 6초를
        # 낭비하고, "다시 실행하면 된다"는 fail 로 잘못 집계되므로 여기서 가른다.
        return "no_url"
    if is_expired(url):
        return "expired"

    for attempt in range(1, RETRIES + 1):
        try:
            resp = session.get(url, timeout=TIMEOUT, stream=True)
            resp.raise_for_status()
            # 일단 .part 라는 임시 이름으로 받고, 다 받은 뒤에야 진짜 이름으로 바꾼다.
            # 중간에 끊겨도 반쪽짜리 파일이 "이미 받은 파일"로 오해받지 않는다.
            tmp_path = dest_path + ".part"
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    f.write(chunk)
            os.replace(tmp_path, dest_path)
            return "ok"
        except requests.RequestException as e:
            if attempt == RETRIES:
                print(f"    [실패] {os.path.basename(dest_path)}: {e}")
                return "fail"
            time.sleep(RETRY_WAIT * attempt)

    # RETRIES 를 0 으로 두면 위 반복문이 한 번도 돌지 않는다. 그때 아무것도
    # 돌려주지 않으면 부르는 쪽에서 집계하다 KeyError 가 나므로 여기서 막는다.
    return "fail"


def check_columns(rows: list[dict[str, str]], csv_path: str) -> None:
    """1단계가 만든 CSV 가 맞는지 필수 컬럼으로 확인합니다.

    엉뚱한 CSV 를 넘겼을 때 한참 돌다 알 수 없는 오류로 죽는 대신,
    시작하자마자 무엇이 없는지 알려주기 위한 것입니다.
    """
    required = {"media_id", "media_type", "media_url", "children_urls"}
    missing = required - set(rows[0].keys())
    if missing:
        sys.exit(
            f"[에러] {os.path.basename(csv_path)} 는 수집 CSV 가 아닙니다 — "
            f"필수 컬럼 없음: {', '.join(sorted(missing))}\n"
            f"        실제 컬럼: {', '.join(rows[0].keys())}"
        )


def dataset_row(row: dict[str, str], tasks: list[tuple[str, str]]) -> dict[str, str]:
    """다 받은 게시물 하나를 dataset.csv 에 넣을 행으로 만듭니다.

    원래 컬럼에 파일 경로 두 개를 덧붙입니다. output/ 폴더 기준의 상대경로라
    폴더를 통째로 옮겨도 그대로 동작하고, 며칠이면 만료되는 media_url 과 달리
    계속 유효합니다.
    """
    files = [os.path.relpath(dest, OUTPUT_DIR) for _, dest in tasks]
    cover = next(
        (f for f in files if os.path.basename(f).split(".")[0].endswith("_cover")
         and f.startswith("images")),
        "",
    )
    return {**row, "cover_path": cover, "local_files": ";".join(files)}


def save_dataset_csv(done_rows: list[dict[str, str]]) -> None:
    """파일을 전부 확보한 행을 output/dataset.csv 에 쌓습니다.

    덮어쓰면 안 됩니다 — 중간에 멈췄다 다시 실행하거나 다른 CSV 를 넘겨 돌리면,
    이번에 다루지 않은 기존 완료분이 통째로 사라집니다. media_id 기준으로 쌓기
    때문에 여러 번 나눠 실행해도 한 파일에 모입니다.
    """
    print(f"완료 게시물 {len(done_rows)}건 → {os.path.relpath(DATASET_CSV, ROOT_DIR)}")
    append_csv(done_rows, DATASET_CSV)


def plan_row(row: dict[str, str]) -> list[tuple[str, str]]:
    """CSV 한 행에서 "무엇을 어디에 받을지" 목록을 만듭니다 → [(주소, 저장경로)].

    게시물 종류별 규칙은 파일 맨 위 설명을 보세요.
    여기서는 이름 규칙만 계산하고 네트워크는 전혀 쓰지 않습니다. 그래서 실제로
    내려받지 않고도 계획이 맞는지 따로 확인할 수 있습니다.
    """
    media_id = row["media_id"].strip()
    media_type = row["media_type"].strip()
    media_url = row["media_url"].strip()
    tasks: list[tuple[str, str]] = []

    if media_type == "IMAGE":
        tasks.append((media_url, os.path.join(IMAGES_DIR, f"{media_id}_cover{url_ext(media_url)}")))

    elif media_type == "CAROUSEL_ALBUM":
        # 보통 media_url 은 첫 슬라이드와 같은 사진이라, 슬라이드 목록만 받으면 된다.
        # 예외 — 첫 슬라이드가 영상이면 children[0] 은 .mp4 이고, media_url 은
        # 인스타가 따로 만들어 준 .jpg 표지다. 이때는 중복이 아니므로 함께 받아야
        # 이 게시물에도 표지 이미지가 생긴다 (안 받으면 표지가 아예 없다).
        #
        # 주소는 잘라 낸 그대로 쓴다. 뒤에 붙은 서명 값(oh=)이 한 글자라도
        # 달라지면 "URL signature mismatch" 로 거부당한다.
        children = [u.strip() for u in row["children_urls"].split(";") if u.strip()]
        if children and url_ext(children[0]) == ".mp4":
            tasks.append((media_url, os.path.join(IMAGES_DIR, f"{media_id}_cover.jpg")))

        seen_basenames = set()
        slide_idx = 0  # 0 이면 표지(cover), 1부터 child_1, child_2...
        for url in children:
            name = url_basename(url)
            if name in seen_basenames:  # 같은 파일이 두 번 나오면 건너뛴다
                continue
            seen_basenames.add(name)

            ext = url_ext(url)
            label = "cover" if slide_idx == 0 else f"child_{slide_idx}"
            # 슬라이드에 영상이 섞여 있으면 확장자로 갈라 videos/ 로 보낸다
            folder = VIDEOS_DIR if ext == ".mp4" else IMAGES_DIR
            tasks.append((url, os.path.join(folder, f"{media_id}_{label}{ext}")))
            slide_idx += 1

    elif media_type == "VIDEO":
        # media_url 이 영상 파일이므로, 표지 사진은 thumbnail_url 에서 따로 받는다.
        # 2026-07-28 이전에 수집한 CSV 에는 thumbnail_url 컬럼 자체가 없다.
        # 그래서 row["..."] 가 아니라 row.get(...) 으로 읽어야 KeyError 가 안 난다.
        thumbnail_url = (row.get("thumbnail_url") or "").strip()
        if thumbnail_url:
            tasks.append((thumbnail_url, os.path.join(IMAGES_DIR, f"{media_id}_cover.jpg")))
        tasks.append((media_url, os.path.join(VIDEOS_DIR, f"{media_id}.mp4")))

    else:
        print(f"  [경고] 알 수 없는 media_type '{media_type}' (media_id={media_id}) - 건너뜀")

    return tasks


def main() -> None:
    csv_path: str = sys.argv[1] if len(sys.argv) > 1 else default_csv()
    if not os.path.exists(csv_path):
        sys.exit(f"[에러] 입력 파일이 없습니다: {csv_path}")
    print(f"CSV: {os.path.relpath(csv_path, ROOT_DIR)}")

    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(VIDEOS_DIR, exist_ok=True)

    # utf-8-sig 로 읽어야 한다. 저장할 때 엑셀 호환을 위해 파일 맨 앞에 넣은
    # 표식(BOM)을 여기서 떼어 낸다. 그냥 utf-8 로 열면 첫 컬럼명이
    # "﻿ig_username" 처럼 되어 그 컬럼만 찾지 못한다.
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"[에러] {os.path.basename(csv_path)} 에 데이터 행이 없습니다.")
    check_columns(rows, csv_path)
    keys = "q + Enter 또는 Ctrl+C" if start_quit_watcher() else "Ctrl+C"
    print(f"게시물 {len(rows)}개 처리 시작")
    print(f"  중단하려면 {keys} — 받은 것은 저장되고 다시 실행하면 이어집니다\n")

    stats: dict[str, int] = {"ok": 0, "skip": 0, "fail": 0, "expired": 0, "no_url": 0}
    # 받아야 할 파일을 하나도 빠짐없이 확보한 행만 dataset.csv 로 나간다
    done_rows: list[dict[str, str]] = []

    interrupted = False
    done_count = 0  # 끝까지 처리한 행 수. 남은 개수를 세는 데 쓴다.

    try:
        for i, row in enumerate(rows, 1):
            if _stop_event.is_set():  # q 입력. 다음 행으로 넘어가기 전이 끊기 좋은 지점
                raise KeyboardInterrupt
            tasks = plan_row(row)
            # 알 수 없는 media_type 이면 목록이 비어 있다. 이런 행은 완료로 치지 않는다.
            row_ok = bool(tasks)
            for url, dest in tasks:
                result = download(url, dest)
                stats[result] += 1
                if result in ("fail", "expired", "no_url"):
                    row_ok = False
            if row_ok:
                done_rows.append(dataset_row(row, tasks))
            done_count = i
            if i % 20 == 0 or i == len(rows):
                print(f"  진행 {i}/{len(rows)} | 다운로드 {stats['ok']}  스킵 {stats['skip']}  "
                      f"만료 {stats['expired']}  주소없음 {stats['no_url']}  실패 {stats['fail']}")
    except KeyboardInterrupt:
        interrupted = True
        how = "q 입력" if _stop_event.is_set() else "Ctrl+C"
        print(f"\n[중단] {how} — {done_count}/{len(rows)}행까지 처리했습니다")

    print("\n================ " + ("중단됨" if interrupted else "완료") + " ================")
    print(f"다운로드: {stats['ok']}  |  이미 존재(스킵): {stats['skip']}")
    print(f"URL 만료: {stats['expired']}  |  주소 없음: {stats['no_url']}  |  실패: {stats['fail']}")
    print(f"완료 게시물: {len(done_rows)}/{len(rows)}")
    print(f"저장 위치: {os.path.relpath(OUTPUT_DIR, ROOT_DIR)}")

    if done_rows:
        save_dataset_csv(done_rows)

    # 못 끝낸 행 = 아직 시작도 못 한 행 + 시도했지만 파일이 빈 행.
    # 재시도 목록을 따로 두지 않는 이유는, 같은 명령을 다시 실행하면 이미 받은
    # 파일은 건너뛰고(skip) 못 받은 것만 시도하기 때문이다.
    remaining = (len(rows) - done_count) + (done_count - len(done_rows))
    if remaining:
        cmd = f"python3 {os.path.basename(__file__)}"
        if len(sys.argv) > 1:
            cmd += f" {sys.argv[1]}"
        print(f"\n{remaining}건이 남았습니다 — 같은 명령을 다시 실행하면 이어서 받습니다")
        print(f"  {cmd}")
        if stats["expired"]:
            print(
                "※ 만료(expired)는 주소 자체가 죽은 것이라 다시 실행해도 계속 실패합니다.\n"
                "   crawling.py 를 다시 돌려 새 주소를 받은 뒤 다운로드하세요."
            )
        if stats["no_url"]:
            print(
                "※ 주소 없음(no_url)은 저작권 음원이 포함된 영상이라 API 가 영상 주소를\n"
                "   주지 않는 경우입니다. 재실행해도, 다시 수집해도 받을 수 없습니다 —\n"
                "   표지만 받아지고 그 행은 dataset.csv 에 들어가지 않습니다."
            )


if __name__ == "__main__":
    main()
