import json
import re
from html import unescape
from workers import Response, WorkerEntrypoint
from js import console, fetch, Object, Headers

PERPLEXITY_SEARCH_API_URL = 'https://api.perplexity.ai/search'
PERPLEXITY_CHAT_API_URL = 'https://api.perplexity.ai/chat/completions'
DEFAULT_MAX_NEWS_ITEMS = 5

def clean_excerpt(raw_excerpt):
    # Unescape HTML entities
    text = unescape(raw_excerpt)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove shortcodes or specific patterns like [wpml_language_switcher]{...}
    text = re.sub(r'\[wpml_language_switcher\].*?\[/wpml_language_switcher\]', '', text, flags=re.DOTALL)
    # Remove any leftover curly brace templating such as {% ... %}
    text = re.sub(r'\{[%|{].*?[%|}]\}', '', text, flags=re.DOTALL)
    # Normalize newlines and whitespace
    text = re.sub(r'\n+', '\n', text).strip()
    # Remove reference markers like [1], [2], etc.
    text = re.sub(r'\[\d+\]', '', text)  
    return text

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
        await self.run_worker(env)
        return Response("Run executed!", status=200)

    async def run_worker(self, env):
        api_key = self.env.SECRET_PERPLEXITY_API_KEY
        slack_url = self.env.SECRET_SLACK_WEBHOOK_URL
        max_items = int(getattr(self.env, "MAX_NEWS_ITEMS", DEFAULT_MAX_NEWS_ITEMS))

        try:
            news = await self.fetch_cybersecurity_news(api_key, max_items)
            if not news:
                console.log("No news items returned from Perplexity Search API.")
                return

            summarized_news = []
            for item in news:
                clean_text = clean_excerpt(item['excerpt'])
                summary = await self.generate_summary(api_key, item['headline'], clean_text)
                summarized_news.append({
                    "headline": item['headline'],
                    "summary": summary,
                    "source_url": item['source_url']
                })

            await self.post_news_to_slack(slack_url, summarized_news)
            console.log(f"Posted {len(summarized_news)} summarized news items to Slack.")
        except Exception as e:
            console.error("Worker error:", str(e))

    async def fetch_cybersecurity_news(self, api_key, max_items):
        query = (
            "Aktuelle Cybersecurity-Nachrichten der letzten zwei Arbeitstage für Unternehmen in der DACH-Region, "
            "mit Fokus auf bedeutende Datenpannen, Hacks und Sicherheitslücken. "
            "Bevorzuge Nachrichtenquellen aus Deutschland, Österreich und der Schweiz."
        )

        headers = Headers.new()
        headers.set("Content-Type", "application/json")
        headers.set("Authorization", f"Bearer {api_key}")

        body_dict = {
            "query": query,
            "max_results": max_items,
        }
        body_str = json.dumps(body_dict)

        options = Object.fromEntries([
            ["method", "POST"],
            ["headers", headers],
            ["body", body_str]
        ])

        resp = await fetch(PERPLEXITY_SEARCH_API_URL, options)

        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"Perplexity Search API Error: {resp.status} {resp.statusText}: {text}")

        data = await resp.json()
        try:
            data_py = data.to_py()
            results = data_py.get('results', [])
            news_items = []
            for item in results[:max_items]:
                # Prefer 'direct_url' if available, else 'source_url', else fallback to 'url'
                url = item.get("direct_url") or item.get("source_url") or item.get("url") or ""

                news_items.append({
                    "headline": item.get("title", "No title"),
                    "excerpt": item.get("snippet", ""),
                    "source_url": url,
                })

            console.log("Fetched news items with preferred URLs:", news_items)
            return news_items
        except Exception as e:
            console.error("Error parsing Search API response:", e)
            console.error("Response data that failed:", data)
            raise Exception("Failed to parse Perplexity Search API response") from e


    async def generate_summary(self, api_key, headline, excerpt):
        prompt = (
            f"Fasse die folgende Cybersecurity-Nachricht kurz und ohne Quellenverweise und ohne Formatierung und ohne Markdown zusammen:\n\n"
            f"Titel: {headline}\n\n"
            f"Inhalt: {excerpt}\n\n"
            f"Fasse die wichtigsten Informationen in 2-3 klaren Sätzen zusammen."
        )


        body = {
            "model": "sonar-pro",
            "messages": [
                {"role": "system", "content": "Du bist ein hilfreicher Assistent, der kurze Zusammenfassungen von Cybersecurity-Nachrichten erstellt."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 150,
            "temperature": 0.5,
        }

        headers = Headers.new()
        headers.set("Content-Type", "application/json")
        headers.set("Authorization", f"Bearer {api_key}")

        body_str = json.dumps(body)

        options = Object.fromEntries([
            ["method", "POST"],
            ["headers", headers],
            ["body", body_str]
        ])

        resp = await fetch(PERPLEXITY_CHAT_API_URL, options)

        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"Perplexity Chat API Error: {resp.status} {resp.statusText}: {text}")

        data = await resp.json()
        try:
            data_py = data.to_py()
            content = data_py['choices'][0]['message']['content']
            console.log("Summary generated:", content)
            return content.strip()
        except Exception as e:
            console.error("Error parsing summary content:", e)
            console.error("Chat API response that failed:", data)
            return excerpt  # Fallback to original excerpt

    async def post_news_to_slack(self, webhook_url: str, news_items):
        headers = Headers.new()
        headers.set("Content-Type", "application/json")

        blocks = []
        for item in news_items:
            blocks.append(f"*{item['headline']}*\n{item['summary']}\n<{item['source_url']}|Zur Quelle>")
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
