# yazi-flow

Yazi のペイン配置を「決定した行」に固定する小さなパッチとランチャー。

- **起動時**: 直前のターミナルカーソル（＝シェルプロンプト）の行がそのまま「決定行」になる。
- **左ペイン**: ハイライトされたカレントディレクトリを決定行に**固定**する（中央のカーソルには追従しない）。
- **中央ペイン**: 選択中のエントリが決定行に載り、後続は下へ、先行するものは上へ（末尾から
  先頭へ環状に、各エントリは1回だけ）。先頭を選んでいれば `ls` の最後のエントリが決定行の
  **1つ上**に来る。上下移動は**表示全体が1行ずつスクロール**する。

```
 プロンプトが 17 行目にあった                       yazi 起動後（H=22 行のペイン）
 ┌──────────────────────────┐              ┌──────────────────────────┐
 │ ...                      │              │ ~/Projects               │ ← header
 │ ❯ y                      │  ────────▶   │  a01 │                   │
 │                          │  視線そのまま │  a02 │ f00.txt           │ ← ここが決定行
 └──────────────────────────┘              │▶m_cwd│ f01.txt           │
   カーソル = 17 行目                        └──────────────────────────┘
                                             左のハイライトと中央の先頭が同じ行
```

## しくみ

Yazi 26 のペインは `yazi-plugin/preset/components/*.lua` が描いており、その中身は
バイナリに埋め込まれています（`preset!()`）。**利用者が置くプラグインからは**縦位置を
動かせません:

- `Folder.offset` / `cursor` は Lua から**読み取り専用**
  （`yazi-actor/src/lives/folder.rs` は `add_field_method_get` だけ）
- `rt.mgr` の setter が受けるのは `ratio`（横）だけ（`yazi-plugin/src/runtime/runtime.rs`）
- `mgr.scrolloff` は起動位置に効かない（実測: 0〜20 のどれでも親のハイライトは 1 行目）

一方、プリセット側は `folder.files`（全エントリ）と `folder.cursor` を読めるので、
**自分で描く行を決められます**。そこで 2 ファイルだけ差し替えています:

| ファイル | 役割 |
| --- | --- |
| `modules/current.lua` | 中央ペイン。選択を決定行に固定し、前後を環状に配置する。`Flow` テーブル（共有状態）もここ |
| `modules/parent.lua` | 左ペイン。親一覧を `Flow.keep`（決定行）に合わせて描く。届かない分は空行で埋める |

Rust 側の変更はありません。`modules/` の 2 ファイルを上流の
`yazi-plugin/preset/components/` に**そのまま上書き**してビルドします（プリセットは
コンパイル時に埋め込まれるため、実行時に読まれるファイルではありません）。

## 構成

```
yazi-flow/
├── bin/yazi-flow         ランチャー（DSR で起動前のカーソル行を測り、YAZI_FLOW_ANCHOR を渡す）
├── modules/              上流のプリセットに上書きする Lua（この 2 ファイルが実体）
│   ├── current.lua
│   └── parent.lua
├── scripts/build.sh      clone → modules/ 上書き → cargo build → ~/.local/bin
├── tests/probe.py        PTY + pyte で配置を検証
├── tests/requirements.txt
└── Makefile              install / test / clean
```

`build/`（yazi の clone と `target/`）と `.venv/` は追跡しません。

## インストール

```sh
make install              # = scripts/build.sh: clone → modules/ を上書き → cargo build → ~/.local/bin
```

Rust ツールチェーン（1.95+）と数分の時間が要ります。`--rebuild` でソースを取り直し。
`~/.local/bin` に

- `yazi-flow-yazi` … パッチ版 Yazi 本体
- `yazi-flow` … ランチャーへのシンボリックリンク（シェルから名前で呼ぶため）

が入ります。

## 使い方

```sh
yazi-flow              # 現在地で起動（プロンプト行に合わせる）
yazi-flow ~/Projects   # 引数はそのまま yazi に渡る
yazi-flow --print      # 測った行と決めたアンカーを表示するだけ（起動しない）
yazi-flow --no-flow    # 素の yazi と同じ挙動
yazi-flow --anchor 10  # アンカーを手で指定（0 始まり、ペイン内の行）
```

環境変数:

| 変数 | 意味 |
| --- | --- |
| `YAZI_FLOW_ANCHOR` | 決定行（ペイン内 0 始まり）。ランチャーが設定 |

nushell の `y` は `~/.config/nushell/config.nu` で次のように差し替え済み:

```nu
def --env y [...args] {
    let tmp = (mktemp -t "yazi-cwd.XXXXXX")
    ^yazi-flow ...$args --cwd-file $tmp
    let cwd = (open $tmp)
    if $cwd != $env.PWD and ($cwd | path exists) {
        cd $cwd
    }
    rm -fp $tmp
}
```

`y` は `[...args]` の rest 引数なので、フラグを渡すときは `y -- --print` のように `--` を挟む。

## 計算

Yazi のレイアウト（`preset/components/root.lua`）は

```
row 0            header (1)
row 1 .. H-2     panes   (H-2 行、これが folder_limit)
row H-1          status  (1)
```

プロンプト行 `R`（1 始まり）→ **ペイン内 0 始まりの決定行**

```
anchor = clamp(R - 2, 0, H - 3)
```

`H=24` なら `anchor` は 0..21。`R=24`（最下行）だけはステータスバーの 1 行上までで、
ここは原理的に 1 行届きません。`R<=23` なら完全一致します。

中央ペインは決定行 `keep`（＝起動時のアンカー。セッション中は動かない）を軸に、描く順番
`k = 0, 1, 2, …`（`min(n, H)` 個まで）を次のように配置します。

```
down = H - keep - 1
k <= down  -> row = keep + k, エントリ = (cursor + k) mod n   -- 下方向（後続）
k >  down  -> row = keep - (k - down), エントリ = (cursor - (k - down)) mod n  -- 上方向（先行）
```

つまり選択中は常に決定行、その後ろが下へ、前が上へ。ディレクトリの端では環状に折り返し、
同じエントリは2度描きません（`n < H` なら全部で `n` 個だけ）。

`j`/`k`/↑/↓ は選択を1つ動かす＝**表示全体が1行スクロール**します。先頭で↑を押すと末尾に
回り込み、`ls` の最後のエントリが決定行に載って表示が1行ぶん下へずれます（崩れません）。

親ペインは `row`（＝カーソル行）ではなく `keep`（＝決定行）を目標に、`cursor` と `offset` から
自分の表示範囲を決める。つまり中央で `j`/`k` しても左のハイライト行は動かない。`offset` は
負にできないため、足りない分は空行で埋める。

## 検証

`tests/probe.py` は実際の PTY で起動し、DSR に「プロンプトはここ」と答えさせ、描かれた
画面から「左ペインのハイライト行」と「中央ペインのエントリ行」を読み取って比較します。

```sh
make test                         # venv を作って tests/probe.py を実行
.venv/bin/python tests/probe.py -v # 画面ダンプ付き
```

このマシン（80x24, yazi 26.9.1, パッチ適用）での実測:

```
ok   deep cwd, prompt at bottom: prompt_row=24 left(m_cwd)=22 f00@22 f38@20 f39@21
ok   deep cwd, prompt mid screen: prompt_row=18 left(m_cwd)=17 f00@17 f01@18 f38@15 f39@16
ok   deep cwd, prompt high: prompt_row=8 left(m_cwd)=7 f00@7 f01@8 f38@5 f39@6
ok   only child cwd (like /home/knt419): prompt_row=24 left(m_cwd)=22 f00@22 f38@20 f39@21
ok   cwd near end of listing: prompt_row=24 left(m_cwd)=22 f00@22 f38@20 f39@21
ok   short listing stays below (5 files): prompt_row=8 left(m_cwd)=7 f00@7 f04@11（上は空）
ok   down arrow scrolls the view (j x5): prompt_row=18 left(m_cwd)=17 f00@12 f05@17 f06@18
ok   up arrow at the top scrolls, no collapse: prompt_row=24 left(m_cwd)=22 f38@21 f39@22
ok   up arrow twice: prompt_row=24 left(m_cwd)=22 f38@22
ok   up arrow wraps a short listing: prompt_row=8 left(m_cwd)=7 f00@8 f03@11 f04@7
ok   cd keeps the decision row: left(d05)=17 inside.txt=17
info stock yazi (no flow): prompt_row=24 left_highlight_row=1 (= 22 rows of gaze travel)

12/12 cases aligned
```

## 制限

- パッチ版バイナリが必要（`yazi-flow-yazi` が無いと警告して素の yazi で起動）。
- Yazi を更新したら `scripts/build.sh --rebuild` で作り直し（`YAZI_TAG` で版を指定）。
- タブを 2 枚以上にすると `Tabs.height()` が 1 行増え、決定行が 1 行ずれます。
- `<Tab>`（spot）の吹き出し位置は Rust 側の stock 計算なので、パディング分ずれます。
- 左ペインは決定行に固定なので、中央で深く移動すると左のハイライトと中央のカーソルは
  上下に離れます（意図した挙動）。
- 最下行のプロンプトだけはステータスバーの 1 行ぶん上まで（`R=24` → 23 行目）。
