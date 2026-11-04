"""L4: フィードの記事から「どのパッケージのどの版が危ないか」を LLM で抜き出す (extractor サービス)。

extractor コンテナは DB を持たない。intel が data/llm/in/ に置いた記事を読み、結果を data/llm/out/ に書くだけ。
LLM の出力は信用せず、intel が原文と突き合わせてから取り込む (src/intel/extraction.py)。
"""
