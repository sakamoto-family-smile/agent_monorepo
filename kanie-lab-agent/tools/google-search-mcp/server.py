import os
from fastmcp import FastMCP

mcp = FastMCP("google-search")


@mcp.tool()
async def google_search(query: str, num_results: int = 5) -> str:
    """Google検索を使って最新情報を取得する"""
    try:
        from google import genai
        from google.genai import types

        project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
        if not project:
            return "エラー: GOOGLE_CLOUD_PROJECT が設定されていません"

        client = genai.Client(
            vertexai=True,
            project=project,
            location="global"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"以下について検索して情報をまとめてください: {query}",
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1,
            )
        )

        results = []
        metadata = response.candidates[0].grounding_metadata
        if metadata and metadata.grounding_chunks:
            for chunk in metadata.grounding_chunks:
                if chunk.web:
                    results.append({
                        "title": chunk.web.title,
                        "url": chunk.web.uri,
                    })

        source_list = "\n".join(
            [f"- [{r['title']}]({r['url']})" for r in results[:num_results]]
        )
        return f"## 検索結果\n\n{response.text}\n\n## ソース\n{source_list}"

    except Exception as e:
        return f"Google検索エラー: {str(e)}"


@mcp.tool()
async def google_search_ja(query: str) -> str:
    """日本語に最適化したGoogle検索"""
    return await google_search(f"{query} lang:ja", num_results=5)


if __name__ == "__main__":
    import sys
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport == "streamable-http":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 3001
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")
