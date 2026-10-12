# スライド設計ルール集（出典付き）

作成日 2026-09-19。技術カンファレンス向けの日本語ミニマルスライド（白背景／黒〜濃灰の文字／
アクセント 1〜2 色／1 スライド 1 メッセージ／大きな数字／表よりも図）を作るために Web で調べた規則。
各項目の末尾 `— (Author+YY)` が出典、巻末に文献表。この deck で実際に採用した設計値は最後の節。

---

## 1. タイポグラフィ（サイズ・書体・文字量）

- 本文の最低サイズは 30 pt。「30 pt より小さいフォントを使わない」と縛ると最重要点だけが残る（10 枚／20 分／30 pt） — (Kawasaki05)
- 実務的な下限は本文 24 pt。会場最後列でも読める最小値 — (Duarte12)
- 大会場・プロジェクタなら本文 24〜28 pt、補足 16〜18 pt。小会議室モニタなら本文 18〜20 pt — (Freestyle25)
- 講演スライドはタイトル 36 pt 以上／本文 28 pt 以上。文字の少ないキースライドはタイトル 32 pt 以上／本文 24 pt 以上 — (Timewitch)
- 学会発表では 18 pt 以下を使わない（タイトル 30 pt 以上、見出し 20 pt 以上） — (ConventionConnect)
- 1 スライドで使う文字サイズは 3 種類まで（タイトル／見出し／本文） — (Freestyle25)
- タイトル：本文のジャンプ率は約 1.5 倍を基準に（本文 14 → 見出し 20 → タイトル 30） — (Freestyle25)
- 見出しサイズは本文の 1.3〜2 倍の範囲 — (Kakizaki23)
- 投影スライドはサンセリフ（ゴシック）一択 — (Reynolds)
- フォントは 1 ファイル 1 書体に絞る（和文ゴシック 1 種 + 必要なら欧文 1 種） — (Kakizaki23)
- 「最後列の人のために設計する」"Make it big and make it clear" — (Reynolds)
- 1 スライドは 3 秒で理解できること（glance test） — (Duarte12)
- 1 スライドの総文字数は 105 字以内（意思決定者 826 名への調査と 51,544 枚の解析。105 字以内・3 色以内で成約率 +22 %） — (Maeda&Horiguchi25)
- キーメッセージは 13 字以内、補足の箇条書きは 1 行 40 字以内 — (Maeda&Horiguchi25)
- 強調手段（太字・色・サイズ・書体・下線）を 3 つ以上併用しない — (Tsutawaru)
- 文字の縦横比を変えない — (Tsutawaru)
- スライドと配布資料を混ぜない（slideument を作らない）。最良のスライドは文字ゼロのこともある — (Reynolds)

### assertion–evidence（主張 + 証拠）の規則

- 見出しは「トピック語句」ではなく完全な文（sentence headline）で、そのスライドの主張そのものを書く — (Alley&Neeley05)
- 見出しは 1〜2 行以内 — (AlleyPSU08)
- 見出しは 28 pt で 8〜14 語（日本語なら 1 行 20 字前後 × 最大 2 行）、本文 18〜24 pt、出典表記 12〜14 pt（太字にしない） — (AE-Guidelines)
- 見出しの下に最低 0.5 インチの余白 — (AE-Guidelines)
- 主張を支えるのは箇条書きではなく視覚的な証拠（図・グラフ・写真・模式図）。証拠がスライド面積の大半を占める — (AlleyPSU08)
- トークを「トピック」ではなく「メッセージ」の連なりとして構成する。細部はノート欄へ — (Alley/CraftSciCom)
- 禁止：語句だけの見出し／箇条書きの羅列／見出しの文言を本文で再掲／文字に押されて図が小さくなること／スライドを読み上げること — (AlleyPSU08)

## 2. 日本語固有の組版

- 和文はゴシック体（UD 系）を第一候補に。BIZ UDP ゴシック／メイリオ／游ゴシック／ヒラギノ角ゴ W4／Noto Sans CJK JP — (Tsutawaru)
- BIZ UD フォントは「分かりやすい・読みやすい・読み間違えにくい」を基準に学術検証済み。SIL OFL 1.1 — (Morisawa)
- UD フォントの利点：濁点・半濁点の分離、O と C、3 と 8 など類似字形の判別性が小サイズで向上 — (Tsutawaru)
- Noto Sans JP は Weight 100〜900 のバリアブルフォント。書体を増やさずウェイト差だけで階層を作れる — (GoogleFonts)
- 行間はフォントサイズの 70 % 前後（0.7 文字分） — (Tsutawaru)
- 学会スライドでは行送り 1.1〜1.5 倍 — (ConventionConnect)
- 字間は文字サイズの 5 % 程度。PowerPoint の「広く」は空きすぎ — (Tsutawaru)
- 1 行が日本語 10 文字以下／英語 3 単語以下になると逆に読みにくい — (Tsutawaru)
- 1 行の上限は 20〜40 字（大画面では 20 字前後、可読上限 40 字） — (ShoubaiSekkei)
- 禁則処理を必ず ON。句読点・閉じ括弧が行頭に来ないように — (JLReq)
- 意味のまとまりを改行で断ち切らない。「のは」「ので」「には」などの助詞は前の語と同じ行に = 文節で改行する — (Tsutawaru)
- 自動折返し任せにせず、手動改行かテキストボックス幅で折返し位置を制御する — (Tsutawaru)
- 段落の最終行は句読点を含めて最低 3 文字は残す — (Tsutawaru)
- 和文と欧字・アラビア数字の間は原則「四分アキ」（行頭・行末では空けない）。半角スペースは広すぎる — (JLReq)
- 英数字は半角に統一 — (Tsutawaru)
- 基本は左揃え。長文のセンタリングは禁止。左端を必ず揃える — (Tsutawaru)
- 箇条書きはぶら下げインデント、記号は `•` より `●` など太めを — (Tsutawaru)
- スライドでは段落の 1 字下げを使わない — (Tsutawaru)
- 1 スライド 1 メッセージ = 1 チャート 1 メッセージ — (ITmedia13)
- 1 スライドに 2 つ以上の主張を置くと認知が分散し、どちらも伝わらない — (DaleCarnegieJP)

## 3. 配色・コントラスト

- 背景は無地の白。グラデーションは同一スライド内でコントラストが変動する — (Kakizaki23)
- 使う色は 4 色まで：背景（白）／文字（黒〜灰）／メイン色／強調色（最重要箇所のみ） — (Tsutawaru)
- 学会スライドはベース 70 %／メイン 25 %／アクセント 5 % — (ConventionConnect)
- 1 スライド 3 色以内 — (Maeda&Horiguchi25)
- PowerPoint 標準色のような高彩度色は使わない。色同士に明度差をつける — (Tsutawaru)
- 本文テキストのコントラスト比は 4.5:1 以上（WCAG 2.2 SC 1.4.3 AA） — (W3C-WCAG22)
- 大きな文字（18 pt 以上、または 14 pt 太字以上）は 3:1 以上 — (W3C-WCAG22)
- 投影環境では 7:1（AAA）を目標にすると安全 — (W3C-WCAG22)
- グラフの線・アイコンなど非テキスト要素も隣接色に対し 3:1 以上 — (W3C-WCAG22)
- 色覚多様性は日本人男性の約 5 %・女性の約 0.2 % — (Tsutawaru)
- CUD の原則：①どの色覚でも識別できる配色 ②色だけでなく形・位置・線種を併用 ③必要なら色名を明記 — (Okabe&Ito08)
- Okabe–Ito の 8 色：`#E69F00` 橙／`#56B4E9` 空色／`#009E73` 青緑／`#F0E442` 黄／`#0072B2` 青／`#D55E00` 朱／`#CC79A7` 赤紫／`#000000` 黒 — (Okabe&Ito08)
- 純赤は使わず朱色（vermilion）に置き換える — (Okabe&Ito08)
- 避ける組み合わせ：赤×緑、紫×青、橙×黄緑 — (Tsutawaru)
- 強調色は赤ではなく橙か水色（黒文字と区別しやすい） — (Tsutawaru)
- 文字色は真っ黒でなく濃い灰にするとチラつきが減る — (Tsutawaru)
- 灰色は「色数を増やした印象を与えない」ので非強調系列に積極的に使う — (Tsutawaru)
- "Use colors with purpose, choose just a few" — (Reynolds)
- CUD 推奨配色セット ver.4（2018）はアクセント・ベース・灰の 20 色 — (CUDO18)

## 4. ビジュアル構成・レイアウト

- 1 スライド 1 アイデア。箇条書きを並べるのではなくスライドを分割 — (Reynolds08)
- 余白を潰さない。ロゴや装飾で空きを埋めない — (Reynolds)
- S/N 比を上げる：意味に寄与しない要素は全部削る — (Reynolds)
- 画像は大きく、しばしば全画面で — (Reynolds)
- アニメーション・画面切替効果は最小限 — (Reynolds)
- coherence 原則：無関係な素材を除くと理解が深まる（23/23 件、d = 0.86） — (Mayer19)
- signalling 原則：重要箇所を強調する手がかり（色・太字・矢印）（24/28 件、d = 0.41） — (Mayer19)
- redundancy 原則：話す内容をそのまま文字で載せない（16/16 件、d = 0.86） — (Mayer19)
- spatial contiguity 原則：説明文は対応する図のすぐ隣に。凡例や注釈を図から離さない（22/22 件、d = 1.10） — (Mayer19)
- segmenting 原則：内容を扱える単位に区切る（10/10 件、d = 0.77） — (Mayer19)
- ゲシュタルトの近接：近いものは同じグループと知覚され、色や形の類似より強く働く — (NNg20)
- ゲシュタルトの類同：色・形・サイズのいずれか 1 つを共有させれば同じ仲間と読まれる — (NNg20)
- 揃え・グループ化・コントラストの 3 点を全スライドで守る — (Tsutawaru)
- 表ではなくグラフにする基準：値の「形（傾向・例外）」にメッセージがあるときはグラフ。精密値の参照が必要なときだけ表 — (Few12)
- 数値が 1〜2 個ならグラフでも表でもなく「大きな数字 + 短い言葉」（BAN） — (SWD21)
- 6×6 ルールは鵜呑みにしない。箇条書きは要素間の関係を示せない。assertion–evidence 型へ — (Forbes17)
- 高橋メソッド：巨大な文字のみ、1 枚数文字。節目の扉に限定して使うとミニマル路線と両立 — (Takahashi01)

## 5. スライド上のデータビジュアライゼーション

- data-ink ratio を最大化：データを表さないインク（chartjunk）は消す — (Tufte83)
- 凡例を廃し、線や棒のすぐ横に直接ラベル — (Tsutawaru)(SWD19)
- 注目させたい 1 系列だけに色をつけ、残りは灰に落とす — (Knaflic15)
- 軸そのものを消さず灰にして後退させる — (SWD19)
- 補助線を減らし、縦軸の目盛りは 3〜5 本 — (Tsutawaru)
- 棒グラフの基線は必ず 0 から — (Yau15)
- 折れ線グラフは 0 始まりでなくてよい — (Yau24)(SWD14)
- 言いたい 1 つの数値にだけ注釈。全点にラベルを振らない — (SWD19)
- 投影用の線幅は主系列 2〜3 pt、補助 1.5 pt。1 px の細線は消える — (Deckary25)
- 色だけで系列を区別しない：線種・マーカー形・ハッチングを併用 — (Okabe&Ito08)
- 表を残す場合は罫線を削り行間を広げる — (Tsutawaru)
- 3D グラフ・立体効果は使わない — (Tufte83)(Tsutawaru)

## 6. 参照動画のスタイルについて

- 動画「Kimi K3：フロンティア級LLMを支える コア技術」（https://youtu.be/ood8p_sa-HI）はチャンネル「数理の弾丸」（船蔵颯氏、https://www.youtube.com/@mathbullet）。
- 概要欄・映像は取得できない（YouTube は JS のみ返す）。同氏の Speaker Deck（https://speakerdeck.com/mathbullet）に実物のデッキが 7 点あり、
  そこから背景・見出し・アクセントの使い方を実測して本 deck に反映した（詳細は下の「採用した設計値」）。

---

## この deck で採用した設計値

| 項目 | 値 | 根拠 |
|---|---|---|
| 出力 | LuaLaTeX Beamer 16:9（160 × 90 mm）、PDF | 禁則・和欧文間隔を luatexja が処理、1 枚ずつ描画して確認できる |
| 見出し | HaranoAji Gothic Heavy 22 pt（PPT 換算 ≈ 46 pt）、主張 1 文、最大 2 行 | AlleyPSU08, AE-Guidelines, Timewitch |
| 本文 | 12 pt（≈ PPT 25 pt） | Duarte12, Freestyle25 |
| 大きな数字 | Heavy 48–54 pt、アクセント色 | SWD21 |
| 出典・引用 | 8.5–9 pt、`#6B7280`（コントラスト 4.8:1） | ConventionConnect（18 pt 以下を使わない）, W3C-WCAG22 |
| 書体 | 和文 HaranoAji Gothic（4 ウェイト）、欧文・数字 Fira Sans、数式 Fira Math | Kakizaki23（1 書体）, Reynolds（サンセリフ） |
| 色 | 文字 `#1A1A1A`、補足 `#4B5563`、青 `#0072B2`（北海道・主要数字）、朱 `#D55E00`（和歌山・警告、大きな文字のみ）、淡青面 `#E3EEF8` | Okabe&Ito08, Tsutawaru（橙は強調色に向く）, W3C-WCAG22 |
| 図 | 凡例なし・直接ラベル、注目系列だけ色、棒は 0 起点、目盛 3〜5 本、主線 3 pt | Knaflic15, Few12, Yau15, Deckary25 |
| 改行 | 見出し・本文は文節で `\\` を手動指定、助詞の直前で切らない | Tsutawaru, JLReq |
| 文字量 | 1 枚 105 字以内を目標、本文の文字サイズは 3 段階まで | Maeda&Horiguchi25, Freestyle25 |

---

## 文献表

| キー | 参照 | URL |
|---|---|---|
| Kawasaki05 | Guy Kawasaki, "The 10/20/30 Rule of PowerPoint", 2005 | https://guykawasaki.com/the_102030_rule/ |
| Duarte08 | Nancy Duarte, *slide:ology*, O'Reilly, 2008 | https://www.duarte.com/resources/books/slideology/ |
| Duarte12 | Nancy Duarte, "Do Your Slides Pass the Glance Test?", HBR, 2012 | https://hbr.org/2012/10/do-your-slides-pass-the-glance-test |
| Reynolds08 | Garr Reynolds, *Presentation Zen*, New Riders, 2008 | https://presentationzen.com/ |
| Reynolds | Garr Reynolds, "How to Design a Great Presentation" | https://www.garrreynolds.com/design-tips |
| Alley&Neeley05 | M. Alley & K. A. Neeley, "Rethinking the Design of Presentation Slides: A Case for Sentence Headlines and Visual Evidence", *Technical Communication* 52(4), 417–426, 2005 | https://pure.psu.edu/en/publications/rethinking-the-design-of-presentation-slides-a-case-for-sentence-/ |
| AlleyPSU08 | M. Alley (Penn State), "How to Create an Assertion-Evidence Presentation", 2008 | https://cpb-us-e1.wpmucdn.com/sites.psu.edu/dist/7/13153/files/2008/10/Assertion-Evidence-Slides-Instruction_Set.pdf |
| Alley/CraftSciCom | The Craft of Scientific Communication / Assertion-Evidence Approach | https://www.assertion-evidence.com/ |
| AE-Guidelines | "5.12 Designing Assertion-Evidence Slide Decks", *Strategic Business Communication* (FHSU Pressbooks) | https://fhsu.pressbooks.pub/strategicbcomm/chapter/5-12-message-strategy-evidence/ |
| Mayer19 | R. E. Mayer, "How multimedia can improve learning and instruction", *Impact*, 2019（一次文献は Mayer & Fiorella 2014, Cambridge Handbook of Multimedia Learning ch.12） | https://my.chartered.college/impact_article/how-multimedia-can-improve-learning-and-instruction/ |
| Tufte83 | E. R. Tufte, *The Visual Display of Quantitative Information*, Graphics Press, 1983 | — |
| Knaflic15 | C. N. Knaflic, *Storytelling with Data*, Wiley, 2015 | https://www.wiley.com/en-us/Storytelling+with+Data-p-9781119002253 |
| SWD14 | storytelling with data, "a little math on non-zero baselines", 2014 | https://www.storytellingwithdata.com/blog/2014/02/a-little-math-on-non-zero-baselines |
| SWD19 | storytelling with data, "declutter! (and question default settings)", 2019 | https://www.storytellingwithdata.com/blog/2019/5/13/declutter-and-question-defaults |
| SWD21 | storytelling with data, "storytelling with simple text", 2021 | https://www.storytellingwithdata.com/blog/2021/5/20/storytelling-with-simple-text |
| Few12 | S. Few, "Effective Chart Design", Perceptual Edge | https://www.perceptualedge.com/images/Effective_Chart_Design.pdf |
| Yau15 | N. Yau, "Bar Chart Baselines Start at Zero", FlowingData, 2015 | https://flowingdata.com/2015/08/31/bar-chart-baselines-start-at-zero/ |
| Yau24 | N. Yau, "Why Line Chart Baselines Can Start at Non-Zero", FlowingData, 2024 | https://flowingdata.com/2024/03/06/line-chart-baselines/ |
| Okabe&Ito08 | M. Okabe & K. Ito, "Color Universal Design (CUD)", 2008 | https://jfly.uni-koeln.de/color/ |
| CUDO18 | NPO カラーユニバーサルデザイン機構「推奨配色セット ver.4」, 2018 | https://jfly.uni-koeln.de/colorset/ |
| W3C-WCAG22 | W3C, *WCAG 2.2*, SC 1.4.3 / 1.4.6 / 1.4.11 | https://www.w3.org/TR/WCAG22/#contrast-minimum |
| JLReq | W3C 日本語組版タスクフォース「簡便な行組版ルール（案）」／*Requirements for Japanese Text Layout* | https://w3c.github.io/jlreq/docs/line-composition/ |
| Tsutawaru | 高橋佑磨・片山なつ「伝わるデザイン｜研究発表のユニバーサルデザイン」 | https://tsutawarudesign.com/ |
| Morisawa | 株式会社モリサワ「BIZ UD フォントとは？」 | https://www.morisawa.co.jp/support/faq/3854 |
| GoogleFonts | Google Fonts, "Noto Sans Japanese" | https://fonts.google.com/noto/specimen/Noto+Sans+JP |
| Kakizaki23 | 柿崎真沙子「スライド作成のABC（3）」『週刊医学界新聞』3536 号, 2023 | https://www.igaku-shoin.co.jp/paper/archive/y2023/3536_04 |
| ConventionConnect | Convention Connect「学会発表のスライドで押さえるべきポイント」 | https://connect.c-cloud.co.jp/articles/column/23 |
| Freestyle25 | フリースタイルエンターテイメント「パワーポイントの見やすい文字の大きさは？」 | https://www.freestyle-entertainment.co.jp/ppt/column/font-size/ |
| Timewitch | Timewitch「スライドの『最適な文字の大きさ』にはワケがある」（検索スニペット由来、原文未確認） | https://note.timewitch.jp/n/nfd30571585b6 |
| Maeda&Horiguchi25 | 前田鎌利・堀口友恵『プレゼン資料の図解化大全』ダイヤモンド社, 2025 | https://diamond.jp/articles/-/363098 |
| ITmedia13 | ITmedia「マッキンゼーのプレゼン資料は、1 チャート 1 メッセージ」, 2013 | https://www.itmedia.co.jp/bizid/articles/1311/19/news010_2.html |
| DaleCarnegieJP | デール・カーネギー・ジャパン「1 スライド 1 メッセージ原則」 | https://www.dale-carnegie.co.jp/library/blog/5976/ |
| Takahashi01 | 高橋征義「高橋メソッド」2001／『でかいプレゼン』SB クリエイティブ, 2005 | https://ja.wikipedia.org/wiki/高橋メソッド |
| NNg20 | Nielsen Norman Group, "Proximity / Similarity Principle in Visual Design" | https://www.nngroup.com/articles/gestalt-proximity/ |
| Forbes17 | ProPoint Graphics, "Debunking the Presentation 6x6 Rule", Forbes, 2017 | https://www.forbes.com/sites/propointgraphics/2017/07/05/debunking-the-presentation-6x6-rule/ |
| ShoubaiSekkei | 商売設計「文章が劇的に読みやすくなる『一行の長さ』」 | https://www.shoubaisekkei.co.jp/column/number-of-characters |
| Deckary25 | Deckary, "Line Charts in PowerPoint: Best Practices" | https://deckary.com/blog/line-chart-powerpoint |

### 確認メモ

- AE の「28 pt／18–24 pt／8–14 語」は Alley 由来の教育用ガイド経由（Penn State 一次 PDF は抽出が部分的）。
- Mayer の効果量は Mayer & Fiorella (2014) の一次表と一致（coherence 0.86、signalling 0.41、redundancy 0.86、spatial contiguity 1.10、segmenting 0.77）。
- 線幅 2〜3 pt は実務ブログの値。Okabe&Ito08 の「線を太く・記号を大きく」と併記して使う。
