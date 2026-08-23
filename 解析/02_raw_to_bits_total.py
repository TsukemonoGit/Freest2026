import ast


LEADER_INTERVALS = 4
FOOTER_INTERVALS = 1
EXPECTED_BITS = 424

MARK_TARGET_US = 460
MARK_TOLERANCE_US = 100

ZERO_BIT_TOTAL_US = 842
ONE_BIT_TOTAL_US = 1682
BIT_THRESHOLD_US = (ZERO_BIT_TOTAL_US + ONE_BIT_TOTAL_US) / 2
BIT_TOTAL_TOLERANCE_US = 100


print("MARK/SPACE付き時間差のリストを貼り付けてください")
text = input()
intervals = ast.literal_eval(text)

if len(intervals) <= LEADER_INTERVALS + FOOTER_INTERVALS:
    raise ValueError("データ部がありません")

# 先頭のヘッダー4区間と、末尾のフッター1区間を除く
data_intervals = intervals[LEADER_INTERVALS:-FOOTER_INTERVALS]

if len(data_intervals) % 2 != 0:
    raise ValueError("データ部をMARK/SPACEのペアに分割できません")

bits = []

for index in range(0, len(data_intervals), 2):
    mark_type, mark_us = data_intervals[index]
    space_type, space_us = data_intervals[index + 1]
    bit_number = index // 2

    if mark_type != "MARK" or space_type != "SPACE":
        raise ValueError(
            f"{bit_number}番目がMARK/SPACEの順ではありません"
        )

    if abs(mark_us - MARK_TARGET_US) > MARK_TOLERANCE_US:
        raise ValueError(
            f"{bit_number}番目のMARKが想定範囲外です: {mark_us} µs"
        )

    bit_total_us = mark_us + space_us
    distance_from_zero = abs(bit_total_us - ZERO_BIT_TOTAL_US)
    distance_from_one = abs(bit_total_us - ONE_BIT_TOTAL_US)

    if min(distance_from_zero, distance_from_one) > BIT_TOTAL_TOLERANCE_US:
        raise ValueError(
            f"{bit_number}番目の合計時間が想定範囲外です: "
            f"{bit_total_us} µs"
        )

    if bit_total_us < BIT_THRESHOLD_US:
        bits.append("0")
    else:
        bits.append("1")

bit_string = "".join(bits)

print(f"0の基準時間: {ZERO_BIT_TOTAL_US} µs")
print(f"1の基準時間: {ONE_BIT_TOTAL_US} µs")
print(f"0/1判定境界: {BIT_THRESHOLD_US:.1f} µs")
print(f"データビット数: {len(bit_string)}")

if len(bit_string) != EXPECTED_BITS:
    print(
        f"警告: 想定は{EXPECTED_BITS}ビットですが、"
        f"{len(bit_string)}ビットでした"
    )

print(bit_string)