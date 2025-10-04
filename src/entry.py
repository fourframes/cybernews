import json
from workers import Response, WorkerEntrypoint
from js import console, fetch, Object, Headers

PERPLEXITY_API_URL = 'https://api.perplexity.ai/chat/completions'
NEWS_SOURCES = [
    "Heise Security", "Krebs on Security", "The Hacker News",
    "ZDNet Cybersecurity", "SecurityWeek", "BleepingComputer", "Cybersecurity Insiders"
]
DEFAULT_MAX_NEWS_ITEMS = 5


class Default(WorkerEntrypoint):
    async def fetch(self, request, env):
        url = request.url
        if url.endswith("/test-run"):
            if self.env.TESTRUN:
                console.log("Manual test run triggered")
                await self.run_worker(env)
                return Response("Test run executed!", status=200)
        return Response("OK", status=200)

    async def scheduled(self, event, env, ctx):
        console.log("Scheduled event triggered")
        # Run asynchronously without blocking scheduled event
        await self.run_worker(env)
        return Response("Run executed!", status=200)

    async def run_worker(self, env):
        api_key = self.env.SECRET_PERPLEXITY_API_KEY
        slack_url = self.env.SECRET_SLACK_WEBHOOK_URL
        max_items = int(getattr(self.env, "MAX_NEWS_ITEMS", DEFAULT_MAX_NEWS_ITEMS))

        try:
            news = await self.fetch_cybersecurity_news(api_key , max_items)
            if not news:
                console.log("No news items returned from Perplexity.")
                return
            await self.post_news_to_slack(slack_url, news)
            console.log(f"Posted {len(news)} news items to Slack.")
        except Exception as e:
            console.error("Worker error:", str(e))

    async def fetch_cybersecurity_news(self, api_key, max_items):
        prompt = f"""
Bitte die aktuellen, relevanten Cybersecurity-Nachrichten der letzten beiden Arbeitstage (heute und letzter Arbeitstag) für Unternehmen in der DACH-Region (Deutschland, Österreich, Schweiz) bereitstellen. Fokus liegt auf bedeutenden Datenpannen, Hacks und Sicherheitslücken mit hoher Relevanz für die Region. Bitte bevorzuge Nachrichtenquellen aus dem DACH-Raum, aber internationale Quellen sind ebenfalls akzeptabel, wenn sie für die Region relevant sind. Bitte bevorzuge Nachrichtenquellen, die eher Nachrichtenartikel als Beiträge von Herstellern sind - außer es handelt sich um Sicherheitslücken, welche Hersteller selber publizieren.
Nutze Quellen ähnlich wie: {', '.join(NEWS_SOURCES)}.
Antworte ausschließlich mit einem JSON-Array von Objekten, ohne zusätzlichen Text oder Markdown.
Jedes Objekt enthält folgende Felder:

- headline (String)
- excerpt (String)
- source_url (String)

[
  {{
    "headline": "Titel der Nachricht",
    "excerpt": "Kurze Zusammenfassung der Nachricht",
    "source_url": "https://link.zum/artikel"
  }},
  ...
]

Beschränke die Antwort auf {max_items} Einträge.
"""

        body = {
            "model": "sonar-pro",
            "messages": [
                {"role": "system", "content": "Sie sind ein hilfreicher Assistent, der Cybersicherheitsnachrichten für DACH-Unternehmen zusammenfasst."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 5000,
            "temperature": 0.7,
        }

        # Create Headers instance and set headers
        headers = Headers.new()
        headers.set("Content-Type", "application/json")
        headers.set("Authorization", f"Bearer {api_key}")

        # JSON body as string
        body_str = json.dumps(body)

        # Build options object
        options = Object.fromEntries([
            ["method", "POST"],
            ["headers", headers],
            ["body", body_str]
        ])

        resp = await fetch(PERPLEXITY_API_URL, options)
       
        
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"Perplexity API Error: {resp.status} {resp.statusText}: {text}")

        data = await resp.json()
        content = None
        try:
            data_py = data.to_py()  # Convert JS object to Python native
            content = data_py['choices'][0]['message']['content']
            console.log("Raw Perplexity API content:", content)
            news_items = json.loads(content)
            return news_items
        except Exception as e:
            console.error("Error parsing content:", e)
            console.error("Content that failed:", content if content else data)
            raise Exception("Failed to parse Perplexity API response") from e



    async def post_news_to_slack(self, webhook_url: str, news_items):
        headers = Headers.new()
        headers.set("Content-Type", "application/json")

        # Build a single message block
        blocks = []
        for item in news_items:
            blocks.append(f"*{item['headline']}*\n{item['excerpt']}\n<{item['source_url']}|Read more>")
        message_text = "\n\n".join(blocks)

        message = {
            "text": message_text
        }
        body = json.dumps(message)

        options = Object.fromEntries([
            ["method", "POST"],
            ["headers", headers],
            ["body", body]
        ])

        resp = await fetch(webhook_url, options)
        if resp.status != 200:
            raise Exception(f"Slack webhook error: {resp.status} {resp.statusText}")
