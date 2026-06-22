# -*- coding: utf-8 -*-
"""
HHグループ（阪急阪神HD）AI経営診断PoC ｜ モックアプリ（エントリポイント）

画面は2レイヤー構成：
  定型レイヤー  … 経営サマリ（結論ファースト）／モニタリング／診断（毎回同じ固定フォーマット）
  非定型レイヤー … AIアシスタント（OpenAI gpt-5-mini・RAG・出典付き）

役割分担：
  data.py      … 数値・論点・コーパス等のダミーデータと算出ロジック
  assistant.py … AIアシスタントの応答（OpenAI呼び出し）
  app.py       … 上記を画面に組み立てる（このファイル）
※ 表示値はすべて架空のダミー。精度保証なし（PoC前提）。
"""
import os
import sys

# Windows の ProactorEventLoop は Gradio の非同期処理と衝突してフリーズする
# SelectorEventLoop に戻すことで回避
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pandas as pd
import plotly.graph_objects as go
import gradio as gr

# どこから起動しても data/assistant を読めるよう、このファイルの場所をパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D
import assistant as A

# ===========================================================================
# 1. ブランド・パレット（阪急マルーン）と共通スタイル
# ===========================================================================
MAROON = "#6E2C3E"       # 標準（強調・インタラクティブ）
MAROON_DARK = "#4A1C27"  # 濃（ヘッダー・見出し）
INK = "#211C1D"          # 文字（温チャコール）
MUTE = "#8A8079"         # 補助グレー
NEUTRAL = "#C9C0B6"      # グラフの控えめ色
SEV = {"高": "#B23A2E", "中": "#C0922F", "低": "#4F7A6A"}  # 深刻度の色


def style_fig(fig, height, title):
    """全グラフ共通のスタイル（フォント・余白・配色）を適用して返す。"""
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=MAROON_DARK)),
        height=height, template="plotly_white",
        font=dict(family="Noto Sans JP, Meiryo, Yu Gothic, sans-serif", color=INK, size=13),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=48, b=24, l=12, r=16),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor="#ECE6DF", zeroline=False),
    )
    return fig


def flag(pct):
    """乖離率が閾値を超えたら『要確認』、範囲内は『—』を返す（表の判定列）。"""
    return "▲ 要確認" if abs(pct) > D.THRESHOLD_PCT else "—"


# ===========================================================================
# 2. 定型レイヤー：モニタリングの表・グラフ
# ===========================================================================
def view_plan_actual():
    """計画 vs 実績：乖離一覧（表）と、事業利益の乖離率（棒グラフ）。"""
    rows = []
    for seg, kpi, plan, act in D.PLAN_ACTUAL:
        pct = (act - plan) / plan * 100
        rows.append([seg, kpi, f"{plan:,}", f"{act:,}", f"{act-plan:+,}", f"{pct:+.1f}%", flag(pct)])
    df = pd.DataFrame(rows, columns=["セグメント", "KPI", "計画", "実績", "差分", "乖離率", ""])

    profit = [(seg, act / plan * 100 - 100) for seg, kpi, plan, act in D.PLAN_ACTUAL if kpi == "事業利益"]
    vals = [v for _, v in profit]
    fig = go.Figure(go.Bar(
        x=[s for s, _ in profit], y=vals,
        marker_color=[SEV["高"] if abs(v) > D.THRESHOLD_PCT else MAROON for v in vals],
        text=[f"{v:+.1f}%" for v in vals], textposition="outside", textfont=dict(color=INK)))
    fig.add_hline(y=D.THRESHOLD_PCT, line_dash="dot", line_color=NEUTRAL)
    fig.add_hline(y=-D.THRESHOLD_PCT, line_dash="dot", line_color=NEUTRAL)
    return df, style_fig(fig, 340, "セグメント別 事業利益　計画対比（乖離率）")


def view_assumption():
    """前提 vs 外部環境：中計前提値と直近実勢の乖離一覧（表）。"""
    rows = []
    for name, base, now, unit, src in D.ASSUMPTION_EXTERNAL:
        pct = (now - base) / base * 100
        rows.append([name, f"{base}{unit}", f"{now}{unit}", f"{pct:+.1f}%", flag(pct), src])
    return pd.DataFrame(rows, columns=["前提項目", "中計前提", "直近実勢", "乖離率", "", "外部指標 出所"])


def view_report_changes():
    """報告変化点：同一テーマの過去/直近の記述差分（表）。"""
    rows = [[r["テーマ"], r["過去(2025/Q2)"], r["直近(2026/Q1)"], r["変化点(AI抽出)"], r["深刻度"]]
            for r in D.REPORT_CHANGES]
    return pd.DataFrame(rows, columns=["テーマ", "過去の記述", "直近の記述", "変化点（AI抽出）", "深刻度"])


def view_coverage():
    """議論カバレッジ：アジェンダと議事録を突合し未議論テーマを検出（表）。"""
    rows = [[item, kind, cnt, last, "▲ 議論漏れ" if cnt < D.UNDISCUSSED_N else "—"]
            for item, cnt, last, kind in D.AGENDA_COVERAGE]
    return pd.DataFrame(rows, columns=["アジェンダ項目", "区分", "直近6回の言及", "最終言及", ""])


# ===========================================================================
# 3. 定型レイヤー：診断の表・グラフ
# ===========================================================================
def view_priority():
    """重要度診断：論点を3軸スコアで順位付け（表＋横棒グラフ）。"""
    items = D.ranked_issues()
    rows = [[i + 1, D.severity(it), it["title"], it["impact"] or "—", it["urgency"], it["cross"],
             D.issue_score(it)] for i, it in enumerate(items)]
    df = pd.DataFrame(rows, columns=["順位", "深刻度", "論点", "影響額(億円)", "緊急度", "横断性", "重要度スコア"])

    fig = go.Figure(go.Bar(
        x=[D.issue_score(it) for it in items][::-1], y=[it["title"] for it in items][::-1],
        orientation="h", marker_color=MAROON,
        text=[D.issue_score(it) for it in items][::-1], textposition="outside", textfont=dict(color=INK)))
    return df, style_fig(fig, 360, "重要度スコア（影響額×0.5 ＋ 緊急度×0.3 ＋ 横断性×0.2）")


def view_sensitivity():
    """感応度診断：前提±10%が連結利益に与える影響（表＋トルネード）。"""
    rows = [[n, f"{lo:+d}", f"{hi:+d}", max(abs(lo), abs(hi))] for n, lo, hi in D.SENSITIVITY]
    df = pd.DataFrame(rows, columns=[f"前提（±{D.SENS_SHOCK_PCT}%）", "-10%時(億円)", "+10%時(億円)", "感応度幅"])

    order = sorted(D.SENSITIVITY, key=lambda r: max(abs(r[1]), abs(r[2])))  # 感応度の小→大で並べる
    fig = go.Figure()
    fig.add_trace(go.Bar(y=[r[0] for r in order], x=[r[1] for r in order], orientation="h",
                         name=f"-{D.SENS_SHOCK_PCT}%", marker_color=NEUTRAL))
    fig.add_trace(go.Bar(y=[r[0] for r in order], x=[r[2] for r in order], orientation="h",
                         name=f"+{D.SENS_SHOCK_PCT}%", marker_color=MAROON))
    fig.update_layout(barmode="relative", legend=dict(orientation="h", y=1.12, x=0))
    df = df.sort_values("感応度幅", ascending=False).reset_index(drop=True)
    return df, style_fig(fig, 380, f"前提変化が連結事業利益（ベース{D.BASE_PROFIT:,}億円）に与える影響")


def view_propagation(factor):
    """波及構造診断：要因→事業→KPIの連鎖（表＋サンキー図）。"""
    chain = D.PROPAGATION[factor]
    df = pd.DataFrame([[factor, seg, mech, kpi, st] for seg, mech, kpi, st in chain],
                      columns=["起点要因", "波及先 事業", "波及メカニズム", "影響KPI", "影響度"])

    segs = [c[0] for c in chain]
    kpis = list(dict.fromkeys(c[2] for c in chain))  # 重複を除いた影響KPI
    labels = [factor] + segs + kpis
    idx = {label: i for i, label in enumerate(labels)}
    weight = {"強": 3, "中": 2, "弱": 1}
    src, tgt, val = [], [], []
    for seg, mech, kpi, st in chain:  # 要因→事業、事業→KPI の2本のリンクを張る
        src += [idx[factor], idx[seg]]
        tgt += [idx[seg], idx[kpi]]
        val += [weight[st], weight[st]]
    fig = go.Figure(go.Sankey(
        node=dict(label=labels, pad=20, thickness=16, line=dict(width=0),
                  color=[MAROON_DARK] + [MAROON] * len(segs) + [NEUTRAL] * len(kpis)),
        link=dict(source=src, target=tgt, value=val, color="rgba(110,44,62,0.18)")))
    return df, style_fig(fig, 380, f"波及構造：{factor} → 事業 → KPI")


def view_evidence():
    """根拠トレース：アシスタントが参照する社内・公開データの出典一覧（表）。"""
    return pd.DataFrame([[c["source"], c["kind"], c["text"]] for c in D.CORPUS],
                        columns=["参照元（出典）", "区分", "要旨"])


def decision_log_df(rows):
    """意思決定ログの行リストを表に整形（列名を一箇所に集約）。"""
    return pd.DataFrame(rows, columns=["日時", "シナリオ", "選定した選択肢", "選定理由", "起票者"])


# ===========================================================================
# 4. 経営サマリ：論点カード（HTML）と画面パーツ
# ===========================================================================
def card_html(it):
    """1論点を高級感のあるカードHTMLに整形（深刻度ドット・タグ・スコア・要旨）。"""
    color = SEV[D.severity(it)]
    if it["human_known"]:
        tag, bg, fg = "人が把握済み", "#F0ECE6", MUTE
    else:  # AIが新たに検出した論点は色で強調（命題Aの価値づけ）
        tag, bg, fg = "AIが新検出", "#F3E7EA", MAROON
    impact = f"{it['impact']:,} 億円" if it["impact"] else "定性"
    return f"""
<div class='hh-card-inner'>
  <div class='hh-card-top'>
    <span class='hh-dot' style='background:{color}'></span>
    <span class='hh-seg'>{it['segment']}</span>
    <span class='hh-tag' style='background:{bg};color:{fg}'>{tag}</span>
    <span class='hh-score'>{D.issue_score(it)}</span>
  </div>
  <div class='hh-title'>{it['title']}</div>
  <div class='hh-head'>{it['headline']}</div>
  <div class='hh-meta'>影響額 {impact}　·　検出元 {it['detected_by']}</div>
</div>
"""


def caption(text):
    """各画面の1行ガイド（薄いグレーの小さな説明）。文字を増やしすぎない用。"""
    return gr.HTML(f"<div class='hh-caption'>{text}</div>")


def section(text):
    """画面内セクションの見出し（マルーン）。"""
    return gr.HTML(f"<div class='hh-section'>{text}</div>")


# ===========================================================================
# 5. デザイン（CSS）とヘッダー
# ===========================================================================
CSS = """
/* Google Fonts はネットワーク制限がある環境でブロックするため削除。システムフォントで代替 */
:root { --hh-maroon:#6E2C3E; --hh-maroon-d:#4A1C27; --hh-ivory:#FAF8F5; --hh-ink:#211C1D; }
/* ダークモード追従を打ち消し、常にライト（アイボリー）基調にするためGradio変数を上書き */
:root, .dark {
  --body-background-fill:#FAF8F5 !important; --background-fill-primary:#FFFFFF !important;
  --background-fill-secondary:#F3EFEA !important; --block-background-fill:#FFFFFF !important;
  --border-color-primary:#ECE6DF !important; --body-text-color:#211C1D !important;
  --body-text-color-subdued:#8A8079 !important; --block-label-text-color:#5C534E !important;
  --block-title-text-color:#4A1C27 !important; --input-background-fill:#FFFFFF !important;
  --table-odd-background-fill:#FFFFFF !important; --table-even-background-fill:#FAF8F5 !important;
  --neutral-950:#211C1D !important; color-scheme:light !important;
  /* ラジオ／チェックボックスの選択肢ピルもライト＋マルーンに */
  --checkbox-label-background-fill:#F3EFEA !important;
  --checkbox-label-background-fill-selected:#F3E7EA !important;
  --checkbox-label-text-color:#5C534E !important;
  --checkbox-label-text-color-selected:#4A1C27 !important;
  --checkbox-background-color-selected:#6E2C3E !important;
  --checkbox-border-color-selected:#6E2C3E !important;
}
input[type=radio], input[type=checkbox] { accent-color:#6E2C3E !important; }
/* width:100% が無いとコンテナが中身の幅に縮み、タブごとに全体幅が変わる。全幅固定で統一 */
.gradio-container { background:var(--hh-ivory) !important; font-family:'Noto Sans JP','Meiryo','Yu Gothic',sans-serif !important;
  color:var(--hh-ink); width:100% !important; max-width:1180px !important; margin:0 auto !important; }
/* Gradioのfillableレイアウトが内側コンテンツを狭めるのを解除し、全タブを全幅で統一 */
.gradio-container .main, .gradio-container .wrap, .gradio-container .contain,
.gradio-container .fillable, .gradio-container > .main { max-width:100% !important; width:100% !important; }
footer { display:none !important; }
/* ヘッダー */
.hh-header { padding:26px 4px 14px; border-bottom:1px solid #ECE6DF; margin-bottom:8px; }
.hh-brand { display:flex; align-items:center; gap:14px; }
.hh-brandbar { width:6px; height:34px; background:var(--hh-maroon); border-radius:3px; }
.hh-brand h1 { font-size:21px; font-weight:500; letter-spacing:.06em; color:var(--hh-maroon-d); margin:0; }
.hh-brand .sub { font-size:12px; color:#8A8079; letter-spacing:.04em; margin-top:3px; font-weight:300; }
.hh-caption { color:#8A8079; font-size:12.5px; font-weight:300; letter-spacing:.02em; margin:2px 2px 10px; }
.hh-section { color:var(--hh-maroon-d); font-size:15px; font-weight:500; letter-spacing:.04em; margin:6px 2px 2px; }
/* タブ（バー全体を全幅に広げ、各タブを均等割りで統一） */
.tab-wrapper, .tab-container { width:100% !important; }
[role=tablist] { display:flex !important; width:100% !important; }
/* min-width:0 が無いと長いタブが文字幅まで縮まず不均等になる。これで必ず均等割り */
[role=tablist] button[role=tab] { flex:1 1 0 !important; min-width:0 !important; white-space:nowrap !important;
  justify-content:center !important; text-align:center !important; }
button[role=tab][aria-selected=true] { color:var(--hh-maroon-d) !important; font-weight:500 !important;
  border-bottom:2px solid var(--hh-maroon) !important; }
button[role=tab] { color:#8A8079 !important; font-weight:400 !important; letter-spacing:.03em; }
/* カード */
.hh-card { background:#fff !important; border:1px solid #ECE6DF !important; border-radius:14px !important;
  padding:0 !important; box-shadow:0 1px 2px rgba(74,28,39,.04) !important; }
.hh-card-inner { padding:16px 18px 14px; }
.hh-card-top { display:flex; align-items:center; gap:9px; margin-bottom:8px; }
.hh-dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
.hh-seg { font-size:12px; color:#8A8079; letter-spacing:.04em; }
.hh-tag { font-size:11px; padding:2px 9px; border-radius:10px; letter-spacing:.03em; }
.hh-score { margin-left:auto; font-size:22px; font-weight:700; color:var(--hh-maroon-d); font-variant-numeric:tabular-nums; }
.hh-title { font-size:15.5px; font-weight:500; color:var(--hh-ink); line-height:1.5; margin-bottom:4px; }
.hh-head { font-size:13px; color:#5C534E; font-weight:300; line-height:1.6; margin-bottom:8px; }
.hh-meta { font-size:11.5px; color:#9A8F86; letter-spacing:.02em; }
/* 深掘りボタン（カード内のテキストリンク風）※elem_classesはbutton自身に付く */
.hh-deep, .hh-deep button { background:transparent !important; color:var(--hh-maroon) !important;
  border:none !important; box-shadow:none !important; font-size:12.5px !important; font-weight:500 !important;
  padding:0 18px 14px !important; text-align:left !important; letter-spacing:.03em; }
.hh-deep:hover { color:var(--hh-maroon-d) !important; }
/* プライマリボタン（送信・記録） */
.hh-primary, .hh-primary button { background:var(--hh-maroon) !important; color:#fff !important;
  border:none !important; font-weight:500 !important; letter-spacing:.04em; }
.hh-primary:hover { background:var(--hh-maroon-d) !important; }
/* サジェスト質問（丸いチップ）※elem_classesはRow（親）に付くので子孫セレクタ */
.hh-sug button { background:#F3EFEA !important; color:#5C534E !important; border:1px solid #ECE6DF !important;
  font-size:12.5px !important; font-weight:400 !important; border-radius:18px !important; box-shadow:none !important; }
.hh-sug button:hover { border-color:var(--hh-maroon) !important; color:var(--hh-maroon-d) !important; }
/* テーブル（罫線を薄く） */
table { border:none !important; }
thead th { background:#F3EFEA !important; color:#5C534E !important; font-weight:500 !important;
  border:none !important; border-bottom:1px solid #E4DCD2 !important; }
tbody td { border:none !important; border-bottom:1px solid #F1EBE3 !important; color:var(--hh-ink) !important; }
"""

HEADER = """
<div class='hh-header'><div class='hh-brand'>
  <div class='hh-brandbar'></div>
  <div><h1>HHグループ　AI経営診断</h1>
  <div class='sub'>PoC モック　·　気づく → 見極める → 打ち手を選ぶ　·　表示値はすべて架空のダミー</div></div>
</div></div>
"""


# ===========================================================================
# 6. 画面組み立て（UI）
# ===========================================================================
# AIアシスタントの2モード（ラベルが画面の選択肢にもなる）
MODE_GENERAL = "一般質問（読み込み済みデータ全体）"
MODE_DEEP = "観点を深掘り（論点を選んで掘り下げ）"


def respond(message, history, mode, topic):
    """ユーザー発言を履歴に足し、AIアシスタントの応答を返す（入力欄はクリア）。
    深掘りモードのときは選択中の論点(topic)に絞って回答させる。"""
    if not message or not message.strip():
        return history, ""
    history = (history or []) + [{"role": "user", "content": message}]
    focus = topic if mode == MODE_DEEP else None
    reply = A.chat(message, history[:-1], focus=focus)
    return history + [{"role": "assistant", "content": reply}], ""


def switch_mode(mode):
    """モード切替に応じて、論点ドロップダウンと2種のサジェスト行の表示を切り替える。"""
    deep = (mode == MODE_DEEP)
    return (gr.update(visible=deep),        # 論点ドロップダウン
            gr.update(visible=not deep),    # 一般サジェスト行
            gr.update(visible=deep))        # 深掘りサジェスト行


def add_decision(rows, option, reason, who):
    """意思決定ログに1行追加（日時はモックの固定値）。"""
    new = ["2026/06/19", "金利上昇", option or "(未選択)", reason or "(理由未記入)", who or "—"]
    rows = [new] + list(rows)
    return rows, decision_log_df(rows)


# fill_width=True：既定の「コンテンツ幅に合わせて縮む」挙動をやめ、常に全幅で描画する。
# これでタブを切り替えても全体幅が一定になり、タブバーの幅も揃う。
with gr.Blocks(title="HHグループ AI経営診断PoC", fill_width=True) as demo:
    gr.HTML(HEADER)

    with gr.Tabs() as main_tabs:
        # ---- 経営サマリ（結論ファースト）----
        with gr.Tab("経営サマリ", id="summary"):
            caption("いま経営会議に出すべき論点を、重要度スコア順に。カード下の「深掘り」からAIアシスタントへ。")
            # 論点カードを2列グリッドで並べる。各カードの深掘りボタンは後で一括バインドする
            #（チャット入力欄がこの後のタブで定義されるため、ここでは(ボタン, 論点)を控えておく）
            deep_buttons = []
            issues = D.ranked_issues()
            for i in range(0, len(issues), 2):
                with gr.Row(equal_height=True):
                    for it in issues[i:i + 2]:
                        with gr.Column():
                            with gr.Group(elem_classes="hh-card"):
                                gr.HTML(card_html(it))
                                deep_buttons.append((gr.Button("深掘りする →", elem_classes="hh-deep"), it))

        # ---- モニタリング（①気づく）----
        with gr.Tab("モニタリング", id="monitor"):
            section("① 気づく　計画・前提・報告・議論の“ズレ／変化”を固定フォーマットで自動検知")
            with gr.Tabs():
                with gr.Tab("計画 vs 実績"):
                    caption("セグメント別KPIの計画対比。乖離率 ±8% 超を要確認として強調。")
                    df, fig = view_plan_actual()
                    gr.Plot(fig)
                    gr.Dataframe(df, interactive=False, elem_classes="hh-card")
                with gr.Tab("前提 vs 外部環境"):
                    caption("中計の主要前提値と、公開外部指標の直近実勢との乖離。")
                    gr.Dataframe(view_assumption(), wrap=True, interactive=False, elem_classes="hh-card")
                with gr.Tab("報告変化点"):
                    caption("同一テーマの過去・直近の記述差分。トーンの変化をLLMが抽出。")
                    gr.Dataframe(view_report_changes(), wrap=True, interactive=False, elem_classes="hh-card")
                with gr.Tab("議論カバレッジ"):
                    caption("年間アジェンダと直近議事録の突合。一定回数 未議論のテーマを検出。")
                    gr.Dataframe(view_coverage(), interactive=False, elem_classes="hh-card")

        # ---- 診断（②見極める）----
        with gr.Tab("診断", id="diagnose"):
            section("② 見極める　多数のズレから“どれが重要か・どこに効くか”を評価")
            with gr.Tabs():
                with gr.Tab("重要度"):
                    caption("影響額・緊急度・横断性の3軸（固定式）でスコアリングし、順位付け。")
                    df, fig = view_priority()
                    gr.Plot(fig)
                    gr.Dataframe(df, wrap=True, interactive=False, elem_classes="hh-card")
                with gr.Tab("感応度"):
                    caption("主要前提を ±10% 動かしたときの連結事業利益への影響（トルネード）。")
                    df, fig = view_sensitivity()
                    gr.Plot(fig)
                    gr.Dataframe(df, interactive=False, elem_classes="hh-card")
                with gr.Tab("波及構造"):
                    caption("起点となる要因から、影響を受ける事業・KPIの連鎖を構造化。")
                    factor = gr.Dropdown(list(D.PROPAGATION.keys()), value="金利上昇", label="起点要因")
                    prop_plot = gr.Plot()
                    prop_table = gr.Dataframe(wrap=True, interactive=False, elem_classes="hh-card")
                    # 要因を選ぶたび／初回ロード時に波及図と表を更新（戻り値は df, fig の順）
                    factor.change(view_propagation, factor, [prop_table, prop_plot])
                    demo.load(view_propagation, factor, [prop_table, prop_plot])
                with gr.Tab("根拠トレース"):
                    caption("各診断が参照した社内・公開データの出典一覧。横断要件として全機能に付与。")
                    gr.Dataframe(view_evidence(), wrap=True, interactive=False, elem_classes="hh-card")

        # ---- AIアシスタント（③深掘り・打ち手）----
        with gr.Tab("AIアシスタント", id="assistant"):
            section("③ 深掘り・打ち手　全社データを参照し、出典付きで壁打ち（OpenAI gpt-5-mini）")
            caption("打ち手は選択肢を網羅し、収益影響・実行容易性・リスク・時間軸で比較。回答には出典を併記。")

            # モード切替：一般質問 か、論点を選んでの深掘り か
            with gr.Row():
                mode = gr.Radio([MODE_GENERAL, MODE_DEEP], value=MODE_GENERAL,
                                label="モード", scale=3)
                topic = gr.Dropdown([it["title"] for it in D.ranked_issues()],
                                    value=D.ranked_issues()[0]["title"],
                                    label="深掘りする論点", visible=False, scale=2)

            chatbot = gr.Chatbot(height=380, show_label=False, elem_classes="hh-card", type="messages")
            # サジェストは2種。モードに応じてどちらか一方を表示
            with gr.Row(elem_classes="hh-sug") as general_row:
                general_sugs = [gr.Button(q, size="sm") for q in D.GENERAL_QUESTIONS]
            with gr.Row(elem_classes="hh-sug", visible=False) as deep_row:
                deep_sugs = [gr.Button(q, size="sm") for q in D.DEEP_QUESTIONS]
            with gr.Row():
                chat_input = gr.Textbox(placeholder="経営課題について質問する…", show_label=False,
                                        scale=8, container=False, lines=1)
                send = gr.Button("送信", scale=1, elem_classes="hh-primary")

            # モード切替で論点ドロップダウン／サジェスト行の表示を更新
            mode.change(switch_mode, mode, [topic, general_row, deep_row])

            # 送信（ボタン／Enter）と、サジェスト押下（入力欄に流し込んでから送信）
            chat_io = ([chat_input, chatbot, mode, topic], [chatbot, chat_input])
            send.click(respond, *chat_io)
            chat_input.submit(respond, *chat_io)
            for btn, q in zip(general_sugs + deep_sugs, D.GENERAL_QUESTIONS + D.DEEP_QUESTIONS):
                btn.click(lambda q=q: q, None, chat_input).then(respond, *chat_io)

            section("意思決定ログ")
            caption("壁打ちで定まった選定と理由を記録・蓄積（PoCでは簡易ストア）。")
            log_state = gr.State(list(D.DECISION_LOG))
            log_table = gr.Dataframe(decision_log_df(D.DECISION_LOG), wrap=True,
                                     interactive=False, elem_classes="hh-card")
            with gr.Row():
                opt = gr.Dropdown([o["選択肢"] for o in D.OPTIONS_COMPARE], label="選定した選択肢", scale=2)
                reason = gr.Textbox(label="選定理由", scale=3)
                who = gr.Textbox(label="起票者", value="経営企画", scale=1)
            gr.Button("意思決定ログに記録", elem_classes="hh-primary").click(
                add_decision, [log_state, opt, reason, who], [log_state, log_table])

        # ---- 前提・ゴール ----
        with gr.Tab("前提・ゴール", id="about"):
            gr.Markdown("""
#### 成果ゴール
2026年9月末までに、AIによる経営診断（気づく・見極める・打ち手を選ぶ）が「有効かつ実現可能」であることを、
公開・マスキングデータの範囲で実証し、本格導入に進むかを判断できる状態をつくる。

#### 成功をどう判断するか（命題）
| 命題 | 成功の考え方 |
|---|---|
| A：モニタリング（気づく） | 人が手作業で見つける乖離・変化をAIが概ね捕捉し、人が見落とした重要な乖離を新たに検出できる |
| B：診断（見極める） | AIが示す重要論点の多くを担当者が「会議に出す価値あり」と認め、感応度・波及の妥当性を財務担当が概ね認める |
| C：対策提示（打ち手を選ぶ） | 代表シナリオで、人が見落としていた／比較できていなかった対応策の観点をAIが提示できる |

#### 前提・制約
- 完成品ではなく「使えそうか」を判断する材料。本番品質・例外処理・全社展開は対象外
- UIは簡素（本モック）。機能ロジックの有効性で評価いただく
- 精度保証なし（誤検知・抜けは前提。AI出力は人の判断を補助）
- データはマスキング／公開情報前提（本モックの数値はすべて架空のダミー）
""")

    # 経営サマリの「深掘り」→ 深掘りモードに切替え、その論点を選択してAIアシスタントへ遷移
    def open_assistant(it):
        q = f"「{it['title']}」について、なぜ重要か・連結への影響・打ち手の選択肢を比較して教えて。"
        return (gr.update(selected="assistant"), MODE_DEEP,
                gr.update(value=it["title"], visible=True),  # 論点を選択して表示
                gr.update(visible=False), gr.update(visible=True), q)  # 一般→隠す／深掘り→出す
    for btn, it in deep_buttons:
        btn.click(lambda it=it: open_assistant(it), None,
                  [main_tabs, mode, topic, general_row, deep_row, chat_input])


if __name__ == "__main__":
    demo.launch(css=CSS, theme=gr.themes.Base(font=[gr.themes.GoogleFont("Noto Sans JP"), "sans-serif"]),
                server_port=int(os.getenv("GRADIO_SERVER_PORT", "7862")), inbrowser=False)
