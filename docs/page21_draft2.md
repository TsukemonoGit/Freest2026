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
    そのために必要なのは？
      ↓
  「電源ON」→「この赤外線の並び」が分かる
    そのために必要なのは？
      ↓
  リモコンの信号を受信して、ボタンの型を登録する
    そのために必要なのは？
      ↓
  赤外線受信モジュールの出力を記録できる
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

## 段階①：信号を記録する（capture.py）

### 何をやるか

リモコンのボタンを押すと、PL-IRM1838Bから「HIGH」「LOW」の電圧変化が届く。
これを**「いつ・どれくらいの間」** HIGHだったかLOWだったかをマイクロ秒で記録する。

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

| 項目 | 現行（22〜33ページ） | 理想形（draft2） |
|------|---------------------|-----------------|
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
3. **拡張しやすい。** 别のリモコンに対応するとき、
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

（従来の22〜33ページの9ページ分が、5ページに圧縮され、
  残りのページで送信・Wi-Fi・スマホ画面に十分なスペースが確保できる）
