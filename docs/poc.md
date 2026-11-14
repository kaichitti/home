# PoC 手順（判定1: 目標台数と1台あたりの増分）

企画書9章の最初のフェーズです。Redroid＋差分層で「実機→N台」を再現し、1台あたりのディスク増分とメモリ使用量を実測します。結果をもとに目標値（企画書1章）と、MVP へ進むかどうかを決めます。

## 1. 準備

```sh
droidfork doctor
```

NG がなくなるまで直します。binder がない場合の対処は `doctor` が表示します。

記録用に次の情報を控えておきます。

- CPU・メモリ・ディスク（SSD/HDD）
- ディストリビューションとカーネル（`uname -r`）
- 取り込み元の実機の Android バージョン

## 2. 雛形を作る

```sh
droidfork capture --name poc
droidfork template build poc
droidfork template show poc     # 導入に失敗したアプリと理由を確認
```

ARM向けアプリの導入結果（`INSTALL_FAILED_NO_MATCHING_ABIS` など）は、企画書10章の「動作確認リスト」の材料になります。

## 3. 台数を段階的に増やして測る

同じ条件で、台数を 1 → 5 → 10 → … と増やしながら測ります。各段階で全台の起動が終わり、1〜2分置いて落ち着いてから測ってください。

```sh
droidfork create poc -n 1 && droidfork start -t poc
droidfork stats --json > poc-01台.json

droidfork create poc -n 4 && droidfork start -t poc
droidfork stats --json > poc-05台.json

droidfork create poc -n 5 && droidfork start -t poc
droidfork stats --json > poc-10台.json
```

省メモリ設定の効果も比べます。一度すべて削除し、同じ手順を `--scale 0.5 --fps 15` で繰り返してください。

```sh
droidfork rm -t poc -y
droidfork create poc -n 10 --scale 0.5 --fps 15 && droidfork start -t poc
droidfork stats --json > poc-10台-省メモリ.json
```

## 4. 使い方を再現してから測る

起動しただけの状態では差分はほぼ空です。実際の使い方に近づけるため、各台でアプリを数回起動・操作してから、もう一度 `stats` を取ります。差分層の増え方（アプリのキャッシュ、データベースなど）は、ここで初めて見えます。

## 5. 識別子を確認する

```sh
droidfork ids
```

すべての台で「判定」が OK であること（シリアル・Android ID・MAC が重複していないこと）を確認します。

## 6. メモリの重複排除（KSM）を試す

```sh
echo 1 | sudo tee /sys/kernel/mm/ksm/run
# 数分待ってから
droidfork stats
```

まとめの「KSM」欄に、統合で節約できた量が出ます。KSM は、統合を許可したメモリ領域しか対象にしません。Android のプロセスが許可していなければ効果は小さくなりますが、それ自体が PoC で確かめる点です（企画書10章）。終わったら `echo 0 | sudo tee /sys/kernel/mm/ksm/run` で元に戻します。

## 7. 記録表

| 項目 | 1台 | 5台 | 10台 | 10台（省メモリ） |
| --- | --- | --- | --- | --- |
| 雛形の共有層（1つだけ） |  |  |  |  |
| ベースイメージ（1つだけ） |  |  |  |  |
| 1台あたりディスク増分（起動直後） |  |  |  |  |
| 1台あたりディスク増分（操作後） |  |  |  |  |
| 1台あたりメモリ |  |  |  |  |
| 平均起動時間 |  |  |  |  |
| ホストの空きメモリ |  |  |  |  |
| 追加で起動できる見込み台数 |  |  |  |  |
| データ領域の合計／丸ごとコピーした場合 |  |  |  |  |
| 識別子の重複 |  |  |  |  |

`stats --json` の `summary` が、ほぼこの表の各行に対応します。

## 8. 判定1

- 目標の PC スペック（例: メモリ 16GB）で、何台を安定して動かせたか
- 1台あたりの増分（ディスク・メモリ）を、企画書1章の目標値として書き込む
- 既存の多重起動型エミュレータを同じ PC で動かした台数と比べる

条件を満たせば MVP（自社業務での試用）へ進み、満たさなければ自社用ツールとして止めるかどうかを判断します。
