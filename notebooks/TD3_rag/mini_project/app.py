import os
from flask import Flask, request, render_template_string
import chromadb
from sentence_transformers import SentenceTransformer
import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5"

client = anthropic.Anthropic()

embed_model = SentenceTransformer("all-MiniLM-L6-v2")

DB_PATH = "./chroma_db"
chroma_client = chromadb.PersistentClient(path=DB_PATH)
collection = chroma_client.get_collection("catalog")

app = Flask(__name__)


def retrieve(query, k=4):
    q_emb = embed_model.encode(query).tolist()
    res = collection.query(query_embeddings=[q_emb], n_results=k)

    return [
        {
            "name": m["name"],
            "category": m["category"],
            "short_description": m["short_description"],
        }
        for m in res["metadatas"][0]
    ]


def answer_question(question, k=4):
    hits = retrieve(question, k=k)

    context = "\n".join(
        f"- {h['name']} ({h['category']}): {h['short_description']}"
        for h in hits
    )

    prompt = f"""
You are a catalog assistant.

Answer ONLY using the products below.
If the answer is not in the catalog, say "I don't know".

Catalog:
{context}

Question:
{question}
"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    return resp.content[0].text


HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Catalog Chatbot</title>
<style>
  :root {
    --bg: #f4f5f7;
    --card: #ffffff;
    --primary: #e60028;
    --primary-dark: #c40021;
    --text: #1c1c1e;
    --muted: #6b7280;
    --border: #e5e7eb;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: var(--text);
    padding: 24px;
  }
  .card {
    width: 100%;
    max-width: 560px;
    background: var(--card);
    border-radius: 16px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
    padding: 32px;
  }
  .header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 24px;
  }
  .badge {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border-radius: 10px;
    background: var(--primary);
    color: white;
    font-weight: 700;
    font-size: 18px;
  }
  h2 {
    margin: 0;
    font-size: 20px;
  }
  .subtitle {
    margin: 2px 0 0;
    font-size: 13px;
    color: var(--muted);
  }
  form {
    display: flex;
    gap: 8px;
  }
  input[type="text"] {
    flex: 1;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: 10px;
    font-size: 15px;
    outline: none;
    transition: border-color 0.15s ease;
  }
  input[type="text"]:focus {
    border-color: var(--primary);
  }
  button {
    padding: 12px 20px;
    border: none;
    border-radius: 10px;
    background: var(--primary);
    color: white;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s ease;
  }
  button:hover {
    background: var(--primary-dark);
  }
  .answer-block {
    margin-top: 24px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
  }
  .label {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    margin-bottom: 6px;
  }
  .question {
    font-size: 14px;
    color: var(--muted);
    margin-bottom: 14px;
  }
  .answer {
    background: #fafafa;
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
    font-size: 15px;
    line-height: 1.5;
    white-space: pre-wrap;
  }
</style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="badge">F</div>
      <div>
        <h2>Catalog Assistant</h2>
        <p class="subtitle">Ask me anything about the product catalog</p>
      </div>
    </div>

    <form method="post">
      <input type="text" name="q" placeholder="e.g. What headphones do you have?" value="{{ question or '' }}" autofocus>
      <button type="submit">Ask</button>
    </form>

    {% if answer %}
    <div class="answer-block">
      <div class="label">You asked</div>
      <div class="question">{{ question }}</div>
      <div class="label">Answer</div>
      <div class="answer">{{ answer }}</div>
    </div>
    {% endif %}
  </div>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def home():
    answer = None
    question = None
    if request.method == "POST":
        question = request.form["q"]
        answer = answer_question(question)
    return render_template_string(HTML, answer=answer, question=question)


if __name__ == "__main__":
    app.run(debug=True) 