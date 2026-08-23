#!/usr/bin/env python3
"""縦長のバイト解析CSVを、測定ごとの横長比較表へ変換する。

例:
    python byte_csv_wide.py input.csv --positions 18-21 \
        --value lsb-hex --sort natural-label --pair-check \
        --output comparison_18_21.csv --markdown comparison_18_21.md

    python byte_csv_wide.py input.csv --positions 22 23 24 25 \
        --output comparison_22_25.csv

外部ライブラリは不要。Python 3.10以降で動作する。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


VALUE_COLUMNS = {
    "bits": ("受信順8ビット", "ビット列"),
    "msb-dec": ("MSB十進数", "MSB十進"),
    "msb-hex": ("MSB十六進数", "MSB十六進"),
    "lsb-dec": ("LSB十進数", "LSB十進"),
    "lsb-hex": ("LSB十六進数", "LSB十六進"),
}


def clean_text(value: object) -> str:
    """Markdown装飾や、貼り付け時のエスケープを除去する。"""
    text = "" if value is None else str(value)
    text = text.strip().replace("**", "")
    text = text.replace(r"\_", "_")
    return text.strip()


def normalized_header(value: object) -> str:
    return re.sub(r"\s+", "", clean_text(value)).lstrip("\ufeff")


def natural_key(value: str) -> list[tuple[int, object]]:
    """1_bits, 2_bits, 10_bitsを数値順に並べるためのキー。"""
    parts = re.split(r"(\d+)", value.casefold())
    return [
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts
        if part != ""
    ]


def parse_positions(tokens: Iterable[str]) -> list[int]:
    """18 19 20 21、18-21、18,19,20,21のいずれも受け付ける。"""
    positions: list[int] = []

    for token in tokens:
        for part in token.replace("～", "-").split(","):
            part = part.strip()
            if not part:
                continue

            range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
            if range_match:
                start, end = map(int, range_match.groups())
                if start > end:
                    raise ValueError(f"位置の範囲が逆です: {part}")
                positions.extend(range(start, end + 1))
            elif part.isdigit():
                positions.append(int(part))
            else:
                raise ValueError(f"位置を解釈できません: {part}")

    positions = list(dict.fromkeys(positions))
    if not positions:
        raise ValueError("対象位置が指定されていません。")
    if any(position < 1 for position in positions):
        raise ValueError("バイト位置は1以上で指定してください。")
    return positions


def parse_byte(value: str, bits: str) -> int | None:
    """補数確認用に、行から8ビット値を得る。"""
    clean_bits = re.sub(r"\s+", "", clean_text(bits))
    if re.fullmatch(r"[01]{8}", clean_bits):
        return int(clean_bits, 2)

    clean_value = clean_text(value).lower().removeprefix("0x")
    if re.fullmatch(r"[0-9a-f]{1,2}", clean_value):
        return int(clean_value, 16)
    return None


def format_value(value: str, value_mode: str, hex_prefix: bool) -> str:
    value = clean_text(value)
    if value_mode.endswith("hex"):
        value = value.upper().removeprefix("0X")
        if re.fullmatch(r"[0-9A-F]{1,2}", value):
            value = value.zfill(2)
        if hex_prefix and value not in {"", "—"}:
            value = f"0x{value}"
    return value


def resolve_columns(fieldnames: list[str] | None, value_mode: str) -> dict[str, str]:
    if not fieldnames:
        raise ValueError("CSVに見出し行がありません。")

    original_by_normalized = {
        normalized_header(fieldname): fieldname for fieldname in fieldnames
    }

    aliases = {
        "order": ("測定順", "順番", "order"),
        "label": ("ラベル", "label"),
        "file": ("入力ファイル", "ファイル", "file"),
        "position": ("8ビット組位置", "バイト位置", "位置", "position"),
        "bits": ("受信順8ビット", "8ビット", "bits"),
        "value": (VALUE_COLUMNS[value_mode][0],),
    }

    result: dict[str, str] = {}
    for logical_name, candidates in aliases.items():
        for candidate in candidates:
            found = original_by_normalized.get(normalized_header(candidate))
            if found is not None:
                result[logical_name] = found
                break

        if logical_name in {"file", "bits"}:
            continue
        if logical_name not in result:
            expected = " / ".join(candidates)
            raise ValueError(f"必要な列がありません: {expected}")

    return result


@dataclass
class Measurement:
    order_text: str
    order_number: int | None
    label: str
    input_file: str
    first_seen: int
    values: dict[int, str] = field(default_factory=dict)
    byte_values: dict[int, int] = field(default_factory=dict)


def read_measurements(
    input_path: Path,
    positions: list[int],
    value_mode: str,
    hex_prefix: bool,
) -> list[Measurement]:
    selected = set(positions)
    measurements: "OrderedDict[tuple[str, str, str], Measurement]" = OrderedDict()

    with input_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = resolve_columns(reader.fieldnames, value_mode)

        for row_number, row in enumerate(reader, start=2):
            # 空行や、Markdownの区切り線が混ざっても読み飛ばす。
            if not any(clean_text(value) for value in row.values()):
                continue

            position_text = clean_text(row.get(columns["position"], ""))
            if not position_text.isdigit():
                print(
                    f"[SKIP] {row_number}行目: バイト位置が数値ではありません",
                    file=sys.stderr,
                )
                continue

            position = int(position_text)
            if position not in selected:
                continue

            order_text = clean_text(row.get(columns["order"], ""))
            label = clean_text(row.get(columns["label"], ""))
            input_file = clean_text(row.get(columns.get("file", ""), ""))
            key = (order_text, label, input_file)

            if key not in measurements:
                try:
                    order_number = int(order_text)
                except ValueError:
                    order_number = None
                measurements[key] = Measurement(
                    order_text=order_text,
                    order_number=order_number,
                    label=label,
                    input_file=input_file,
                    first_seen=len(measurements),
                )

            measurement = measurements[key]
            if position in measurement.values:
                raise ValueError(
                    f"{row_number}行目: {label} の{position}バイト目が重複しています。"
                )

            raw_value = clean_text(row.get(columns["value"], ""))
            measurement.values[position] = format_value(
                raw_value, value_mode, hex_prefix
            )
            measurement.byte_values[position] = parse_byte(
                raw_value,
                clean_text(row.get(columns.get("bits", ""), "")),
            )

    if not measurements:
        raise ValueError(
            "指定したバイト位置のデータがありません。"
            "入力CSVと --positions を確認してください。"
        )
    return list(measurements.values())


def sort_measurements(
    measurements: list[Measurement], sort_mode: str
) -> list[Measurement]:
    if sort_mode == "input":
        return sorted(measurements, key=lambda item: item.first_seen)
    if sort_mode == "measurement":
        return sorted(
            measurements,
            key=lambda item: (
                item.order_number is None,
                item.order_number if item.order_number is not None else 0,
                item.first_seen,
            ),
        )
    if sort_mode == "natural-label":
        return sorted(
            measurements,
            key=lambda item: (natural_key(item.label), item.first_seen),
        )
    raise ValueError(f"未対応の並び順です: {sort_mode}")


def adjacent_pairs(positions: list[int]) -> list[tuple[int, int]]:
    """指定順の (1個目,2個目), (3個目,4個目)... をペアにする。"""
    return [
        (positions[index], positions[index + 1])
        for index in range(0, len(positions) - 1, 2)
    ]


def complement_result(measurement: Measurement, left: int, right: int) -> str:
    left_value = measurement.byte_values.get(left)
    right_value = measurement.byte_values.get(right)
    if left_value is None or right_value is None:
        return "—"
    return "一致" if (left_value ^ right_value) == 0xFF else "不一致"


def build_table(
    measurements: list[Measurement],
    positions: list[int],
    pair_check: bool,
    include_file: bool,
) -> tuple[list[str], list[list[str]]]:
    headers = ["測定順", "ラベル"]
    if include_file:
        headers.append("入力ファイル")
    headers.extend(f"{position}バイト目" for position in positions)

    pairs = adjacent_pairs(positions) if pair_check else []
    headers.extend(f"{left}/{right}補数" for left, right in pairs)

    rows: list[list[str]] = []
    for measurement in measurements:
        row = [measurement.order_text, measurement.label]
        if include_file:
            row.append(measurement.input_file)
        row.extend(measurement.values.get(position, "—") for position in positions)
        row.extend(
            complement_result(measurement, left, right)
            for left, right in pairs
        )
        rows.append(row)
    return headers, rows


def write_csv(output_path: Path, headers: list[str], rows: list[list[str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(headers)
        writer.writerows(rows)


def markdown_escape(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", "<br>")


def write_markdown(
    output_path: Path,
    headers: list[str],
    rows: list[list[str]],
    positions: list[int],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    title = "・".join(map(str, positions)) + "バイト目の比較"
    lines = [
        f"# {title}",
        "",
        "| " + " | ".join(map(markdown_escape, headers)) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(markdown_escape(value) for value in row) + " |"
        for row in rows
    )
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def print_preview(headers: list[str], rows: list[list[str]], limit: int = 8) -> None:
    preview_rows = rows[:limit]
    widths = [len(header) for header in headers]
    for row in preview_rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def line(values: list[str]) -> str:
        return "  ".join(
            value.ljust(widths[index]) for index, value in enumerate(values)
        )

    print(line(headers))
    print(line(["-" * width for width in widths]))
    for row in preview_rows:
        print(line(row))
    if len(rows) > limit:
        print(f"... 残り{len(rows) - limit}行")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "縦長のバイト解析CSVを、1測定1行の横長比較表に変換します。"
        )
    )
    parser.add_argument("input", type=Path, help="入力CSV")
    parser.add_argument(
        "--positions",
        nargs="+",
        required=True,
        metavar="位置",
        help="対象位置。例: 18-21 または 18 19 20 21",
    )
    parser.add_argument(
        "--value",
        choices=VALUE_COLUMNS,
        default="lsb-hex",
        help="表示する値（既定: lsb-hex）",
    )
    parser.add_argument(
        "--sort",
        choices=("input", "measurement", "natural-label"),
        default="input",
        help=(
            "並び順。input=CSV順、measurement=測定順、"
            "natural-label=ラベルの自然順（既定: input）"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("byte_comparison.csv"),
        help="出力CSV（既定: byte_comparison.csv）",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        help="同じ表をMarkdown形式でも保存",
    )
    parser.add_argument(
        "--pair-check",
        action="store_true",
        help="指定位置を2個ずつ組にして、ビット反転関係を確認",
    )
    parser.add_argument(
        "--include-file",
        action="store_true",
        help="出力に入力ファイル列も残す",
    )
    parser.add_argument(
        "--hex-prefix",
        action="store_true",
        help="16進数に0xを付ける（指定しなければ付けない）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="指定位置が欠けた測定があればエラーにする",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        positions = parse_positions(args.positions)
        measurements = read_measurements(
            input_path=args.input,
            positions=positions,
            value_mode=args.value,
            hex_prefix=args.hex_prefix,
        )
        measurements = sort_measurements(measurements, args.sort)

        missing = [
            (measurement.label, position)
            for measurement in measurements
            for position in positions
            if position not in measurement.values
        ]
        if missing:
            sample = ", ".join(
                f"{label}:{position}" for label, position in missing[:8]
            )
            message = f"指定位置が欠けています: {sample}"
            if len(missing) > 8:
                message += f" ほか{len(missing) - 8}件"
            if args.strict:
                raise ValueError(message)
            print(f"[WARN] {message}", file=sys.stderr)

        headers, rows = build_table(
            measurements=measurements,
            positions=positions,
            pair_check=args.pair_check,
            include_file=args.include_file,
        )
        write_csv(args.output, headers, rows)
        if args.markdown is not None:
            write_markdown(args.markdown, headers, rows, positions)

        print_preview(headers, rows)
        print(f"\nCSV保存先: {args.output.resolve()}")
        if args.markdown is not None:
            print(f"Markdown保存先: {args.markdown.resolve()}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())