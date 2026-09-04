# Build a Telegram bot with Bot API 10.1 Rich Messages

> Copy this prompt into any coding agent. Replace the `{{...}}` placeholders per
> bot. It is written so the agent understands the real capabilities/limits of
> Telegram **rich messages**, **tables**, **rich buttons**, headings, media and
> RTL — and does NOT fall back to fake ASCII tables or inline keyboards.

---

## 1. What you are building

A Telegram bot (Python, **aiogram ≥ 3.31**) that presents results as **Bot API
10.1/10.2 Rich Messages**.

- Content type: **movies / TV series** (change to `{{domain: e.g. products,
  recipes, jobs, articles}}`).
- Language / direction: **Persian, RTL** (`is_rtl=true`). Change to
  `{{language}}` / `{{rtl|ltr}}`.
- Each item opens as ONE rich message that is edited in place on navigation
  (never spawn a new message per screen).

## 2. Use the correct API (do not use these wrong approaches)

DO NOT:
- Build tables out of spaces/pipes in a normal text message (`| a | b |`) — real
  rich tables support clickable links, alignment, headers; monospace fakes do not.
- Put every action as a bottom `InlineKeyboardMarkup` button when it belongs
  inside the content — use **rich buttons** (button blocks) where appropriate.
- Chunk long content into many 4,096-char messages. Rich messages allow up to
  **32,768 chars**.

DO use:
- **`sendRichMessage`** (aiogram: `bot.send_rich_message(...)`,
  `InputRichMessage`) and **`editMessageText` with the `rich_message` parameter**
  to edit in place. In aiogram 3.31 the types live in `aiogram.types`:
  `InputRichMessage`, `InputRichBlock*`, `RichBlock*`, `RichText*`,
  `RichMessageButton`, `CopyTextButton`.

### Limits to respect
- 32,768 characters · **500 blocks** total (nested included) · max **20 table
  columns** · max 50 media.
- `CopyTextButton` (copy-to-clipboard) text is capped at **256 characters**.
- Custom emoji in a message require the bot owner to have **Telegram Premium**
  (or a Fragment username); always pass `alternative_text` fallback.
- Rich messages need a recent client; wrap sends in try/except and **fall back to
  a classic `send_photo` + caption + inline keyboard** if the API rejects them.

## 3. Blocks reference (the building blocks)

Message content = an ordered list of **blocks** (`InputRichMessage(blocks=[...],
is_rtl=True)`), OR an `html`/`markdown` string. Prefer explicit block objects.

- **Photo / media block:** `InputRichBlockPhoto(photo=InputMediaPhoto(media=URL))`
  placed anywhere in the body (top for a poster). Also video, audio, animation,
  voice note, collage, slideshow.
- **Heading:** `InputRichBlockSectionHeading(text=..., size=1..6)`.
- **Paragraph:** `InputRichBlockParagraph(text=...)`.
- **Table:** `InputRichBlockTable(cells=[[cell, cell], ...], is_bordered=bool,
  is_striped=bool, is_compact=bool, caption=?)`.
  - `cell = RichBlockTableCell(text=<RichText>, align="left|center|right",
    valign="top|middle|bottom", is_header=bool, colspan=?, rowspan=?)`.
  - `text` is a `RichText` — a plain string OR a list of inline rich text nodes.
- **Divider:** `InputRichBlockDivider()`.
- **Pull quote:** `InputRichBlockPullQuotation(text=..., credit=?)` — rendered
  **centered** by Telegram (there is no align field; it is always centered).
- **Block quote:** `InputRichBlockBlockQuotation(blocks=[...], credit=?)`.
- **Expandable block quote:** `InputRichBlockExpandableBlockQuotation(text=...)`
  (collapsed “show more”).
- **Collapsible details:** `InputRichBlockDetails(summary=..., blocks=[...],
  is_open=bool)`.
- **Lists:** `InputRichBlockList(items=[InputRichBlockListItem(label=?,
  blocks=[...], has_checkbox=?, is_checked=?, type="ordered|unordered")])`.
- **Buttons block:** `InputRichBlockButtons(buttons=[RichMessageButton(...)],
  align=?)`. Inline rich text button node: `RichTextButton(button=...)`.
- **Footer:** `InputRichBlockFooter(text=...)`.

### Inline rich text (RichText) nodes for cell/paragraph text
`RichTextBold`, `RichTextItalic`, `RichTextUnderline`, `RichTextStrikethrough`,
`RichTextSpoiler`, `RichTextCode`, `RichTextCustomEmoji(custom_emoji_id=...,
alternative_text=...)`, **`RichTextUrl(text=..., url=...)`** (a clickable link —
this is how table cells link out), `RichTextMention`, `RichTextTextMention`,
`RichTextHashtag`, `RichTextCustomEmoji`, etc. A plain `str` is also accepted.

### Rich buttons (`RichMessageButton`) — fields
Exactly ONE action per button: `url`, `callback_data`, `web_app`, `login_url`,
`switch_inline_query(_current_chat/_chosen_chat)`, `copy_text=CopyTextButton(
text=...)`, or `disabled=DisabledButton(...)`. Plus `text` (RichText) and
optional `style`: `"primary"` (blue), `"success"` (green), `"danger"` (red),
`"link"`.

## 4. EXACT layout I want for the item card

Build blocks in this order (`{{...}}` = data from the scraped item):

1. **Poster photo block** — `{{poster_url}}`.
2. **Metadata table** — `InputRichBlockTable(is_bordered=False, is_striped=False,
   is_compact=True)`. Every cell `align="center", valign="middle"`.
   - Title/header row (two header cells): `{{title_english}}` |
     `{{title_persian}}`.
   - Then metadata rows, each = `[label cell, value cell]` (label-first — this
     order renders RTL, label on the right, on Telegram **mobile**):
     - `امتیاز` → `{{imdb}}/10`
     - `مدت زمان` → `{{runtime}}`   *(omit the whole row if the source has none)*
     - `محصول` → `{{country}}`
     - `ژانر` → `{{genres joined by «،»}}`
     - `ستارگان` → `{{cast joined by «،»}}`
   - Label cell text = a `RichTextCustomEmoji` (the custom emoji id below)
     followed by the label, with `alternative_text` set to the fallback unicode:
     - امتیاز `{{EMOJI_ID_RATING}}` (fallback ⭐)
     - مدت زمان `{{EMOJI_ID_RUNTIME}}` (fallback ⏱)
     - محصول `{{EMOJI_ID_COUNTRY}}` (fallback 🌍)
     - ژانر `{{EMOJI_ID_GENRE}}` (fallback 🎭)
     - ستارگان `{{EMOJI_ID_CAST}}` (fallback 🎬)
3. **Divider.**
4. **Story pull quote** — `InputRichBlockPullQuotation(text={{plot}})` (centered
   automatically). Omit if no plot.

Buttons under the message (classic `reply_markup` inline keyboard is fine for
the primary actions, OR rich button blocks — your choice, keep it consistent):
- `🎬 مشاهده تریلر` → URL button to `{{trailer_url}}` when present.
- Primary download/season actions; **dubbed (دوبله) options use
  `style="success"` (green)**, original audio uses `style="primary"` (blue).
- A back button (`🔙 بازگشت`) to return to the previous view, editing in place.
- A copy button **only when the copied text fits 256 chars** (`CopyTextButton`);
  otherwise do not split into many buttons.

### Drill-down (TV series)
- Seasons shown as buttons labeled `فصل N - X قسمت` (X = episode count).
- A quality choice opens an **episode table** (`is_compact=True`,
  `is_striped=True`), header row `قسمت | حجم | دانلود`, each episode row with the
  episode label, size, and a `RichTextUrl` link cell. Keep the whole season in
  one message (rich limits allow it). Back button returns to qualities; another
  back returns to seasons — all via `editMessageText(rich_message=...)`.

### RTL rule that matters
There is a client inconsistency: some Desktop clients mirror table columns
relative to mobile. **Target mobile RTL**: put the label in the FIRST cell and
the value in the SECOND cell (`[label, value]`), set `is_rtl=True`, and keep
Persian text. Do not add bidi characters inside cells; let `is_rtl` handle
direction.

## 5. Data to scrape (parser)
From `{{source site / HTML}}` extract: english title, persian title, year,
poster URL, genres, IMDb rating (normalise to `X/10`), countries (محصول), cast
(ستارگان), runtime if available (omit row otherwise), plot, and the
**trailer link** (e.g. an anchor like `a.trailer_btn` →
`https://{{site}}/play/{id}/trailer/`). Only mark a field present when the source
actually contains it.

## 6. Code expectations
- Python 3.12, aiogram ≥ 3.31. Isolate rich-building in a `services/rich.py`;
  keep a classic fallback. Keep all Persian user-facing strings; no source-site
  name/URL in user text.
- Unit tests: build the rich message from a sample payload and assert block
  types/order, table `is_bordered=False`, every cell `align=="center"`,
  label-first order, custom-emoji ids on label cells, and trailer URL button.
- Keep callback data ≤ 64 bytes. Handle expired/state-key lookups gracefully.
- Empty `ALLOWED_USER_IDS` = bot open to everyone.

`{{extra project-specific notes}}`
