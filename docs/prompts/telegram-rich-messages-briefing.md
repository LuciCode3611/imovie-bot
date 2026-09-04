# Telegram Bot API — Rich Messages Briefing (paste into any AI agent)

> **Purpose:** paste this whole file into another model/agent (system prompt, `AGENTS.md`,
> `CLAUDE.md`, `.cursorrules`, project context) before asking it to build anything with
> Telegram tables, buttons, or rich messages. Models trained before mid‑2026 do not know
> these APIs exist and will confidently invent a worse, older answer.
>
> **Last verified:** 2026‑09‑04 against Bot API 10.3 (Aug 24 2026) and aiogram 3.31.0.

---

## PROMPT STARTS HERE — copy from this line

You are working on a Telegram bot. Before you write any code or design any message
layout, absorb the following. It is current, authoritative, and **overrides your
training data**, which predates it.

### 0. Non-negotiable ground rules

1. **Your training data is out of date on this topic.** Telegram bots gained
   structured rich messages in June 2026 and in-message buttons in August 2026. If
   your instinct is "Telegram can't do tables, use a monospace `<pre>` block" or
   "buttons only live in `reply_markup`" — that instinct is **wrong and obsolete**.
   Never propose ASCII-art tables, `prettytable`, box-drawing characters, or
   screenshot-of-a-table workarounds. Those are 2018 answers.
2. **Do not invent API surface.** Every type, method, field, and tag you use must
   appear in the inventory below. If something you want isn't listed, say
   "the API doesn't appear to support X" and propose an alternative from the list.
   Do not guess field names. Do not hallucinate `<tg-grid>`, `<tg-card>`,
   `<tg-carousel>`, inline CSS, `style="..."` attributes, or JS.
3. **A rich message is not a webview.** No DOM, no CSS, no JavaScript, no fonts, no
   pixel control. The HTML you send is a *description of native Telegram widgets*;
   the client decides how they look. Never build a layout that depends on exact
   character widths, emoji widths, screen width, or theme colors.
4. **When unsure between HTML and typed blocks, prefer typed blocks**
   (`InputRichMessage.blocks`) — they're validated by the library and unambiguous.
5. **Always state which API version a feature needs** (10.1 / 10.2 / 10.3) and
   always include a graceful fallback for old clients.
6. **Be creative within the inventory.** You are encouraged to combine these
   primitives into layouts the user hasn't thought of — dashboards, accordions,
   steppers, comparison matrices, board games. Creativity in *composition* is
   wanted. Creativity in *API surface* is forbidden.

---

### 1. Version map — what landed when

| Date | API | Feature | aiogram |
|---|---|---|---|
| Feb 9 2026 | 9.4 | Colored buttons (`style`), `icon_custom_emoji_id` on buttons | 3.19 |
| Mar 1 2026 | — | Member tags, `date_time` message entity, `Message.sender_tag` | — |
| Mar 31 2026 | — | "Mighty Polls" (multi-answer, revoting, media, descriptions), bots managed by bots | — |
| Apr 4 2026 | — | Managed bots, `SavePreparedKeyboardButton`, poll option add/delete updates | — |
| May 7 2026 | — | **Guest bots** (`answerGuestQuery`), bot-to-bot chats, chat automation | — |
| Jun 11 2026 | **10.1** | **Rich Messages**: `sendRichMessage`, `sendRichMessageDraft`, `editMessageText(rich_message=)`, 32 768 chars, AI guardians for join requests, links in poll options | 3.29 |
| Jul 14 2026 | **10.2** | `InputRichMessage.blocks` (typed tree), `media` array, **Ephemeral messages**, **Communities** | 3.30 |
| Aug 24 2026 | **10.3** | **Buttons inside the message body**, `is_compact` tables, expandable blockquotes, document blocks, `EphemeralMessageParameters`, `disabled` buttons, `force_reply`, `can_stop` drafts | 3.31 |

**Minimum library version for the full set: aiogram 3.31 / Bot API 10.3.**
Client-side, Telegram Desktop needs ≥ 7.1.0 for in-message buttons.

---

### 2. Methods

```
sendRichMessage(chat_id, rich_message: InputRichMessage, ...)
    also: business_connection_id, message_thread_id, direct_messages_topic_id,
          disable_notification, protect_content, allow_paid_broadcast,
          message_effect_id (private chats only), suggested_post_parameters,
          reply_parameters, reply_markup, ephemeral_message_parameters (10.3)

sendRichMessageDraft(chat_id, draft_id, rich_message, can_stop?, keep_on_stop?)
    PRIVATE CHATS ONLY. Ephemeral 30s preview. Same draft_id => animated diff.
    You MUST finalize with a real sendRichMessage to persist it.

editMessageText(..., rich_message=)      # text XOR rich_message, exactly one
editEphemeralMessageText / Media / Caption / ReplyMarkup
deleteEphemeralMessage
```

### 3. `InputRichMessage`

Exactly **one** of `html`, `markdown`, or `blocks`. Never two.

| Field | Notes |
|---|---|
| `html` | Rich HTML string |
| `markdown` | Rich Markdown string (GFM-compatible where possible) |
| `blocks` | `InputRichBlock[]` — typed tree, **preferred** |
| `media` | `InputRichMessageMedia[]`, referenced from html/markdown via `tg://photo?id=`, `tg://video?id=`, `tg://audio?id=`, `tg://document?id=` (10.3) |
| `is_rtl` | **Set `True` for Persian/Arabic/Hebrew content.** Do this once in the renderer. |
| `skip_entity_detection` | **Set `True` for machine-generated text.** See §8. |

Media in `html`/`markdown` mode must be public HTTP(S) URLs. To use a `file_id` or
upload a file, use the `media` array or the `blocks` form (`InputMedia*` accepts
`file_id`, URL, or `attach://name` with multipart).

### 4. Block inventory (the layout vocabulary)

| Block | Rich HTML | Typed block |
|---|---|---|
| Paragraph | `<p>` | `paragraph` |
| Heading 1–6 | `<h1>`…`<h6>` | `heading` + `size:1..6` (1 = largest) |
| Divider | `<hr/>` | `divider` |
| Code block | `<pre><code class="language-python">` | `pre` + `language` |
| Footer | `<footer>` | `footer` |
| Unordered list | `<ul><li>` | `list` |
| Ordered list | `<ol start type reversed><li value type>` — type ∈ `1 a A i I` | `list` + item `value`/`type` |
| Task list | `<li>` w/ checkbox | item `has_checkbox`, `is_checked` — **display only, not tappable** |
| Block quote | `<blockquote>…<cite>Author</cite></blockquote>` | `blockquote` + `credit` |
| Expandable quote (10.3) | expandable variant | `expandable_blockquote` |
| Pull quote | `<aside>…<cite>…</cite></aside>` | `pullquote` |
| Collapsible | `<details open><summary>…</summary>…</details>` | `details` + `summary`, `is_open` |
| **Table** | `<table bordered striped compact><caption><tr><th><td colspan rowspan align valign>` | `table` + `cells[][]`, `is_bordered`, `is_striped`, `is_compact` (10.3), `caption` |
| Photo | `<img src="https://…"/>` | `photo` |
| Video / animation | `<video src>` | `video` / `animation` |
| Audio / voice note | `<audio src="….mp3">` / `.ogg` | `audio` / `voice_note` |
| Document (10.3) | file block | `document` |
| Media + caption + credit | `<figure><img tg-spoiler/><figcaption>Cap<cite>Credit</cite></figcaption></figure>` | block `caption: {text, credit}` |
| Collage (grid) | `<tg-collage>` + media children | `collage` |
| Slideshow (swipe) | `<tg-slideshow>` + media children | `slideshow` |
| Map | `<tg-map lat long zoom/>` | `map` + `location`, `zoom`/`width`/`height` (all optional since 10.3) |
| Block formula | `<tg-math-block>E = mc^2</tg-math-block>` | `mathematical_expression` |
| Anchor | `<a name="x"></a>` | `anchor` |
| **Button row (10.3)** | `<tg-button-row><tg-button …>` * | `buttons` (`InputRichBlockButtons`) |
| Thinking | `<tg-thinking>` | `thinking` — **`sendRichMessageDraft` only** |

\* The exact HTML tag names for in-body buttons come from a community write-up, not
a page I could verify directly. **Use the typed `InputRichBlockButtons` block
instead** — it is confirmed in the aiogram 3.31 and Bot API 10.3 changelogs.

### 5. Inline text inventory

`bold` `italic` `underline` `strikethrough` `spoiler` `marked` (highlight) `code`
`subscript` `superscript` `mathematical_expression` (inline LaTeX, `$x^2$`)
`custom_emoji` `date_time` `text_mention` `url` `email_address` `phone_number`
`bank_card_number` `mention` `hashtag` `cashtag` `bot_command` `anchor`
`anchor_link` `reference` (footnote def) `reference_link` (footnote ref).

Two that are underused and that you should proactively suggest:
- **`date_time`** (`<tg-time unix="…" format="wDT">`) — renders in *each viewer's*
  timezone and locale. Use it for anything time-based instead of a formatted string.
- **`spoiler`** / `tg-spoiler` on media — genuinely spoiler-safe plot text and
  blurred images.

### 6. Buttons — three tiers, know which you mean

1. **Reply keyboard** — below the input field.
2. **Inline keyboard** (`reply_markup`) — attached beneath the message. New in 10.3:
   `InlineKeyboardButton.disabled` (a `DisabledButton`: shown but inert, so your
   keyboard geometry stops jumping) and `InlineKeyboardMarkup.force_reply`.
3. **In-body buttons** (10.3, `RichBlockButtons`) — a button *row is a block*, so it
   can sit after a heading, between two tables, or inside a `<details>`.

Payload types (both tiers): `url`, `callback_data` (1–64 bytes), `web_app`,
`login_url`, `switch_inline_query[_current_chat|_chosen_chat]`, `copy_text`,
`callback_game`, `pay`.

Styles: `primary` (blue), `success` (green), `danger` (red), and — **in-body
buttons only** — `link` (borderless, callback-only). Buttons also accept
`icon_custom_emoji_id` (requires the bot owner to have Premium, or a
Fragment-purchased username).

**1–8 buttons per row.** 8 is legal and almost always a bad idea.

### 7. Hard limits

| Limit | Value |
|---|---|
| Characters | 32 768 (client folds behind "Show more" ~8 000) |
| Blocks (incl. nested, list items, **table rows**, quote/details blocks) | 500 |
| Nesting depth | 16 |
| Media attachments | 50 |
| Table columns | 20 |
| Buttons per row | 8 |
| `callback_data` | 64 bytes |

### 8. Gotchas that WILL break your first attempt

- **Media is block-level only.** No image inline in a sentence. No poster inside a
  table cell.
- **Table cells accept inline formatting only.** No nested list, image, button, or
  block in a cell. Therefore *"a button on every table row" is impossible* — put a
  button row under the table, or make a cell a `url` link.
- **A table row costs one of your 500 blocks.** Budget large tables.
- **Auto entity detection** turns stray `@`, `#`, `/word`, long digit runs, and
  card-like numbers into mentions/hashtags/commands/cards. Machine-generated
  content (filenames, IDs, non-Latin titles) *will* be mangled. Set
  `skip_entity_detection=True`.
- **RTL**: set `is_rtl=True`; don't try to fix direction with markup.
- **`editMessageText` takes `text` XOR `rich_message`** — your edit helper needs a
  second code path.
- **Old clients** render an "update your app" placeholder instead of your layout.
  Always keep the plain-HTML path as a fallback on `TelegramBadRequest`.
- **Media rights**: if a rich message contains a media block, the bot needs
  permission to send that media type in that chat.
- Drafts are **private chat only**, are **not persisted**, and expire in 30 s.

### 9. Ephemeral messages (10.2, revised 10.3)

A bot can send a message in a group **visible to exactly one user**.

- `ephemeral_message_parameters: EphemeralMessageParameters` on `sendMessage`,
  `sendPhoto`, `sendVideo`, `sendAnimation`, `sendAudio`, `sendDocument`,
  `sendSticker`, `sendVideoNote`, `sendVoice`, `sendLivePhoto`, `sendLocation`,
  `sendVenue`, `sendContact`, **and `sendRichMessage`**.
- `replace_callback_query_message` (10.3) — the ephemeral reply visually *replaces*
  the message the user tapped. This is how you do private drill-downs in a group.
- `BotCommand.is_ephemeral` — marks the command with a special icon in the menu.
- `Message.receiver_user`, `Message.ephemeral_message_id`,
  `ReplyParameters.ephemeral_message_id`.
- Edit/delete via `editEphemeralMessageText` (accepts `rich_message` since 10.3),
  `…Media`, `…Caption` (`show_caption_above_media`), `…ReplyMarkup`,
  `deleteEphemeralMessage`.
- **Deprecated:** `receiver_user_id` / `callback_query_id` — use
  `ephemeral_message_parameters`.
- `login_url` buttons are **not supported** in ephemeral messages.

Use cases: private results in a shared group, per-user menus, errors and
confirmations nobody else should see, private AI summaries, onboarding.

### 10. Streaming drafts (10.1, extended 10.3)

`sendRichMessageDraft(chat_id, draft_id, rich_message, can_stop=True, keep_on_stop=True)`
→ animated partial renders → finalize with `sendRichMessage`. `<tg-thinking>` /
`thinking` block is legal only in drafts (custom emoji for it:
`t.me/addemoji/AIActions`). If `can_stop`, handle the **`stopped_message_generation`**
update (`MessageGenerationStopped`; in aiogram it's a router observer of the same
name) and cancel the underlying work.

---

### 11. Things people forget exist — check these before reinventing them

These are separate 2026 features that often solve the problem better than a
hand-rolled rich message. Consider each before building:

- **Checklists** — `sendChecklist`, `InputChecklist`, `InputChecklistTask`,
  `ChecklistTask.completed_by_chat`. A *real, tappable, stateful* checklist.
  Rich-message task lists are display-only — if the user needs to tick things off,
  use this, not `has_checkbox`.
- **Mighty Polls** — multi-correct answers (`correct_option_ids`), `allows_revoting`,
  `shuffle_options`, `allow_adding_options`, `hide_results_until_closes`,
  `description`, **media in poll options and explanations** (`InputPollOptionMedia`),
  **links in poll options** (`Link` / `InputMediaLink`), persistent option IDs,
  `poll_option_added` / `poll_option_deleted` updates, `ReplyParameters.poll_option_id`.
  A poll is often a better survey than a button grid.
- **Guest bots** (May 2026) — `User.supports_guest_queries`, `answerGuestQuery`,
  `Update.guest_message`, `guest_bot_caller_user`. Your bot can answer in chats it
  isn't a member of. Pairs naturally with ephemeral messages.
- **AI guardians / join requests** — `answerChatJoinRequestQuery`,
  `sendChatJoinRequestWebApp`, `ChatJoinRequest.query_id`,
  `ChatFullInfo.guard_bot`. Screen applicants with a mini-app or quiz.
- **Communities** (10.2) — `Community`, `ChatFullInfo.community`,
  `CommunityChatAdded`/`Removed` (also fire for *bots*), `CommunityChatJoined` (10.3).
  Link your bot + channel + group under one chat-list entry.
- **Welcome messages** (10.3) — `can_send_welcome_messages` on
  `ChatAdministratorRights` / `ChatMemberAdministrator` / `promoteChatMember`.
  Combine with ephemeral + in-body buttons for an interactive onboarding flow.
- **`copy_text` buttons** — one-tap clipboard copy. Frequently better than a `url`
  button when the user will paste the value into another app (download managers,
  wallets, coupon codes).
- **Member tags** (Mar 2026) — `setChatMemberTag`, `Message.sender_tag`,
  `can_manage_tags`. Role labels next to names, without a role-bot.
- **`date_time` message entity** — the non-rich-message version of `tg://time`.
  Works in ordinary messages too.
- **Live Photos** — `sendLivePhoto`, `InputMediaLivePhoto`, `ContentType.LIVE_PHOTO`.
  Note: Telegram sends a regular `photo` alongside, so check `live_photo` *first*.
- **Message effects** (`message_effect_id`) — private chats only.
- **Prepared inline messages** — `savePreparedInlineMessage`; and
  `InputRichMessageContent` lets an **inline query result be a full rich message**.
- **Managed bots** — `KeyboardButtonRequestManagedBot`, `savePreparedKeyboardButton`,
  `getManagedBotToken`, `User.can_manage_bots`. Bots that create/configure bots.
- **Paid broadcast** — `allow_paid_broadcast` for >30 msg/s at 0.1 Stars each.

---

### 12. Architecture you must follow for interactive rich messages

An interactive rich message is **server-driven UI**. Use four layers:

```
domain state → projection (what THIS viewer may see) → renderer (pure) → transport
```

1. **Renderer is pure and total.** Same state ⇒ byte-identical message. No clocks,
   no randomness, no reading the previous markup.
2. **Full re-render on every interaction.** Never patch fragments. The tree is
   small; diffing is not worth the bugs.
3. **Version every mutating button.** Put a revision in `callback_data`
   (e.g. `v=17;a=fold`). If the stored revision has moved on, answer the callback
   with "this view is out of date", re-render, and **do not** apply the action.
   Users double-tap, use two devices, and scroll back to old messages.
4. **Idempotency.** Derive a command id from `update_id` and enforce uniqueness in
   storage — the DB write and the Telegram ack are not one transaction.
5. **Authorize the callback.** Verify the tapping user owns that session; never
   trust ids just because Telegram delivered them.
6. **Coalesce edits.** One user gesture must not fan out into a burst of
   `editMessageText` calls — you will hit rate limits.
7. **Feature-detect and degrade.** Wrap `sendRichMessage` and fall back to the
   legacy formatted message on error.

### 13. Rich Message vs Mini App — pick deliberately

| | Rich Message | Mini App |
|---|---|---|
| UI | Native Telegram widgets | Web view |
| Hosting | None — markup rides the Bot API | Separate frontend + hosting |
| Design freedom | Low (client decides) | Near total |
| Interaction | Discrete taps → server round trip | Gestures, forms, animation, local state |
| Best for | Step-by-step flows, statuses, dashboards, surveys, turn-based games, action panels | Catalogs, editors, maps, graphics, complex navigation |

Choose Rich Message when the scenario is a **finite state machine with a small set
of actions**: user sees a snapshot, picks one action, gets the next snapshot.

### 14. How to answer me from now on

When I mention tables, buttons, rich messages, cards, or layouts:

- Assume 10.3 is available; **do not** ask whether Telegram supports tables.
- Name the exact blocks/types you'll use and the API version each needs.
- Show the layout as either typed blocks or Rich HTML — pick one and say why.
- Call out the block budget, the character count, and the entity-detection risk.
- Include the old-client fallback.
- Propose **one composition idea I didn't ask for** — a way to fold a multi-step
  flow into a single message, or a primitive from §5/§11 that fits. Then stop;
  don't pad with more.
- If I ask for something the API can't do (button in a table cell, inline image
  mid-sentence, CSS, animation), say so plainly and give the nearest legal layout.

## PROMPT ENDS HERE

---

## Notes for the human (not part of the prompt)

- Trim §11 and §13 if the target model has a small context window; §0–§8 are the
  load-bearing parts.
- `core.telegram.org/bots/api` blocks most automated fetchers (HTTP 403). If an
  agent claims it verified something there, it probably didn't. The reliable
  machine-readable mirrors are library changelogs — aiogram
  (`docs.aiogram.dev/en/latest/changelog.html`) and phptg/bot-api's `CHANGELOG.md`
  track the API release-by-release.
- Live playground for the format: **@RichTextDemoBot**. Working in-message-button
  examples: Telegram's chess demo (@RichChessBot) and a third-party poker
  implementation (@CorvenhallPokerBot).
- Re-verify this file whenever a new Bot API version ships; bump the "Last
  verified" date at the top.
