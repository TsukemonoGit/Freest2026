# 21ページ目案（draft2）：どんなコードが必要？

## やりたいこと（もう一度）

「スマホからエアコンを操作したい」

これを実現するためにPicoに書くコードは大きく分けて**3つの柱**がある：

1. **受信** — リモコンの信号を受け取って「何のボタンか」分かる
2. **送信** — 分かったボタンの信号をエアコンに送出する
3. **連携** — スマホから操作する

さらに、**1の「分かる」を作る過程**に分析用コードがある。

---

## 逆算フロー：最終状態から最初のステップへ

```
最終状態
  スマホの画面で「電源ON」ボタンをタップ
    → Wi-FiでPicoに届く
      → Picoが赤外線LEDを点滅
        → エアコンが電源ON

  そのために必要なのは？
    ↓
  Picoが「電源ONボタンの赤外線信号」を出せる
  （ir_send.py：ボタンコードから38kHzの搬送波を生成してLEDを点滅させる）
    そのために必要なのは？
      ↓
  「電源ON」→「この赤外線の並び」が分かる
  （buttons.py：ボタンコード↔ボタン名の辞書）
    そのために必要なのは？
      ↓
  リモコンの信号を受信して、ボタンの型を登録する
  （protocol.py：timingデータから32ビットコードを復号する）
    そのために必要なのは？
      ↓
  赤外線受信モジュールの出力を記録できる
  （capture.py：GPIOの変化をマイクロ秒で記録する）
    そのために必要なのは？
      ↓
  GPIOの入力変化をマイクロ秒で測れる
```

**下から順に作る。** なぜ？
- 下の段階が動いていないと、上の段階のテストができない
- 途中の段階で「ちゃんと動いているか」を確認しながら進められる
- コード初心者は「動いてるか見えない」ことが一番つまづく原因

---

## 必要なコードの一覧（理想形）

| ファイル | 役割 | 具体的に何をするか |
|---------|------|-------------------|
| `capture.py` | ハードウェア層：信号を記録 | GPIOの変化を検出し、各区間の長さを配列に保存 |
| `protocol.py` | プロトコル層：信号を解釈 | 配列を「ヘッダ・ビット列・繰返し」に分割し、ボタンコードを抽出 |
| `buttons.py` | データ層：ボタン辞書 | ボタンコード↔ボタン名の対応を登録 |
| `ir_send.py` | 送信層：信号を出す | ボタンコードから赤外線信号を再現してLEDを点滅 |
| `main.py` | アプリ層：全部を束ねる | 受信→判定→送信→Wi-Fi連携の流れ |
| `analyze.py` | 分析ツール（PC側） | 測定データから時間帯とボタン辞書を自動生成 |

**大事な原則：**
- 1ファイル = 1つの役割
- 下の層は上の層を知らない（capture.pyは「ボタン」の概念を知らない）
- 各ファイルは単体でテストできる

---

## 実装環境：まずここを揃える

### 言語：MicroPython

Pico 2 WH で赤外線の送受信をするために、以下の3つを比較した：

| | MicroPython | Arduino／C++ | Pico SDK（C／C++） |
|---|---|---|---|
| 始めやすさ | REPLからすぐ試せる | 導入は比較的簡単 | ビルド環境が必要 |
| 時間測定 | IRQ＋ticks_usでµs測定 | 割込みで安定して測定 | PIO・DMAまで細かく制御 |
| 解析の見え方 | 時間列を自分で処理できる | ライブラリ利用では中身が隠れやすい | 最も正確だがコード量が増える |

**選んだ理由：** 最初に「信号が届いているか」をすぐ確認したい。
REPL（対話式シェル）からコードを打てばその場で動くのが、
初心者が「動いてるか見えない」問題を減らす。

### IDE：VS Code + Raspberry Pi Pico 拡張

VS Code に Raspberry Pi 公式の拡張機能をインストールする。
MicroPython でも C/C++ でも同じ環境で開発できる。
REPL（対話式シェル）が拡張機能に内蔵されており、
コードを打てばその場で Pico 上で動かせる。

**他の選択肢：**
- Thonny：もっとシンプルだが機能が少ない
- Mu Editor：デバッガーがない
- 詳細は IDE 比較資料（ide_comparison.md）を参照

### セットアップ手順

1. VS Code をインストールする（ https://code.visualstudio.com/ ）
2. VS Code の拡張機能で「Raspberry Pi Pico」を検索してインストールする
   （published by Raspberry Pi）
3. Pico 2 WH を USB ケーブルで PC に接続する
4. VS Code 左サイドバーの Raspberry Pi アイコンをクリックする
5.「New MicroPython Project」を作成する
6. MicroPython ターミナル（REPL）が開いて `>>>` が表示されれば接続成功
7. 試しにシェルで以下を打つ：
   ```
   >>> from machine import Pin
   >>> print("OK")
   ```
   `OK` と表示されれば、MicroPython が動いている

---

## テストの方法

### 基本ルール：「1段階書いたら、そのたびに動かして確認する」

全部作ってから動かすと、どこでバグってるか分からない。
段階ごとに「書いて→動かして→結果を見る」の繰り返し。

### ファイルを単体で動かす方法

Picoでは普通に電源を入れると `main.py` が自動で実行される。
でも各ファイルを単体でテストしたいときは、**ファイルの末尾にテストコードを書く**。

```python
# capture.py の例
class IRCapture:
    # ... 本来のコード ...

# ↓ ファイルの一番下に追加
if __name__ == "__main__":
    # capture.py を直接実行したときだけ、ここが動く
    # main.py から import されたときは動かない
    from time import sleep_ms
    cap = IRCapture(pin_num=15)
    print("リモコンを押してみて...")
    while True:
        sleep_ms(500)
        data = cap.get_and_reset()
        if data:
            print(f"受信: {len(data)} エッジ")
```

**`if __name__ == "__main__":` の仕組み：**
- ファイルを**直接実行**したとき → `__name__` は `"__main__"` になる → テストコードが動く
- 別のファイルから **import された**とき → `__name__` は `"capture"` になる → テストコードは動かない

### VS Code で実行する手順

1. VS Code で Pico に接続する（MicroPython ターミナルが開いている状態）
2. テストしたいファイル（例：`capture.py`）を開く
3. ターミナルで実行する：
   ```
   >>> exec(open("capture.py").read())
   ```
4. シェルに結果が出力される
5. リモコンを押して動作を確認する

**注意：** この状態で `main.py` もPicoに存在する場合、
手動で実行したときは `capture.py` が動いて、
Picoを電源再投入したときは `main.py` が動く。
2つのファイルが干渉しないように、テスト中は `main.py` をリネームするか消しておく。

### テストの流れ（この資料の進め方）

| ステップ | 書くファイル | 確認すること |
|---------|-------------|-------------|
| 1 | `capture.py` | リモコンを押すとエッジが記録されるか |
| 2 | `protocol.py` | ダミーデータをデコードできるか |
| 3 | `buttons.py` | コードを入れるとボタン名が返るか |
| 4 | `ir_send.py` | 赤外線LEDが点滅するか |
| 5 | `main.py` | 全部がつながり、Wi-Fi経由で操作できるか |

---

## 段階①：信号を記録する（capture.py）

### 何をやるか

リモコンのボタンを押すと、PL-IRM1838Bから「HIGH」「LOW」の電圧変化が届く。
これを**「いつ・どれくらいの間」** HIGHだったかLOWだったかをマイクロ秒で記録する。

### なぜこれだけ？

いきなり「電源ボタンはこれです」とは決められない。
まず「信号がちゃんと届いているか」「どんな数字が並んでいるか」だけでも見る。

### 使うもの

Pico + PL-IRM1838B（受信モジュール）

### なぜこういう構造にするか

```
[現在のアプローチ]
  割り込みごとに durations[i] に直接書き込む
  → 配列のインデックスを管理する必要がある
  → 記録が溢れたら終了
  → フレーム区切りの判定も同じ割り込みの中で行う

[理想的なアプローチ]
  割り込みは「時刻と状態を記録する」だけ
  → 非常に短く終わる（割り込みハンドラは長い処理の敵）
  → メインループでフレーム検出・処理を行う
  → 役割が分離されてデバッグが楽
```

### コード

```python
# capture.py — ハードウェア層：GPIO変化を timing リストに記録

from machine import Pin
from time import ticks_us, ticks_diff

class IRCapture:
    def __init__(self, pin_num=15):
        self.pin = Pin(pin_num, Pin.IN)
        self.timings = []       # (elapsed_us, level) のリスト
        self._last_us = 0
        self._last_level = 0
        self._started = False
        self.pin.irq(
            handler=self._on_edge,
            trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING
        )

    def _on_edge(self, pin):
        now = ticks_us()
        level = pin.value()
        if self._started:
            elapsed = ticks_diff(now, self._last_us)
            self.timings.append((elapsed, self._last_level))
        else:
            # 最初の立下りから記録開始（待機中の長いHIGHを避ける）
            if level == 0:
                self._started = True
        self._last_us = now
        self._last_level = level

    def get_and_reset(self):
        """現在の記録を取得してクリアする"""
        result = self.timings
        self.timings = []
        self._started = False
        return result

    def stop(self):
        self.pin.irq(handler=None)

    def start(self):
        self.pin.irq(
            handler=self._on_edge,
            trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING
        )

# === テスト用（capture.py 単体で実行したときだけ動く） ===
if __name__ == "__main__":
    from time import sleep_ms
    cap = IRCapture(pin_num=15)
    print("リモコンを押してみて...")
    while True:
        sleep_ms(500)
        data = cap.get_and_reset()
        if data:
            print(f"受信: {len(data)} エッジ")
            for elapsed, level in data[:10]:
                print(f"  level={level}  {elapsed}us")
```

**ポイント：**
- 割り込みハンドラ（`_on_edge`）は**極力短い**。リストに追加するだけ。
- フレーム検出・解析は呼ばない。それは次の層の仕事。
- `get_and_reset()` でメインループから安全にデータを取出せる。

---

## 段階②：フレームに分割し、ボタンコードを抽出する（protocol.py）

### 何をやるか

`capture.py` が記録した `(elapsed_us, level)` の並びから：
1. 長い無信号（＝フレーム間の空白）で区切りを見つける
2. 1フレーム分の timing を取り出す
3. ヘッダ・ビット列・繰返しに分割する
4. ビット列（0と1の列）を返す

### なぜこの段階で？

capture.py は「届いた信号を記録する」だけで、中身は知らない。
protocol.py が「記録された信号の中身を読み解く」仕事をする。

### なぜこういう構造にするか

```
[現在のアプローチ]
  解析の各ステップ（記号化→ビット化→登録→判定）が
  異なる関数・ファイルに分散
  → 途中経過を見たいとき、どの関数を呼べばいいか分かりにくい

[理想的なアプローチ]
  protocol.py が「生の timing → ボタンコード」の
  一連の変換を1つの流れで行う
  → 「入力 timing → 出力コード」が1行で確認できる
  → 解析ツールからもメインからも同じ関数を呼べる
```

### コード

```python
# protocol.py — プロトコル層：timing → ボタンコード

# --- 定数（NECリモコンの例。実測で調整する） ---
HEADER_MARK_US = 9000      # ヘッダの MARK 長さ
HEADER_SPACE_US = 4500     # ヘッダの SPACE 長さ
BIT_MARK_US = 560          # ビット区間の MARK 長さ
BIT_SPACE_SHORT_US = 560   # ビット 0 の SPACE 長さ
BIT_SPACE_LONG_US = 1690   # ビット 1 の SPACE 長さ
TOLERANCE_US = 400         # 許容誤差
FRAME_GAP_US = 20000       # フレーム区切りの空白（µs）

def _in_range(value, target):
    """value が target ± TOLERANCE_US の範囲内か"""
    return abs(value - target) <= TOLERANCE_US

def detect_frames(timings):
    """timing リストをフレームごとに分割して返す"""
    frames = []
    current = []
    for elapsed, level in timings:
        # SPACE(lv=1) が十分長ければフレーム区切り
        if level == 1 and elapsed > FRAME_GAP_US:
            if current:
                frames.append(current)
            current = []
        else:
            current.append((elapsed, level))
    if current:
        frames.append(current)
    return frames

def decode_frame(frame_timings):
    """
    1フレームの timing からボタンコード(32bit整数)を返す。
    失敗した場合は None を返す。

    NEC規格の例：
      先頭: MARK 9000 + SPACE 4500 （ヘッダ）
      ビット: 各MARK 560 + SPACE 560(=0) or 1690(=1)
      繰返し: MARK 560 + SPACE 約108000ms
    """
    if not frame_timings:
        return None

    # ヘッダの確認
    first_elapsed, first_level = frame_timings[0]
    if first_level != 0:    # 最初は MARK(LOW)
        return None
    if not _in_range(first_elapsed, HEADER_MARK_US):
        return None
    if len(frame_timings) < 2:
        return None
    second_elapsed, second_level = frame_timings[1]
    if second_level != 1:   # 次は SPACE(HIGH)
        return None
    if not _in_range(second_elapsed, HEADER_SPACE_US):
        return None

    # ビット列の復号
    bits = []
    i = 2  # ヘッダの後から開始
    while i + 1 < len(frame_timings):
        mark_us, mark_lv = frame_timings[i]
        space_us, space_lv = frame_timings[i + 1]

        if mark_lv != 0 or space_lv != 1:
            break

        if not _in_range(mark_us, BIT_MARK_US):
            break

        if _in_range(space_us, BIT_SPACE_LONG_US):
            bits.append(1)
        elif _in_range(space_us, BIT_SPACE_SHORT_US):
            bits.append(0)
        else:
            break

        i += 2

    if len(bits) != 32:
        return None

    # 32ビットを整数に変換
    code = 0
    for b in bits:
        code = (code << 1) | b
    return code

# === テスト用 ===
if __name__ == "__main__":
    # ダミーの timing データでテスト
    dummy = [
        (9000, 0), (4500, 1),   # ヘッダ
        (560, 0), (560, 1),     # bit 0
        (560, 0), (1690, 1),    # bit 1
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (1690, 1),    # bit 1
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (560, 1),     # bit 0
        (560, 0), (1690, 1),    # bit 1
        (560, 0), (560, 1),     # bit 0
        (560, 0), (20000, 1),   # フレーム末尾
    ]
    frames = detect_frames(dummy)
    print(f"フレーム数: {len(frames)}")
    for f in frames:
        code = decode_frame(f)
        if code is not None:
            print(f"デコード成功: 0x{code:08X}")
        else:
            print(f"デコード失敗 ({len(f)} エッジ)")
```

**ポイント：**
- **1つの関数で「timing → ボタンコード」が完了する。**
  中間の記号化ステップを外部から見せる必要がない。
- ヘッダ・ビット・繰返しの**規格（NEC等）に依存する部分は定数として上に集める**。
  別のリモコンに対応するときは定数だけ変えればいい。
- 許容誤差（`TOLERANCE_US`）は実測して調整する。

---

## 段階③：ボタン辞書をつくる（buttons.py）

### 何をやるか

「32ビットのコード → ボタン名」の対応を辞書で持つ。
これは**分析の結果として手動or自動で作る**もの。

### なぜ記号に？

protocol.py が返してきた32ビットのコードは、実測しないと「何のボタンか」分からない。
buttons.py に登録することで、コード→ボタン名の変換が可能になる。

### コード

```python
# buttons.py — データ層：ボタンコード → ボタン名

BUTTONS = {
    # 以下は例。実測した32ビットコードを入れる。
    # 実際の値は analyze.py で生成する。
    0x00FF_A05F: "POWER",
    0x00FF_609F: "TEMP_UP",
    0x00FF_20DF: "TEMP_DOWN",
    0x00FF_807F: "MODE_COOL",
    0x00FF_40BF: "FAN_UP",
}

def identify(code):
    """ボタンコードからボタン名を返す。不明な場合は None"""
    return BUTTONS.get(code)

# === テスト用 ===
if __name__ == "__main__":
    test_codes = [0x00FF_A05F, 0x00FF_609F, 0x00FF_FFFF]
    for code in test_codes:
        name = identify(code)
        print(f"0x{code:08X} → {name or '(不明)'}")
```

### ボタン辞書はどうやって作るか（分析ツール）

```python
# analyze.py — PC側ツール：測定データからボタン辞書を生成

import csv
import glob
from collections import defaultdict

def load_capture(filepath):
    """BEGIN〜END間の (level, duration_us) を読む"""
    rows = []
    in_capture = False
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line == "BEGIN":
                in_capture = True
                continue
            if line == "END":
                break
            if in_capture:
                parts = line.split()
                if len(parts) == 3:
                    rows.append((int(parts[1]), int(parts[2])))
    return rows

def analyze_directory(data_dir):
    """data/ 以下の全キャプチャを読み、コードごとの出現回数を数える"""
    code_counts = defaultdict(int)
    for filepath in sorted(glob.glob(f"{data_dir}/*.csv")):
        timings = load_capture(filepath)
        # protocol.py を使ってデコード
        from protocol import detect_frames, decode_frame
        frames = detect_frames(timings)
        for frame in frames:
            code = decode_frame(frame)
            if code is not None:
                code_counts[code] += 1
    return code_counts

if __name__ == "__main__":
    counts = analyze_directory("data")
    print("=== 検出されたボタンコード ===")
    for code, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  0x{code:08X}  ×{n}回")
    print()
    print("上記のコードを buttons.py の BUTTONS 辞書に追加してください")
```

**ポイント：**
- 実測データを `analyze.py` に通すと「このコードが何回検出されたか」が分かる
- 同じボタンを複数回押した codes が集まれば、それがそのボタンの型
- 人間が「これは電源ボタン」と名前を付けて `buttons.py` に書き込む
- **「記号化→ビット化」の手動ステップがなくなる。** 規格を知れば自動化できる。

---

## 段階④：赤外線を送出する（ir_send.py）

### 何をやるか

ボタンコード（32ビット）を受け取り、対応する赤外線信号を赤外線LEDで送出する。

### なぜこの段階で？

まず「相手の信号を受け取れる」ことが確認できてから、「こちらから出せる」に進む。
受信なしで送信だけやっても、信号が正しいか分からない。

### なぜPWMか

38kHzの搬送波をGPIOで直接点滅させるのは精度的に難しい。
PicoのPWM機能を使えば、38kHzの矩形波をハードウェアで安定出力できる。
プログラムは「PWMをONにするかOFFにするか」だけを制御すればいい。

### コード

```python
# ir_send.py — 送信層：ボタンコードを赤外線信号に変換して送出

from machine import Pin, PWM
from time import sleep_us

class IRsender:
    def __init__(self, pin_num=16):
        self.pwm = PWM(Pin(pin_num))
        self.pwm.freq(38000)      # 38kHz搬送波
        self.pwm.duty_u16(0)      # 最初はOFF

    def _mark(self, duration_us):
        """搬送波を出して指定時間待つ"""
        self.pwm.duty_u16(32768)  # 50%デューティ（ON）
        sleep_us(duration_us)

    def _space(self, duration_us):
        """搬送波を止めて指定時間待つ"""
        self.pwm.duty_u16(0)      # OFF
        sleep_us(duration_us)

    def send_code(self, code, repeats=2):
        """
        32ビットのボタンコードを赤外線で送信する。
        NECフォーマットの例。
        """
        for _ in range(repeats):
            # ヘッダ
            self._mark(9000)
            self._space(4500)

            # データ部（32ビット）
            for i in range(32):
                bit = (code >> (31 - i)) & 1
                self._mark(560)
                if bit == 1:
                    self._space(1690)
                else:
                    self._space(560)

            # 最後のマーク
            self._mark(560)

            # フレーム間の空白
            self._space(108000)

        self.pwm.duty_u16(0)

    def off(self):
        """送信を停止し、PWMを無効化する"""
        self.pwm.duty_u16(0)
        self.pwm.deinit()

# === テスト用（赤外線LEDが接続されていること） ===
if __name__ == "__main__":
    sender = IRsender(pin_num=16)
    print("テスト送信: 0x00FFA05F を2回送信")
    sender.send_code(0x00FFA05F, repeats=2)
    sender.off()
    print("完了。エアコンが反応したか確認してみて。")
```

**ポイント：**
- **PWMが38kHzを出している間は、GPIOのON/OFFで搬送波の有無を制御できる。**
  これがPicoの大きな利点。
- `_mark()` / `_space()` が**ネスト**している（`_mark`の中で`sleep_us`している）。
  これにより、赤外線プロトコルの「MARKとSPACEの交互パターン」が
  コード上でそのまま読み取れる。
- `sleep_us()` はPythonの関数呼び出しのオーバーヘッドがあるため、
  超精密が必要な場合はPIOを使う。ただしNEC等の一般的なリモコンでは
  このレベルで十分動く。

---

## 段階⑤：全部を束ねる（main.py）

### 何をやるか

受信→判定→送信の流れを1つにまとめ、さらにWi-Fi経由でスマホからの操作を受け付ける。

### なぜここが最後？

capture.py、protocol.py、buttons.py、ir_send.py が全部揃って初めて、
「リモコンを押した→ボタンを識別した→エアコンを操作した」の一連の流れが通る。
ここが通ったとき、初めて「動いた！」といえる。

### コード

```python
# main.py — アプリ層：受信・判定・送信・Wi-Fi

import network
import socket
from time import sleep_ms
from capture import IRCapture
from protocol import detect_frames, decode_frame
from buttons import identify
from ir_send import IRsender

# --- 初期化 ---
capture = IRCapture(pin_num=15)
sender = IRsender(pin_num=16)

# --- Wi-Fi接続 ---
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect("YOUR_SSID", "YOUR_PASSWORD")
while not wlan.isconnected():
    sleep_ms(500)
print("Wi-Fi接続:", wlan.ifconfig()[0])

# --- 受信ループ（常時） ---
print("受信待機中...")
while True:
    sleep_ms(100)

    # タイミングの記録を取得
    timings = capture.get_and_reset()
    if not timings:
        continue

    # フレーム分割 → デコード
    frames = detect_frames(timings)
    for frame in frames:
        code = decode_frame(frame)
        if code is not None:
            name = identify(code)
            if name:
                print(f"受信: {name} (0x{code:08X})")
            else:
                print(f"不明: 0x{code:08X}")

# --- Wi-Fi送信部分（別途追加） ---
# HTTPサーバーを立ち上げ、
# スマホから POST /send?button=POWER を受け取って
# sender.send_code(BUTTONS["POWER"]) を呼ぶ。
# → 34, 35ページで作る。
```

---

## 全体の流れ図（コード同士の関係）

```
スマホ
  │
  │ HTTP POST /send?button=POWER
  │
  ▼
┌─────────────┐    Wi-Fi    ┌─────────────┐
│   main.py   │◄────────────│  Wi-Fiサーバー │
│             │             │  (main.py内)  │
└──────┬──────┘             └─────────────┘
       │
       │ ボタンコード
       ▼
┌─────────────┐         ┌─────────────┐
│ ir_send.py  │────LED──│ 赤外線LED    │
│  送信層     │         └─────────────┘
└─────────────┘
                                      エアコン
┌─────────────┐         ┌─────────────┐     │
│ir_send.pyから│         │PL-IRM1838B │─────┘
│受信した場合  │         │  受信モジュール│  赤外線
└──────┬──────┘         └──────┬──────┘
       │                       │
       │ timings               │ GPIO15
       ▼                       ▼
┌─────────────┐    ┌─────────────────┐
│ protocol.py │◄───│  capture.py     │
│ プロトコル層 │    │  ハードウェア層  │
└──────┬──────┘    └─────────────────┘
       │
       │ code
       ▼
┌─────────────┐
│ buttons.py  │
│ データ層    │──► ボタン名
└─────────────┘
```

---

## 現行コードとの違い：何が変わったか

| 項目 | 現行（22〜33ページ） | draft2 |
|------|---------------------|--------|
| ファイル数 | 6+個（capture, analyze, signatures, main, tools/...） | 5個（capture, protocol, buttons, ir_send, main） |
| 割り込みの役割 | カウント＋時間記録＋フレーム判定を混在 | 記録だけ。他はメインループ |
| 解析ステップ | 記号化→ビット化→登録→判定（手動较多） | timing→コード（protocol.py 1本） |
| 送信 | 未作成（34-35ページ） | ir_send.py で完成形を先に示す |
| ボタン辞書生成 | 手動 | analyze.py で半自動 |
| 影響範囲 | ファイル間の依存が多い | 各層が独立（下の層は上の層を知らない） |

---

## なぜこの構造が良いか

1. **途中で確認できる。** capture.py だけ動かして「信号が届いているか」確認できる。
   protocol.py だけ動かして「デコードできるか」確認できる。
2. **デバッグが楽。** 「受信できない」問題が起きたとき、
   capture.py の出力を確認すれば「ハードウェア層まで問題ない」が分かる。
3. **拡張しやすい。** 別のリモコンに対応するとき、
   protocol.py の定数だけ変えればいい。他は変更不要。
4. **初学者でも理解しやすい。** 「1ファイル = 1役割」なので、
   「次に何を書けばいいか」が分かりやすい。

---

## 実装の進め方（21ページから見せる流れ）

```
21ページ：全体像と逆算フロー（このページ）
22ページ：capture.py — 最初のコード。信号が届くか確認
23ページ：protocol.py — timing をデコード
24ページ：analyze.py — 実測データからボタン辞書をつくる
25ページ：buttons.py — ボタン辞書を登録
26ページ：ir_send.py — 信号を送出
27ページ：main.py — 全部をつなぐ
28ページ：Wi-Fi接続 + スマホ操作
```
