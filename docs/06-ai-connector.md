# 6 · AI connector

The AI has **one job** in the Studio: reading supplier documents (PDF, Excel, CSV, Word, XML, HTML, photos, in any layout) and turning them into structured data for you to review. Everything else runs on your own database with no AI calls: matching against earlier sheets, version and duplicate detection, search, pricing, trips, quotations, PDFs.

## How the AI is used, and why it's reliable

| Step | What happens |
|---|---|
| 1. Make it readable | The file is turned into text with its tables kept as tables. Merged header cells are repeated over their columns, and page and sheet boundaries plus Word headers are marked. Scans and photos go to the AI as images. This is plain code, and layout-agnostic. |
| 2. Give context | The instructions (what to record, and how), plus **the names this supplier used in earlier sheets**: hotels, rooms, packages, add-ons. The AI is told to reuse the exact spelling for the same things and never to add anything that isn't in the document, so a re-sent sheet matches cleanly and duplicates don't appear. |
| 3. A fixed answer shape | The AI must answer by filling a fixed schema (a tool / function call), never free text. The answer is validated; anything that doesn't fit fails loudly instead of reaching the database. |
| 4. Copy, never calculate | Numbers are copied exactly. "On request" stays empty. Anything unclear goes into warnings for you. |
| 5. Package identity | For every package the AI also writes the name without season or year words (*base name*) and the edition ("Off Season 2026"), so editions of one package are recognised as versions. |
| 6. Revised sheets | The AI flags a sheet that says it is revised, and uses its effective date. |
| 7. Checks and change preview | Plain code checks dates, seasons, prices and group-size logic, then works out new / changed / unchanged against the library. You review before anything is saved. |

Long documents are read in parts; later parts get the first page as context, and long sheets repeat their header rows in every part.

**Prompt caching (Claude):** the instructions and the schema are the same for every call, so they're cached. The second and later parts of a long document, and documents read within a few minutes of each other, pay about a tenth for that part. The cost estimate counts cached tokens at that lower price. OpenAI and some other providers cache on their own, and that's counted too.

Everything about the AI is managed in **Settings → AI connector**. No code changes or redeploys needed.

---

## What the screen shows

**Top row, this month:**

- **AI calls**, with how many failed and the average time;
- **tokens sent** (input) and **tokens received** (output);
- **estimated cost**;
- the **monthly budget** bar.

**Tokens per day:** a stacked bar per day, input tokens in lavender and the AI's answer in orange. Hover a bar for that day's calls, tokens and cost. You can choose the last 7, 30 or 90 days, and **Show table** gives the numbers.

**By model** and **Recent AI calls** show each call with the document it was for. Click one to open that document. Failed calls are marked, with the reason on hover.

> **Tokens** are how AI providers measure, and charge for, text. Roughly 1 token is ¾ of an English word. A typical one-page hotel rate sheet uses 5–15k input tokens and 3–10k output tokens. A 17-page package PDF like the Kashmir one uses more.

---

## Providers

| Provider | Needs | Notes |
|---|---|---|
| **Claude (Anthropic)** (the default) | API key from console.anthropic.com | Reads PDFs natively, including scans; the most tested option here. Models: `claude-sonnet-5-5` (default, best balance), `claude-opus-5-5` (hardest documents), `claude-haiku-4-5-20251001` (cheapest; fine for clean Excel and simple sheets) |
| OpenAI | key and model name | Use a model with function calling and image input |
| Google Gemini | key and model name | Through Google's OpenAI-compatible endpoint |
| Groq | key and model name | Fast and cheap. Check that the model supports tool calls. |
| OpenRouter | key and model name | One key for many companies' models |
| Other (OpenAI-compatible) | base URL, model name, key if needed | Any server with an OpenAI-style `/chat/completions`, e.g. a local **Ollama** at `http://localhost:11434/v1` |

For non-Claude providers, scanned PDFs are sent as page images, up to *Scanned PDF pages to send* (default 20). Normal PDFs and Excel files are sent as extracted text, whatever the provider.

---

## Switching provider (e.g. from Claude to another AI)

1. Settings → AI connector → **AI provider**: choose the new one. The key badge and "Get a key" link switch to that provider.
2. **Model:** type the model name exactly as the provider lists it. For Claude, pick from the suggestions.
3. **Base URL:** already filled in for the listed providers. For *Other*, type your server's address.
4. **API key:** paste it. It's saved **encrypted** and only the last 4 characters are ever shown.
5. **Save**, then **Test connection**. You'll see the reply, the time taken and the tokens used, or the provider's exact error message.
6. Optional: open any document and press **Read again** to compare the new AI's result with the old one.

To go back, choose Claude again. If `ANTHROPIC_API_KEY` is set on the server, it's used automatically. A saved key belongs to one provider, so switching provider clears it.

---

## Keys: where they're kept

| Where | How | Wins? |
|---|---|---|
| Saved in Settings | Encrypted in the database with the server's `SECRET_KEY`. Never sent back to the browser. | **Yes** |
| Server environment variable | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `CUSTOM_AI_API_KEY` | Used when nothing is saved in the app |

- If `SECRET_KEY` isn't set, the key box is disabled and you must use the environment variable.
- If `SECRET_KEY` changes, saved keys can't be read and you'll be asked to enter the key again.
- **Remove saved key** falls back to the environment variable.

---

## Cost and budget

1. Enter **Price per 1M input tokens** and **Price per 1M output tokens** from your provider's pricing page, and pick the currency (USD, INR or EUR). Prices change, so check the page rather than copying a number from here.
2. Set a **Monthly budget**. When this month's estimated cost reaches it, new uploads are saved but marked *failed* with a budget message. Press **Try again** after raising the budget or when the month changes. What's already in the library keeps working.
3. The cost shown is an **estimate** from your prices. Your provider's invoice is the real figure. Calls made before you entered prices are estimated at today's prices, both on screen and for the budget.

**AI reading switched on:** untick this to stop all AI calls, for example while a key is being replaced. New uploads are then saved but marked *failed* with the reason. Press **Try again** on them once AI reading is back on. The same happens when the budget is used up.

---

## Extra instructions

These are your own rules, added to the built-in ones every time a document is read. Use them when one supplier's sheets keep coming out wrong. For example:

```
Abdaal Travels prices are always net B2B.
"Room + Brekkie" means CP. "Half board" means MAP.
Green Valley's "Super Deluxe" is its own hotel category, not Deluxe.
When a sheet says "valid till further notice", use 31 March of next year as the end date and add a warning.
```

After saving, press **Read again** on an affected document. Up to 4,000 characters.

The instructions are added *after* the built-in rules, so the AI still has to:

- copy numbers exactly and never calculate prices;
- follow the fixed output format;
- flag anything ambiguous.

---

## Max tokens per answer

This is the longest answer the AI may write for one document, or one part of a long document. Big package PDFs with long hotel lists need long answers. If a document fails with *"Extraction was cut off"*, you have two fixes:

- raise this number;
- or lower **Chunk size** in Settings → Processing, so the document is read in more, smaller parts.

---

## What is sent to the AI provider

**Sent:** the text and tables of the uploaded document (or the file itself for scans and photos), the file name, the supplier name you typed, and the instructions.

**Never sent:** customer names, phone numbers, trips, payments, users or passwords.

Supplier B2B rates do leave your server to reach the AI provider. Anthropic's commercial API terms state that API data isn't used to train models by default. Check your chosen provider's terms, and any confidentiality clauses in your DMC contracts.

---

## Common errors

| Message | Fix |
|---|---|
| *No API key for Claude (Anthropic)* | Paste a key and Save, or set `ANTHROPIC_API_KEY` |
| *authentication_error / 401* | Wrong or expired key. Create a new one at the provider. |
| *This month's AI budget … is used up* | Raise the budget, or wait for next month |
| *Extraction was cut off* | Raise Max tokens, or lower Chunk size |
| *The AI did not return the expected structured data* | The model can't do tool or function calls. Pick a stronger model. |
| *Set SECRET_KEY … to save API keys from the app* | Add `SECRET_KEY` on the server and redeploy, or use the environment variable |
| *AI reading is switched off* | Tick *AI reading switched on* and Save |
