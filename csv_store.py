"""CSV 를 저장하는 공용 함수 모음. crawling.py 와 download_media.py 가 함께 씁니다.

각 스크립트가 저장 코드를 따로 갖고 있으면 한쪽만 고쳤을 때 조용히 어긋납니다.
실제로 나눠 실행할 때 결과 파일이 덮어써져 앞선 실행분이 통째로 사라진 적이
있어서, 저장 방식을 여기 한 곳에 모아 두었습니다.

방식은 두 가지이고, 부르는 쪽에서 파일 성격에 맞게 고릅니다.

    save_csv    덮어쓰기 — "이번 실행의 결과"만 남으면 되는 파일.
                crawling.py 의 실패한 계정 목록이 그렇습니다.
                재시도해서 성공하면 목록에서 빠져야 하니까요.

    append_csv  쌓기    — 계속 모여야 하는 파일.
                수집 결과(posts.csv)와 데이터셋(dataset.csv)이 그렇습니다.
                계정을 나눠 여러 번 돌려도 한 파일에 모입니다.

모든 파일은 utf-8-sig 로 저장합니다. 파일 맨 앞에 3바이트짜리 표식(BOM)을 넣는
방식인데, 이게 있어야 엑셀이 한글을 안 깨뜨립니다. 대신 읽을 때도 utf-8-sig 로
열어야 그 표식이 첫 컬럼 이름에 붙어 버리지 않습니다.
"""

import csv
import os


def save_csv(rows: list, path: str) -> None:
    """행들을 CSV 로 덮어써 저장합니다. 원래 있던 내용은 사라집니다.

    계속 쌓여야 하는 파일에는 append_csv 를 쓰세요.
    """
    if not rows:
        print("저장할 데이터가 없습니다.")
        return

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"저장 완료: {path} ({len(rows)}행)")


def clear_csv(path: str, label: str = "목록") -> None:
    """남길 항목이 하나도 없을 때 기존 파일을 지웁니다. save_csv 와 짝입니다.

    save_csv 는 빈 목록을 받으면 아무것도 하지 않습니다. 그래서 이 함수가 없으면,
    재시도해서 전부 성공한 뒤에도 예전 실패 목록이 그대로 남아 이미 성공한 항목을
    다시 처리하게 됩니다.

    "파일 없음 = 실패 없음" 으로 규칙을 정했습니다. 헤더만 있는 빈 CSV 를 남기면
    "실패가 0건"인지 "아직 안 돌렸는지" 구분되지 않고, 부르는 쪽에서 빈 파일을
    또 걸러내야 합니다. 파일 존재 여부 하나로 판단하는 편이 단순합니다.
    """
    if os.path.exists(path):
        os.remove(path)
        print(f"이전 {label}을 삭제했습니다: {path}")


def append_csv(rows: list, path: str, key: str = "media_id") -> None:
    """행들을 기존 CSV 에 쌓습니다. key 값이 같은 기존 행은 새 행으로 바뀝니다.

    나눠서 여러 번 돌려도 결과가 한 파일에 모입니다. 같은 항목을 다시 수집하면
    새 행이 이기므로, 만료된 주소가 새 주소로 갱신됩니다.
    (단순히 뒤에 이어 붙이면 돌릴 때마다 같은 항목이 중복으로 쌓입니다.)
    """
    if not rows:
        print("저장할 데이터가 없습니다.")
        return

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    merged = {}
    existing_fields = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            existing_fields = reader.fieldnames or []
            for old in reader:
                merged[str(old.get(key))] = old

    before = len(merged)
    for row in rows:
        merged[str(row.get(key))] = row
    added = len(merged) - before

    # 컬럼이 늘어났을 때(새 항목을 추가하고 다시 돌린 경우 등) 기존 행의 값을
    # 잃지 않도록, 새 컬럼과 기존 컬럼을 모두 합쳐 헤더로 쓴다.
    fieldnames = list(rows[0].keys())
    fieldnames += [name for name in existing_fields if name not in fieldnames]

    # 임시 파일에 다 쓴 뒤에 진짜 파일과 바꿔치기한다.
    # 이 함수는 기존 파일을 읽어서 통째로 다시 쓰는 구조라, 쓰는 도중에 끊기면
    # 이 보호가 없을 경우 그동안 모은 것을 전부 잃는다.
    tmp = path + ".part"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(merged.values())
    os.replace(tmp, path)

    print(f"저장 완료: {path} (신규 {added}행 / 갱신 {len(rows) - added}행 / 총 {len(merged)}행)")
