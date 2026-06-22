# -*- coding: utf-8 -*-
"""
AIアシスタント（非定型レイヤー）。
OpenAI gpt-5-mini を使い、全社ダミーデータ（data.CORPUS / ISSUES）を文脈注入したRAG型で応答。
- 回答末尾に【出典】を必ず付ける
- 定型ダッシュボードの数値と矛盾する新数値を作らない
- 打ち手は選択肢を網羅し、評価軸で簡易比較する
"""
import os
from dotenv import load_dotenv

import data as D

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
_client = None
_init_error = None
try:
    from openai import OpenAI
    if os.getenv("OPENAI_API_KEY"):
        _client = OpenAI()
    else:
        _init_error = "OPENAI_API_KEY が未設定です（mock_app/.env を確認してください）。"
except Exception as e:  # pragma: no cover
    _init_error = f"OpenAI クライアント初期化に失敗：{e}"


def _context() -> str:
    """定型レイヤーの結論（論点ランキング）＋RAGコーパスを文脈として組み立てる。"""
    lines = ["【経営サマリ：重要度ランキング（定型ダッシュボードの確定値）】"]
    for it in D.ranked_issues():
        tag = "AIが新検出" if not it["human_known"] else "人が把握済み"
        impact = f"影響額{it['impact']}億円" if it["impact"] else "影響額—（定性）"
        lines.append(
            f"- [{D.severity(it)}|スコア{D.issue_score(it)}|{tag}] {it['title']}"
            f"（{it['segment']}／{impact}／検出元:{it['detected_by']}）：{it['headline']}"
        )
    lines.append("\n【参照可能な社内・公開データ（出典として引用すること）】")
    for c in D.CORPUS:
        lines.append(f"- [{c['id']}|{c['kind']}] {c['source']}：{c['text']}")
    return "\n".join(lines)


SYSTEM_PROMPT = """あなたは阪急阪神ホールディングス（HHグループ）の「AI経営診断アシスタント」です。
経営企画・財務の担当者と経営層を補佐します。以下を厳守してください。

# 役割
- 経営判断サイクル（気づく→見極める→打ち手を選ぶ）の"深掘り・壁打ち"を担う。
- 打ち手を問われたら、選択肢を網羅的に挙げ、収益影響・実行容易性・リスク・時間軸の観点で簡潔に比較する。

# 厳守ルール
- 回答の根拠は、与えられた【経営サマリ】と【参照可能なデータ】の範囲に限る。
- 定型ダッシュボードの数値（スコア・影響額・前提値）と矛盾する新しい数値を創作しない。
- 数値や事実を述べたら、回答の最後に必ず「【出典】」として参照した資料名（CORPUSのsource）を列挙する。
- 範囲外・不明なことは「PoCの公開／マスキングデータの範囲では確認できない」と正直に述べる。
- これはPoCのモックであり、精度保証はなく、出力は人の判断を補助するものだと前提に置く（毎回断る必要はない）。

# 文体
- 簡潔・端的。経営層が短時間で読める分量。要点は箇条書き。過度な前置きや謝辞は不要。
"""


def chat(message: str, history: list, focus: str = None) -> str:
    """応答テキストを返す。
    history … [{'role','content'}, ...]（gradio messages形式）
    focus   … 深掘りモードで選択中の論点名。指定時はその論点に絞って回答させる。
    """
    if _client is None:
        return (f"⚠️ AIアシスタントは現在利用できません。{_init_error or ''}\n"
                "（UIと定型ダッシュボードは引き続きご利用いただけます。）")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": _context()}]
    if focus:  # 深掘りモード：対象論点を中心に、感応度・波及・打ち手まで踏み込ませる
        msgs.append({"role": "system", "content":
                     f"今は『{focus}』に絞った深掘りモードです。この論点を中心に、"
                     "背景・根拠、連結への影響・感応度、他事業への波及、打ち手まで具体的に答えてください。"})
    for m in history:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": message})
    try:
        r = _client.chat.completions.create(model=MODEL, messages=msgs)
        return r.choices[0].message.content.strip()
    except Exception as e:  # pragma: no cover
        return f"⚠️ 応答の生成に失敗しました：{type(e).__name__}: {str(e)[:200]}"
