# N07 SQLite接続解放の修正報告

2026-10-13 JST。修正範囲は独立balloon_n07のみ。既存iwata_dir/API/物理/GFS・DB・N05/N06は変更なし。既存探索のスキーマ移行・状態初期化は不要。

## 原因とログ確認

提供されたN07-test-errors.txt（全1563行）を確認。49件中46 errors、例外は一時ディレクトリ内n07.sqlite3削除時のPermissionError [WinError 32]。同じ例外がcleanup処理で再度出るため、ログ中の該当例外行は92回。別原因のテスト失敗を、このログから追加で主張しない。

前版はSQLite Connectionのwithがcommit/rollbackのみを行い、closeをしない点を見落としていた。Linuxでは開いたファイルもunlinkできるため、前回のLinux成功だけではWindowsのロック解放を確認できていなかった。

## ソース修正

| 対象 | 変更 |
|---|---|
| core.py / Store.connect | contextlib.contextmanagerへ変更。接続→try内PRAGMA→with dbでcommit/rollback→finallyでclose |
| tests/test_http_and_crash.py | StoreOwnershipの2つの直接sqlite3.connectをclosing＋内部トランザクションcontextで解放 |
| tests/test_sqlite_lifecycle.py | 新規。7件の接続解放・ファイル削除・例外・commit失敗回帰テスト |

Storeの各メソッドとtest_n07.pyの `with store.connect() as db` は、共通connectの修正で解放されるので、各呼出しの書換えは不要。クラッシュ試験の子プロセスは意図的にos._exitを呼ぶためPython finallyは通らないが、子プロセス終了をwaitし、OSによるハンドル解放とSQLite復旧を試験する。通常運用の未解放接続と混同しない。

修正の要点：

```python
@contextlib.contextmanager
def connect(self):
    db = sqlite3.connect(self.path, timeout=10)
    try:
        db.execute('PRAGMA synchronous=FULL')
        with db:
            yield db
    finally:
        db.close()
```

close前にcommit/rollbackを完了する。setup中の例外でもclose。BEGIN IMMEDIATEを使うupdate、WAL設定、FULL、要求送信前の確定保存、クラッシュ復旧・JSON hash検査は維持。接続を外へ返してGCに任せる方式ではない。GC強制実行・削除失敗の無視・sleepでの回避は追加していない。

## テスト結果

Work（Linux）で **既存49件＋新規7件＝56件すべて成功**。実行ログはevidence/unit-tests.txt。Windowsでの修正後再実行は未実施なので、Windowsで直ったと断定しない。

追加7件：

1. 作成/get/list/updateの接続をPythonのリストに保持したまま、全接続が閉じていることとDB改名・削除・一時フォルダー削除を確認。
2. 本文例外→rollback→close、元ドキュメント保持。
3. PRAGMA初期設定失敗でもclose。
4. 実SQLiteの遅延外部キー違反によりcommit失敗を起こし、rollbackとcloseを確認。
5. 読込失敗・不正所有DBによるconstructor例外でもclose。
6. WAL、synchronous=FULL（数値2）、BEGIN IMMEDIATE、並行読込を確認。
7. トランザクションcontext終了処理が例外を出してもclose。

既存の子プロセスクラッシュ・未commit rollback・原子的結果保存・応答切断・再開・50地点モック試験も成功。実GFS性能やWindows50地点受入を新しく測ったわけではない。

## Windows更新（既存N07だけ）

1. 実行中のN07管理プロセスがあれば通常中断して終了。既存APIを止めたりDBを削除したりする必要はない。
2. 修正版ZIPを**新しいフォルダー**へ展開。既存venv/storeは消さない。
3. 既存N07への最小更新は次の3ファイルだけでよい。manager/api/cliや既存本体の変更は不要。
   - core.py
   - tests/test_http_and_crash.py
   - tests/test_sqlite_lifecycle.py（新規）
4. 既存N07のコードをバックアップしてからコピー。元ログの配置例を使ったコマンド：

```powershell
# $fixedだけ、修正版を展開した実際の場所へ変更してください。
$fixed = "$env:USERPROFILE\Downloads\N07-SQLite-Fix\balloon_n07"
$current = "$env:USERPROFILE\Chart-Balloon-Simulator\balloon_n07"
if (-not (Test-Path "$fixed\tests\test_sqlite_lifecycle.py")) { throw '修正版の展開場所を確認してください。' }
if (-not (Test-Path "$current\core.py")) { throw '既存N07の場所を確認してください。' }
$backup = Join-Path $env:USERPROFILE ('N07-code-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item "$current\core.py" "$backup\core.py"
Copy-Item "$current\tests\test_http_and_crash.py" "$backup\test_http_and_crash.py"
Copy-Item "$fixed\core.py" "$current\core.py" -Force
Copy-Item "$fixed\tests\test_http_and_crash.py" "$current\tests\test_http_and_crash.py" -Force
Copy-Item "$fixed\tests\test_sqlite_lifecycle.py" "$current\tests\test_sqlite_lifecycle.py" -Force
Set-Location $current
$python = Join-Path $PWD '.venv\Scripts\python.exe'
```

既存N07のパスが違うなら$currentを変更。iwata_dirやAPIの保存先へコピーしない。修正版全体を新規フォルダーで検証する場合は同梱READMEのvenv手順を使う。

## Windows再テスト

まず追加回帰だけ：

```powershell
& $python -B -m unittest discover -s tests -p test_sqlite_lifecycle.py -v
```

期待：7 tests / OK。DBの改名・削除がWindowsで失敗しないことを含む。

次に全テスト：

```powershell
# 前回設定済みならそのN07_VALIDATOR_ROOTを維持。
# 未設定の場合、既存の元validator確認1件だけskipとなり55成功＋1skip。
& $python -B -m unittest discover -s tests -v
```

期待：56 tests / OK（元validatorパス指定済みならskipなし）。56件中どれか失敗した場合は、そのログを確認するまで追加原因や成功を推測しない。

PowerShellのstderr表示をNativeCommandError形式へ変換せず、素のログに保存したい場合：

```powershell
$log = Join-Path $PWD ('N07-tests-fixed-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt')
cmd /c ".venv\Scripts\python.exe -B -m unittest discover -s tests -v > `"$log`" 2>&1"
$testExitCode = $LASTEXITCODE
Get-Content $log
"Exit code: $testExitCode"
```

既存N07のWinError 32問題が解消したことをWindowsのログで確認してから、実GFS受入を再開する。N07全体の最終受入条件である実GFS50地点・復旧確認は別途残る。
