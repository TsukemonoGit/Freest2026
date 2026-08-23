from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_EXPECTED_BITS = 424
BITS_PER_GROUP = 8


@dataclass(frozen=True)
class Capture:
    order: int
    path: Path
    label: str
    bits: str
    groups: tuple[str, ...]


def collect_input_files(inputs: Iterable[str]) -> list[Path]:
    files: list[Path] = []

    for raw_input in inputs:
        path = Path(raw_input).expanduser()

        if not path.exists():
            raise FileNotFoundError(f"入力が見つかりません: {path}")

        if path.is_dir():
            directory_files = sorted(path.glob("*.txt"))
            if not directory_files:
                raise FileNotFoundError(f"TXTファイルがありません: {path}")
            files.extend(directory_files)
        elif path.is_file():
            files.append(path)
        else:
            raise ValueError(f"通常のファイルまたはディレクトリではありません: {path}")

    unique_files: list[Path] = []
    seen: set[Path] = set()

    for path in files:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(path)

    if len(unique_files) < 2:
        raise ValueError("比較には2個以上の入力ファイルが必要です。")

    return unique_files


def extract_bits(text: str, source: Path) -> str:
    candidates: list[str] = []

    whole_text_without_spaces = re.sub(r"\s+", "", text)
    if (
        len(whole_text_without_spaces) >= BITS_PER_GROUP
        and set(whole_text_without_spaces) <= {"0", "1"}
    ):
        candidates.append(whole_text_without_spaces)

    for line in text.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            continue

        line_without_spaces = re.sub(r"\s+", "", stripped_line)
        if (
            len(line_without_spaces) >= BITS_PER_GROUP
            and set(line_without_spaces) <= {"0", "1"}
        ):
            candidates.append(line_without_spaces)

        if ":" in stripped_line or "：" in stripped_line:
            tail = re.split(r"[:：]", stripped_line, maxsplit=1)[1]
            tail_without_spaces = re.sub(r"\s+", "", tail)
            if (
                len(tail_without_spaces) >= BITS_PER_GROUP
                and set(tail_without_spaces) <= {"0", "1"}
            ):
                candidates.append(tail_without_spaces)

        candidates.extend(re.findall(r"[01]{8,}", stripped_line))

    if not candidates:
        raise ValueError(f"0/1ビット列を読み取れませんでした: {source}")

    return max(candidates, key=len)


def split_into_groups(bits: str) -> tuple[str, ...]:
    return tuple(
        bits[index : index + BITS_PER_GROUP]
        for index in range(0, len(bits), BITS_PER_GROUP)
    )


def load_captures(
    paths: list[Path],
    expected_bits: int,
) -> list[Capture]:
    captures: list[Capture] = []

    for order, path in enumerate(paths, start=1):
        try:
            text = path.read_text(encoding="utf-8-sig")
            bits = extract_bits(text, path)
        except (ValueError, UnicodeError):
            print(f"[SKIP] 読み込み失敗: {path.name}")
            order -= 1
            continue

        if expected_bits > 0 and len(bits) != expected_bits:
            print(f"[SKIP] ビット数不一致: {path.name} ({len(bits)}ビット、想定{expected_bits}ビット)")
            order -= 1
            continue

        if len(bits) % BITS_PER_GROUP != 0:
            print(f"[SKIP] 8の倍数ではない: {path.name} ({len(bits)}ビット)")
            order -= 1
            continue

        captures.append(
            Capture(
                order=order,
                path=path,
                label=path.stem,
                bits=bits,
                groups=split_into_groups(bits),
            )
        )

    bit_lengths = {len(capture.bits) for capture in captures}
    if len(bit_lengths) != 1:
        details = ", ".join(
            f"{capture.path.name}={len(capture.bits)}"
            for capture in captures
        )
        raise ValueError(f"ファイル間でビット数が一致しません: {details}")

    return captures


def msb_value(group: str) -> int:
    return int(group, 2)


def lsb_value(group: str) -> int:
    return int(group[::-1], 2)


def changed_group_indexes(captures: list[Capture]) -> list[int]:
    group_count = len(captures[0].groups)
    return [
        index
        for index in range(group_count)
        if len({capture.groups[index] for capture in captures}) > 1
    ]


def changed_bit_indexes(first: Capture, second: Capture) -> list[int]:
    return [
        index
        for index, (left, right) in enumerate(zip(first.bits, second.bits))
        if left != right
    ]


def format_group_positions(indexes: Iterable[int]) -> str:
    values = [str(index + 1) for index in indexes]
    return ", ".join(values) if values else "なし"


def print_input_summary(captures: list[Capture]) -> None:
    print("【入力データ】")
    print("順番\tラベル\tファイル")

    for capture in captures:
        print(
            f"{capture.order}\t{capture.label}\t{capture.path.name}"
        )


def print_adjacent_differences(captures: list[Capture]) -> None:
    print("\n【隣り合う測定結果の差】")

    for previous, current in zip(captures, captures[1:]):
        bit_indexes = changed_bit_indexes(previous, current)
        group_indexes = sorted({index // BITS_PER_GROUP for index in bit_indexes})

        print(f"\n{previous.label}  →  {current.label}")
        print(f"変化したビット数: {len(bit_indexes)}")
        print(f"変化した8ビット組: {format_group_positions(group_indexes)}")

        if not bit_indexes:
            print("変化したビット位置: なし")
            continue

        print("8ビット組\t組内位置\t全体位置\t変化")
        for bit_index in bit_indexes:
            group_index = bit_index // BITS_PER_GROUP
            position_in_group = bit_index % BITS_PER_GROUP
            print(
                f"{group_index + 1}\t{position_in_group + 1}\t{bit_index + 1}\t"
                f"{previous.bits[bit_index]}→{current.bits[bit_index]}"
            )


def print_changed_group_values(
    captures: list[Capture], changed_indexes: list[int]
) -> None:
    print("\n【全測定で変化した8ビット組】")
    print(f"位置: {format_group_positions(changed_indexes)}")

    for group_index in changed_indexes:
        print(f"\n--- 8ビット組 {group_index + 1} ---")
        print(
            "順番\tラベル\t受信順8ビット\t"
            "MSB十進\tMSB十六進\tLSB十進\tLSB十六進\tファイル"
        )

        for capture in captures:
            group = capture.groups[group_index]
            msb = msb_value(group)
            lsb = lsb_value(group)
            print(
                f"{capture.order}\t{capture.label}\t{group}\t"
                f"{msb}\t0x{msb:02X}\t{lsb}\t0x{lsb:02X}\t"
                f"{capture.path.name}"
            )


def write_csv(
    output_path: Path,
    captures: list[Capture],
    changed_indexes: list[int],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "測定順",
                "ラベル",
                "入力ファイル",
                "8ビット組位置",
                "受信順8ビット",
                "MSB十進数",
                "MSB十六進数",
                "LSB十進数",
                "LSB十六進数",
            ]
        )

        for capture in captures:
            for group_index in changed_indexes:
                group = capture.groups[group_index]
                msb = msb_value(group)
                lsb = lsb_value(group)
                writer.writerow(
                    [
                        capture.order,
                        capture.label,
                        str(capture.path),
                        group_index + 1,
                        group,
                        msb,
                        f"0x{msb:02X}",
                        lsb,
                        f"0x{lsb:02X}",
                    ]
                )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "0/1変換済みの赤外線信号を比較し、"
            "操作変更で変化した8ビット位置を調べます。"
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help=(
            "比較するTXTファイル、またはTXTファイルを入れたディレクトリ。"
            "複数ファイルを指定した場合は指定順で比較します。"
        ),
    )
    parser.add_argument(
        "--expected-bits",
        type=int,
        default=DEFAULT_EXPECTED_BITS,
        help=(
            "想定するビット数。既定値は424。"
            "ビット数の確認を無効にする場合は0。"
        ),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="変化した8ビット組の一覧をCSVにも保存します。",
    )
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        paths = collect_input_files(args.inputs)
        captures = load_captures(
            paths=paths,
            expected_bits=args.expected_bits,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1

    changed_indexes = changed_group_indexes(captures)

    print_input_summary(captures)
    print_adjacent_differences(captures)
    print_changed_group_values(captures, changed_indexes)

    if args.csv is not None:
        try:
            write_csv(args.csv, captures, changed_indexes)
        except OSError as error:
            print(f"CSV保存エラー: {error}", file=sys.stderr)
            return 1
        print(f"\nCSV保存先: {args.csv.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
