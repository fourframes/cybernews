export const cron = '0 7 * * 1-5'; // Runs at 7:00 UTC (9:00 CEST), Monday to Friday

const PERPLEXITY_API_URL = 'https://api.perplexity.ai/v1/query'; // Hypothetical endpoint
const NEWS_SOURCES = [
  "Heise Security", "Krebs on Security", "The Hacker News",
  "ZDNet Cybersecurity", "SecurityWeek", "BleepingComputer", "Cybersecurity Insiders"
];

const DEFAULT_MAX_NEWS_ITEMS = 5; // Can be changed via ENV or in code

async function fetchCybersecurityNews(apiKey, maxItems) {
  const prompt = `
    Please provide the latest trending cybersecurity news relevant to companies operating in the DACH region (Germany, Austria, Switzerland).
    Each item should include a headline, a short excerpt, and a link to the original source.
    Focus on quality over speed. Use trusted sources like: ${NEWS_SOURCES.join(', ')}.
  `;

  const body = {
    model: "perplexity-advanced-v1", // Prioritize quality
    prompt,
    max_results: maxItems,
  };

  const response = await fetch(PERPLEXITY_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`Perplexity API error: ${response.status} ${response.statusText}`);
  }
  const data = await response.json();

  // Expected { results: [ { headline, excerpt, source_url } ] }
  return Array.isArray(data.results) ? data.results : [];
}

async function postNewsToSlack(webhookUrl, newsItems) {
  for (const item of newsItems) {
    const message = {
      text: `*${item.headline}*\n${item.excerpt}\n<${item.source_url}|Read more>`,
    };
    const response = await fetch(webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(message),
    });
    if (!response.ok) {
      throw new Error(`Slack webhook error: ${response.status} ${response.statusText}`);
    }
  }
}

// Scheduled entry point (cron)
export async function scheduled(event, env, ctx) {
  ctx.waitUntil(runWorker(env));
}

// Manual test (HTTP entry point)
export async function fetch(request, env, ctx) {
  const url = new URL(request.url);
  if (url.pathname === "/test-run") {
    ctx.waitUntil(runWorker(env));
    return new Response("Test run executed", { status: 200 });
  }
  return new Response("OK", { status: 200 });
}

// Main workflow
async function runWorker(env) {
  const perplexityApiKey = env.SECRET_PERPLEXITY_API_KEY;
  const slackWebhookUrl = env.SECRET_SLACK_WEBHOOK_URL;
  const maxNewsItems = Number(env.MAX_NEWS_ITEMS) || DEFAULT_MAX_NEWS_ITEMS;

  try {
    const newsItems = await fetchCybersecurityNews(perplexityApiKey, maxNewsItems);
    if (newsItems.length === 0) {
      console.log("No news items returned from Perplexity.");
      return;
    }
    await postNewsToSlack(slackWebhookUrl, newsItems);
    console.log(`Posted ${newsItems.length} news items to Slack.`);
  } catch (err) {
    console.error("Worker error:", err);
  }
}

// Secrets and config expected via Wrangler
// wrangler secret put SECRET_PERPLEXITY_API_KEY
// wrangler secret put SECRET_SLACK_WEBHOOK_URL
// wrangler.toml: [vars] MAX_NEWS_ITEMS = "5"
  
