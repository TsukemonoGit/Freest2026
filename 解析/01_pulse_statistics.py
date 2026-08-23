import ast
import statistics


LEADER_INTERVALS = 4
FOOTER_INTERVALS = 1
SPACE_THRESHOLD_US = 800


def print_statistics(name, values):
    if not values:
        print(f"{name}: データなし")
        return

    average = statistics.mean(values)
    median = statistics.median(values)
    minimum = min(values)
    maximum = max(values)
    standard_deviation = statistics.pstdev(values)

    print(f"{name}")
    print(f"  個数      : {len(values)}")
    print(f"  平均値    : {average:.1f} µs")
    print(f"  中央値    : {median:.1f} µs")
    print(f"  最小値    : {minimum} µs")
    print(f"  最大値    : {maximum} µs")
    print(f"  標準偏差  : {standard_deviation:.1f} µs")


print("MARK/SPACE付き時間差のリストを貼り付けてください")
text = input()
intervals = ast.literal_eval(text)

if len(intervals) <= LEADER_INTERVALS + FOOTER_INTERVALS:
    raise ValueError("データ部がありません")

# 先頭のヘッダー4区間と、末尾のフッター1区間を除く
data_intervals = intervals[LEADER_INTERVALS:-FOOTER_INTERVALS]

if len(data_intervals) % 2 != 0:
    raise ValueError("データ部をMARK/SPACEのペアに分割できません")

marks = []
zero_spaces = []
one_spaces = []

for index in range(0, len(data_intervals), 2):
    mark_type, mark_us = data_intervals[index]
    space_type, space_us = data_intervals[index + 1]

    if mark_type != "MARK" or space_type != "SPACE":
        raise ValueError(
            f"{index // 2}番目のデータがMARK/SPACEの順ではありません"
        )

    marks.append(mark_us)

    if space_us < SPACE_THRESHOLD_US:
        zero_spaces.append(space_us)
    else:
        one_spaces.append(space_us)

print()
print(f"SPACE判定境界: {SPACE_THRESHOLD_US} µs")
print()
print_statistics("MARK", marks)
print()
print_statistics("0のSPACE", zero_spaces)
print()
print_statistics("1のSPACE", one_spaces)