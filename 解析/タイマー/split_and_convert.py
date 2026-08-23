#!/usr/bin/env python3
"""
切りタイマーと入りタイマーのログをボタンごとに分割し、
バイナリ文字列(0/1)に変換するスクリプト。
"""

import os
import re
from pathlib import Path


# 変換パラメータ (02_raw_to_bits_total.py と同じ)
LEADER_INTERVALS = 4
FOOTER_INTERVALS = 1
MARK_TARGET_US = 460
MARK_TOLERANCE_US = 100
ZERO_BIT_TOTAL_US = 842
ONE_BIT_TOTAL_US = 1682
BIT_THRESHOLD_US = (ZERO_BIT_TOTAL_US + ONE_BIT_TOTAL_US) / 2
BIT_TOTAL_TOLERANCE_US = 100
EXPECTED_BITS = 424


def parse_button_blocks(log_content):
    """ログをボタンごとのブロックに分割する。検出順に1から番号を振る。"""
    # "リモコンのボタンを1回だけ押してください" で分割
    raw_blocks = log_content.split("リモコンのボタンを1回だけ押してください")

    blocks = []
    number = 0
    for raw_block in raw_blocks:
        # 空ブロックをスキップ
        if not raw_block.strip() or "MARK/SPACE付き時間差:" not in raw_block:
            continue

        # MARK/SPACEリストを抽出
        match = re.search(r'\[.*?\]', raw_block, re.DOTALL)
        if not match:
            continue

        list_str = match.group(0)
        try:
            intervals = eval(list_str)
        except Exception as e:
            print(f"  [WARN] パース失敗のためスキップ: {e}")
            continue

        number += 1
        blocks.append({
            'number': number,
            'name': str(number),
            'data': intervals
        })

    return blocks


def convert_to_bits(intervals):
    """
    MARK/SPACEリストをバイナリ文字列に変換する。
    変換不可能な場合はValueErrorを送出する。
    戻り値: (bit_string, warning_count)
    """
    data_intervals = intervals[LEADER_INTERVALS:-FOOTER_INTERVALS]

    if len(data_intervals) % 2 != 0:
        raise ValueError(f"データ部が偶数ではありません: {len(data_intervals)}個")

    bits = []
    warning_count = 0

    for index in range(0, len(data_intervals), 2):
        mark_type, mark_us = data_intervals[index]
        space_type, space_us = data_intervals[index + 1]
        bit_number = index // 2

        if mark_type != "MARK" or space_type != "SPACE":
            raise ValueError(f"{bit_number}番目がMARK/SPACEの順ではありません")

        if abs(mark_us - MARK_TARGET_US) > MARK_TOLERANCE_US:
            print(f"    [WARN] {bit_number}番目のMARKが想定範囲外: {mark_us} us "
                  f"(範囲: {MARK_TARGET_US-MARK_TOLERANCE_US}-{MARK_TARGET_US+MARK_TOLERANCE_US})")
            warning_count += 1

        bit_total_us = mark_us + space_us
        distance_from_zero = abs(bit_total_us - ZERO_BIT_TOTAL_US)
        distance_from_one = abs(bit_total_us - ONE_BIT_TOTAL_US)

        if min(distance_from_zero, distance_from_one) > BIT_TOTAL_TOLERANCE_US:
            print(f"    [WARN] {bit_number}番目の合計時間が想定外: {bit_total_us} us "
                  f"(0基準:{ZERO_BIT_TOTAL_US}, 1基準:{ONE_BIT_TOTAL_US})")
            warning_count += 1

        if bit_total_us < BIT_THRESHOLD_US:
            bits.append("0")
        else:
            bits.append("1")

    bit_string = "".join(bits)

    if len(bit_string) != EXPECTED_BITS:
        print(f"    [WARN] 想定ビット数:{EXPECTED_BITS} / 実際:{len(bit_string)}")
        warning_count += 1

    return bit_string, warning_count


def save_bit_string(button_data, output_dir):
    """ボタンごとのバイナリ文字列をファイルに保存する。"""
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, f"{button_data['name']}_bits.txt")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"{button_data['name']}\n")
        f.write(f"エッジ数: {len(button_data['data'])}\n")
        f.write(f"データビット数: {len(button_data['bits'])}\n")
        f.write(f"バイナリ: {button_data['bits']}\n")

    return output_path


def process_timer(log_path, output_dir, label):
    """1種類のタイマーログを処理し、成功/失敗のリストを返す。"""
    print("=" * 60)
    print(label)
    print("=" * 60)

    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = parse_button_blocks(content)
    print(f"  検出したボタン数: {len(blocks)}")

    results = []
    errors = []

    for block in blocks:
        print(f"\n  番号: {block['name']}")
        print(f"    エッジ数: {len(block['data'])}")

        try:
            bits, warning_count = convert_to_bits(block['data'])
        except Exception as e:
            errors.append({'name': block['name'], 'reason': str(e)})
            print(f"    [SKIP] 変換失敗: {e}")
            continue

        block['bits'] = bits
        block['warning_count'] = warning_count
        print(f"    ビット数: {len(bits)}")
        print(f"    バイナリ: {bits}")

        output_path = save_bit_string(block, output_dir)
        print(f"    保存先: {output_path}")

        results.append(block)

    return results, errors


def main():
    script_dir = Path(__file__).parent
    timer_dir = script_dir.parent / "タイマー"

    # 切りタイマーを処理
    cut_results, cut_errors = process_timer(
        timer_dir / "切りタイマーログ.txt",
        timer_dir / "切りタイマー_バイナリ",
        "切りタイマー (Off Timer)"
    )

    # 入りタイマーを処理
    on_results, on_errors = process_timer(
        timer_dir / "入りタイマーログ.txt",
        timer_dir / "入りタイマー_バイナリ",
        "入りタイマー (On Timer)"
    )

    # まとめ
    print("\n" + "=" * 60)
    print("処理完了")
    print("=" * 60)
    print(f"切りタイマー: {len(cut_results)}件成功, {len(cut_errors)}件失敗")
    if cut_errors:
        for err in cut_errors:
            print(f"  [FAIL] 番号{err['name']}: {err['reason']}")
    cut_warned = [b for b in cut_results if b['warning_count'] > 0]
    if cut_warned:
        print(f"  警告ありの番号:")
        for b in cut_warned:
            print(f"  [WARN] 番号{b['name']}: 警告{b['warning_count']}件")
    print(f"  出力先: {timer_dir / '切りタイマー_バイナリ'}")

    print(f"\n入りタイマー: {len(on_results)}件成功, {len(on_errors)}件失敗")
    if on_errors:
        for err in on_errors:
            print(f"  [FAIL] 番号{err['name']}: {err['reason']}")
    on_warned = [b for b in on_results if b['warning_count'] > 0]
    if on_warned:
        print(f"  警告ありの番号:")
        for b in on_warned:
            print(f"  [WARN] 番号{b['name']}: 警告{b['warning_count']}件")
    print(f"  出力先: {timer_dir / '入りタイマー_バイナリ'}")


if __name__ == "__main__":
    main()