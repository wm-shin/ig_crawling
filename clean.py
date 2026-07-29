"""
수집한 것을 지우고 처음 상태로 되돌립니다. 다른 계정 목록으로 새로 시작할 때 씁니다.

data/ 와 output/ 은 스크립트를 다시 돌리면 만들어지므로 그냥 지웁니다.
되돌릴 수 없는 것은 직접 작성한 input/accounts.csv 뿐이라 그것만 물어봅니다.

폴더 안만 비우고 폴더 자체는 남깁니다 — input/ 이 사라지면 새 계정 목록을 넣을
자리가 없어지기 때문입니다. .env 와 파이썬 파일은 건드리지 않습니다.

사용법:
    python3 clean.py       # data/ output/ 을 지우고, input/ 은 물어본 뒤 결정
    python3 clean.py --y   # 묻지 않고 input/ 까지 전부
"""

import os
import shutil
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def clear(dirname: str) -> None:
    """폴더 안의 파일과 하위 폴더를 모두 지웁니다. 폴더 자체는 남깁니다."""
    path = os.path.join(ROOT_DIR, dirname)
    if not os.path.isdir(path):
        return

    for entry in os.listdir(path):
        # accounts.example.csv 처럼 형식을 보여주는 파일은 저장소에 포함된
        # 내용물이지 내가 모은 데이터가 아니므로 남긴다.
        if ".example." in entry:
            continue
        target = os.path.join(path, entry)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        else:
            os.remove(target)
    print(f"  {dirname}/ 비움")


def main() -> None:
    # 지우기 전에 먼저 물어본다. 그만두려면 여기서 Ctrl+C.
    with_input = "--y" in sys.argv[1:]
    if not with_input:
        try:
            answer = input("input/accounts.csv 도 지울까요? (아니오면 계정 목록만 남깁니다) [y/N]: ")
        except EOFError:
            # 파이프·크론처럼 물어볼 상대가 없는 환경. 아무것도 지우지 않고 끝낸다.
            sys.exit("입력을 받을 수 없습니다 — 터미널에서 실행하거나 --y 를 붙이세요.")
        # y 를 정확히 입력했을 때만 지운다. 엔터를 포함해 나머지는 전부 "아니오".
        with_input = answer.strip().lower() in ("y", "yes")

    clear("data")
    clear("output")
    if with_input:
        clear("input")

    print("\n완료 — 폴더는 그대로 남아 있습니다.")
    if with_input:
        print("input/accounts.csv 에 새 계정 목록을 넣고 crawling.py 를 실행하세요.")


if __name__ == "__main__":
    main()
