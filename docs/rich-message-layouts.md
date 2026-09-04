# Telegram Rich Messages — layout inventory & ideas for this bot

Date: 2026-09-04
Status: brainstorm / not a spec

Context: you already ship a **download box** (drill-down inline keyboard) and a
**movie card** (poster + caption). This doc maps everything Telegram now lets a
bot draw inside *one* message, then turns it into concrete things worth building
here.

---

## 1. What actually landed (three updates, not one)

The July 14 blog post you linked is the *user-facing* half. The bot-facing half
is spread over three Bot API releases:

| Date | API | What bots got | aiogram |
|---|---|---|---|
| Jun 11 2026 | **10.1** | `sendRichMessage`, `sendRichMessageDraft`, `editMessageText(rich_message=…)`, `InputRichMessage` (html / markdown), 32 768 chars | 3.29 |
| Jul 14 2026 | **10.2** | `InputRichMessage.blocks` (typed block tree), `media` array (file_id / upload, not just public URLs), **ephemeral messages**, communities | 3.30 |
| Aug 24 2026 | **10.3** | **buttons *inside* the message body** (`RichBlockButtons`, `RichMessageButton`), `is_compact` tables, expandable blockquotes, `EphemeralMessageParameters`, `disabled` buttons, `force_reply` | 3.31 |

Your `pyproject.toml` already pins `aiogram>=3.31`, so **all of this is reachable
today** — nothing to upgrade, only code to write.

The mental model that matters: a rich message is **not** HTML-in-a-webview.
There is no DOM, no CSS, no JS. The HTML/Markdown/JSON you send is a *description
of native Telegram widgets*; the client decides pixels. So: think semantic
blocks, never think "I'll align this with spaces".

---

## 2. Full primitive inventory

### 2.1 Block-level (the "layout" vocabulary)

| Block | HTML tag | Notes |
|---|---|---|
| Paragraph | `<p>` | |
| Heading 1–6 | `<h1>`…`<h6>` | size 1 = biggest |
| Divider | `<hr/>` | |
| Preformatted / code | `<pre><code class="language-python">` | syntax highlighting |
| Footer | `<footer>` | small print at the end of a section |
| Unordered list | `<ul><li>` | |
| Ordered list | `<ol start type reversed><li value type>` | `type` = `1 a A i I` |
| **Task list** | `<li>` with checkbox (`has_checkbox` / `is_checked`) | rendered as ☑ / ☐ — *not* interactive by itself |
| Block quote | `<blockquote>…<cite>Author</cite></blockquote>` | |
| **Expandable block quote** | same, expandable variant (10.3) | collapses long text |
| Pull quote | `<aside>…<cite>…</cite></aside>` | centered, magazine style |
| **Details / accordion** | `<details open><summary>…</summary>…</details>` | can nest full rich content |
| **Table** | `<table bordered striped compact><caption><tr><th><td colspan rowspan align valign>` | cells are **inline-only** |
| Photo | `<img src="https://…"/>` | standalone block only |
| Video / animation | `<video src>` | |
| Audio / voice note | `<audio src="…mp3">` / `.ogg` | |
| Document / file | inline document block (10.3) | |
| Media + caption + credit | `<figure><img tg-spoiler/><figcaption>cap<cite>credit</cite></figcaption></figure>` | |
| **Collage** | `<tg-collage>` + media children | grid |
| **Slideshow** | `<tg-slideshow>` + media children | swipeable carousel |
| **Map** | `<tg-map lat long zoom width height/>` | zoom 13–20 |
| Block formula | `<tg-math-block>E = mc^2</tg-math-block>` | LaTeX |
| Anchor | `<a name="x"></a>` + `<a href="#x">` | in-message navigation |
| **Buttons row** | `<tg-button-row><tg-button …>` (10.3) | 1–8 buttons per row |
| Thinking | `<tg-thinking>` | **drafts only** — the "AI is thinking" shimmer |

### 2.2 Inline (inside a paragraph / table cell / button label)

bold, italic, underline, strikethrough, **spoiler**, **marked/highlight**, code,
subscript, superscript, **inline LaTeX** (`$x^2$`), custom emoji
(`<tg-emoji emoji-id>`), **live date-time** (`<tg-time unix format>` — renders
"22:45 tomorrow" localized per viewer), user mention by ID, URL / email / phone /
bank card, hashtag, cashtag, bot command, **footnote reference + definition**,
anchor link.

Two of these are quietly great and everyone will ignore them:
- `tg-time` — every viewer sees the release date / expiry in *their* timezone and locale.
- `spoiler` — a plot summary that is genuinely spoiler-safe, and `tg-spoiler` on a poster.

### 2.3 Buttons — three tiers now

1. **Reply keyboard** — below the input field. Old news.
2. **Inline keyboard** (`reply_markup`) — attached under the message. What you use today.
   New in 10.3: `disabled` (a `DisabledButton` — greyed out, does nothing, but
   still *shown*, so your keyboard geometry stops jumping) and `force_reply`.
3. **Buttons inside the body** (`RichBlockButtons`) — the new thing. A button row
   is a *block*, so it can sit after a heading, between two tables, inside a
   `<details>`, or under each section. Styles: `primary`, `success`, `danger`,
   and **`link`** (borderless, callback-only — perfect for a subtle "more…").

Button payload types are the same set as inline keyboards: `url`, `callback_data`
(1–64 bytes), `web_app`, `login_url`, `switch_inline_query*`, `copy_text`.

> Exact tag names for in-body buttons (`<tg-button-row>` / `<tg-button>`) come
> from a community write-up, not from a doc page I could open (core.telegram.org
> 403s the fetcher). **Recommendation: use `InputRichMessage.blocks` with typed
> `InputRichBlockButtons` instead of hand-written HTML** — unambiguous, and you
> get pydantic validation from aiogram.

### 2.4 Ephemeral messages (the sleeper feature for *your* bot)

In a group, a bot can send a message **visible only to one user**:
`ephemeral_message_parameters` on `sendMessage` / `sendPhoto` / `sendRichMessage`
/ everything. Plus `BotCommand.is_ephemeral` (marks the command with a special
icon in the menu), `editEphemeralMessage*`, `deleteEphemeralMessage`, and
`replace_callback_query_message` (the ephemeral reply visually *replaces* the
message the user tapped).

### 2.5 Streaming drafts

`sendRichMessageDraft(draft_id=…)` — private chats only, 30 s TTL, changes
between drafts with the same `draft_id` are **animated**. You must finalize with
a real `sendRichMessage`. `can_stop` / `keep_on_stop` (10.3) let the user abort.
`<tg-thinking>` is legal only here.

---

## 3. Hard limits & gotchas

| Limit | Value |
|---|---|
| Characters | 32 768 (a "Show more" fold appears around ~8 000) |
| Blocks (incl. nested, list items, table rows) | 500 |
| Nesting depth | 16 |
| Media attachments | 50 |
| Table columns | 20 |
| Buttons per row | 1–8 |
| `callback_data` | 1–64 bytes |
| Map zoom | 13–20 |

Gotchas that will bite:

- **Media is block-level only.** No image inline in a sentence, no poster inside a table cell.
- **Table cells accept inline formatting only** — no nested list/image/button in a cell.
  A "download button per table row" is therefore *not* a thing: put the button row
  directly under the table, or make each row's quality cell a `url` link.
- **Auto entity detection** will turn stray `@`, `#`, `/…`, long digit runs into
  mentions/hashtags/commands. Persian titles + file names will trigger this. Set
  `skip_entity_detection=True` on anything machine-generated.
- **RTL**: set `is_rtl=True` on `InputRichMessage`. Do it once, globally, in your renderer.
- **Old clients** show a "update your app" placeholder instead of your beautiful
  table. Keep the current plain-HTML card as a fallback path — don't delete it.
- `editMessageText` takes `text` **xor** `rich_message`. Your `edit_text_safely`
  helper needs a second flavour.
- Media in `html`/`markdown` mode must be public HTTP(S) URLs; to use `file_id`
  or upload, either use the `media` array with `tg://photo?id=…` refs, or the
  `blocks` form.

---

## 4. Layout patterns — the catalog

Generic recipes; §5 maps them onto this bot.

1. **Hero card** — `<img>` + `<h2>` + meta paragraph + button row. Your current card, one tier up.
2. **Spec sheet** — 2-column `bordered striped compact` table of key/value. The single highest value/effort ratio.
3. **Table + action bar** — table above, `tg-button-row` below (since cells can't hold buttons).
4. **Accordion / FAQ** — stack of `<details>`; each one can hold its own table and buttons. This is how you kill multi-level drill-downs.
5. **Wizard / stepper** — ordered list where done steps are `- [x]`, current step is bold, plus a button row of the legal next actions. Re-render the whole message on each tap.
6. **Dashboard** — headings + tables + a footer with `tg-time` "last updated".
7. **Receipt / invoice** — table with right-aligned numbers, `<hr/>`, bold total, `<footer>` fine print.
8. **Gallery** — `<tg-collage>` (grid) or `<tg-slideshow>` (swipe) + caption + credit.
9. **Leaderboard** — striped table + `<sup>` rank deltas + footnotes for asterisks.
10. **Comparison matrix** — columns = options, rows = attributes, one button row per column below.
11. **Article / digest** — headings, pull quotes, footnotes, anchors + a table-of-contents made of anchor links. Up to 32 k chars.
12. **Progressive reveal** — spoiler inline text, expandable blockquote, closed `<details>`. Same message, three densities.
13. **Board game / grid UI** — table where cells are pieces, button rows for moves (this is literally Telegram's chess demo).
14. **Form / config panel** — task list showing current toggles, button row per toggle, `disabled` buttons for unavailable ones.
15. **Streaming report** — draft with `<tg-thinking>` → partial blocks appear → finalize.

---

## 5. What to build *here* — ranked

### A. Card v2: the whole download box in one message ★★★★★

Today: card → tap dub/original → tap quality → tap file. Three round trips, and
the keyboard is the only thing that changes.

Rich version — one message, zero navigation:

```html
<h3>🎬 Interstellar — میان‌ستاره‌ای (۲۰۱۴)</h3>
<p>⭐ 8.7 · 🎭 درام، علمی‌تخیلی · ⏱ 169 دقیقه</p>
<details><summary>📄 خلاصه داستان</summary><p>در آینده‌ای نزدیک…</p></details>

<table bordered striped compact>
  <caption>زبان اصلی</caption>
  <tr><th>کیفیت</th><th>حجم</th><th>لینک</th></tr>
  <tr><td>1080p</td><td align="right">2.1 GB</td><td><a href="…">دانلود</a></td></tr>
  <tr><td>720p</td><td align="right">1.4 GB</td><td><a href="…">دانلود</a></td></tr>
  <tr><td>480p</td><td align="right">800 MB</td><td><a href="…">دانلود</a></td></tr>
</table>

<table bordered striped compact>
  <caption>دوبله فارسی</caption>
  …
</table>

<tg-button-row>
  <tg-button style="primary" callback_data="c:9f2a">📋 کپی همه لینک‌ها</tg-button>
  <tg-button style="link"    callback_data="t:9f2a">🎞 تریلر</tg-button>
</tg-button-row>
```

Wins: dub vs original becomes a *visual comparison* instead of a branch; sizes
are readable in a column; no state machine for the common path; `CallbackState`
shrinks to only the genuinely stateful actions. Feeds directly off your existing
`MovieDetails.originals` / `.dubs`.

### B. Series: accordion of seasons, table of episodes ★★★★★

Your worst UX today — episode lists get chunked across multiple 3 800-char
messages. Instead: one `<details>` per season (closed by default, so a 10-season
show is still one screen), and inside each, an episodes × qualities table where
every cell is a link.

```html
<details><summary>📂 فصل اول — ۱۰ قسمت</summary>
  <table bordered striped compact>
    <tr><th>قسمت</th><th>1080p</th><th>720p</th><th>480p</th></tr>
    <tr><td>E01</td><td><a href="…">2.1G</a></td><td><a href="…">1.1G</a></td><td><a href="…">600M</a></td></tr>
    …
  </table>
  <tg-button-row><tg-button callback_data="zip:…">📥 لیست کامل فصل</tg-button></tg-button-row>
</details>
```

Watch the 500-block budget: a table row is a block. ~10 seasons × 12 episodes ≈
120 rows — fine. A 500-episode anime is not; fall back to per-season messages.

### C. Ephemeral group mode ★★★★☆

Right now the bot is DM-only with an allowlist. Ephemeral messages let you drop
it into your friends' group: someone runs an ephemeral `/فیلم` command, **only
they** see the results card, the group stays clean, and your "source privacy"
rule survives because nobody else ever sees the links. `is_ephemeral=True` on the
`BotCommand` gives it the special icon in the menu.
`replace_callback_query_message` means the drill-down still feels in-place.

This is the single biggest *product* change available, not just a cosmetic one.

### D. Streaming search with a thinking block ★★★★☆

Your design doc notes zarfilm pages take **4–5 s**. Today that's a static
«🔍 در حال جستجو…». With `sendRichMessageDraft` + `<tg-thinking>` you get an
animated shimmer, then results materializing block by block, animated between
drafts sharing a `draft_id`. Private chats only — which is exactly your case.
Add `can_stop=True` and handle the `stopped_message_generation` update to cancel
the in-flight scrape.

### E. Search results as a gallery ★★★☆☆

Five results = five poster+title blocks with a button row each, or a
`<tg-collage>` of posters with a numbered button row underneath. Way better than
five text buttons. Pagination buttons become a body-level row, freeing
`reply_markup` entirely.

### F. Watchlist / "tonight's pick" ★★★☆☆

Task list with `has_checkbox`, one button row per item to toggle. Re-render on
each tap. Combine with `tg-time` for "added ۳ روز پیش" that localizes itself.
Needs persistence beyond your TTL cache — this is the feature that justifies the
SQLite step your design doc already anticipates.

### G. Owner dashboard ★★★☆☆

`/status` renders a rich admin panel: session cookie validity (with `tg-time`
expiry), cache hit rate, last scrape latency, request count — as a striped table
with `danger`-styled buttons for `/login`, cache flush, etc. Replaces reading logs.

### H. Weekly digest ★★☆☆☆

If you ever add the "new content" crawler from the non-goals list: one 32 k-char
rich message per week — headings per genre, poster collage, table of new
releases, footnotes, TOC of anchor links. A newsletter inside a chat.

### I. Fun ones ★★☆☆☆

- **`copy_text` button** per link — Persian users mostly feed URLs to IDM; copy beats "open".
- **Spoiler plot + `tg-spoiler` poster** for unreleased titles.
- **`<tg-map>`** of filming locations under the card. Useless. Delightful.
- **Inline mode + `InputRichMessageContent`** — share a full rich movie card into any chat from the keyboard.
- **Roulette**: bot picks a random movie, button row `[دوباره] [بریم]`, re-renders in place.

---

## 6. Architecture note before you write any of this

Rich messages push you toward **server-driven UI**, and the failure mode is
well-known. Adopt four layers explicitly:

```
domain state  →  projection (what THIS viewer may see)  →  renderer (pure)  →  transport
```

Rules that will save you:

1. **The renderer is pure and total**: same state ⇒ same message, always. It's
   the natural extension of your existing `services/formatting.py` (already pure
   — keep it that way).
2. **Full re-render, never patch.** Cheaper than tracking which fragment the user saw.
3. **Version every mutating button.** Encode a revision in `callback_data`
   (`v=17;a=…`); if the stored revision moved on, answer "رابط به‌روز شد" and
   re-render instead of guessing. Your 6-hex `CallbackState` keys are the right
   shape already — add a revision counter to `CardEntry`.
4. **Idempotency**: derive a command id from `update_id` so a redelivered update
   can't double-apply.
5. **Feature-detect / degrade**: keep the current plain card as the fallback when
   `sendRichMessage` errors (old client, media rights missing in a group).

---

## 7. Suggested first slice

1. Add `render_card_rich(details) -> InputRichMessage` next to `card_text()` —
   pure function, unit-testable against the existing fixtures, no handler changes.
2. Golden-file tests: fixture HTML → parsed `MovieDetails` → expected rich HTML.
3. Wire it behind a `RICH_CARDS=1` env flag in `open_card`, with the current path
   as fallback on `TelegramBadRequest`.
4. Then series accordion (B), then ephemeral group mode (C).

Items A + B alone delete most of `handlers/card.py`'s drill-down state machine.
