#!/usr/bin/env python3
"""2つのPDFを結合するスクリプト

使い方:
    python merge_pdf.py input1.pdf input2.pdf output.pdf
"""
import argparse
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def merge_pdfs(pdf_paths, output_path):
    """複数のPDFを順番に結合して1つのPDFとして書き出す。"""
    writer = PdfWriter()

    for pdf_path in pdf_paths:
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"ファイルが見つかりません: {pdf_path}")

        reader = PdfReader(pdf_path)

        # 暗号化されている場合は空パスワードでの復号を試みる
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as e:
                raise ValueError(f"暗号化PDFを開けません: {pdf_path} ({e})")

        for page in reader.pages:
            writer.add_page(page)

        print(f"  追加: {path.name} ({len(reader.pages)} ページ)")

    with open(output_path, "wb") as f:
        writer.write(f)

    total = len(writer.pages)
    print(f"完了: {output_path} ({total} ページ)")
    return total


def main():
    parser = argparse.ArgumentParser(description="2つ以上のPDFを結合します")
    parser.add_argument("inputs", nargs="+", help="入力PDF（2つ以上）")
    parser.add_argument("output", help="出力PDFのパス")
    args = parser.parse_args()

    # 最後の引数を output、それ以外を inputs として扱う
    # argparse の都合上、ここで分離する
    inputs = args.inputs
    output = args.output

    if len(inputs) < 2:
        parser.error("入力PDFは2つ以上指定してください")

    try:
        merge_pdfs(inputs, output)
    except (FileNotFoundError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
