---
name: chrome-pdf-fetch
description: Get a PDF that is behind a Cloudflare bot check (curl returns 403, headless browsers loop on "Just a moment…") using the claude-in-chrome extension in the user's real Chrome, then place it under var/external with provenance. Use when a source URL in this repo is Cloudflare-gated, or when a download attempt fails with 403 or a challenge page.
---

# chrome-pdf-fetch

## When to use

- `curl` or `WebFetch` returns 403 on a source PDF.
- Headless or Xvfb browsers stay on "Um momento…", "Executando verificação de segurança" or "Just a moment…".
- The source is a public document the user is entitled to read, and the user has asked for it.

Do not use it for paywalled or login-gated material, or to bypass a CAPTCHA. The Cloudflare check that passes here is a bot check on a public site, not a credential.

## Why headless fails

Cloudflare's managed challenge needs a real, interactive browser profile. Headless Chrome and Xvfb do not clear it for `dominiopublico.gov.br`. The attempt in the T1 run (2026-10-18) looped for 30–50 s on both the PDF URL and the site root.

## What worked (2026-10-18)

1. Load the browser tools in one ToolSearch call (`select:` the core set; see the system prompt).
2. `tabs_context_mcp` with `createIfEmpty: true`. Use the returned tab ID only for this task.
3. `navigate` the tab to the PDF URL. The page shows "Executando verificação de segurança" and then "Verificação bem-sucedida. Esperando a resposta de…".
4. `computer` `wait` 8 s, then `navigate` to the same PDF URL again. Chrome's viewer now renders the PDF (the first load set the clearance cookie in the real profile).
5. Confirm with a screenshot that the viewer shows the document, and note the page count in the viewer (`1 / N`).

## What did not work

- `curl` from the shell: 403. Do not try to copy the Cloudflare cookie out of Chrome. That is someone's browser session, not a file to use.
- The viewer's download button (top-right arrow) produced no file in `~/Downloads`, twice.
- Fetching bytes through `javascript_tool` and passing them back: a 3–4 MB base64 string does not fit in tool output.

So the file reached disk only when the user saved it from the open tab (Ctrl+S). Ask the user to do that step, and tell them the target folder.

## Getting the file onto disk

1. Ask the user to save from the open Chrome tab (Ctrl+S, or the viewer's save). Ask for the exact path if it is not the project root.
2. Find it: `find . -maxdepth 1 -iname "*.pdf"` from the repo root, or use the path the user gives. Check size and type with `ls -la` and `file`.
3. Move it, never delete. Refuse if the target already exists (raw sources are immutable). Then `mkdir -p var/external/<source>` and `mv <file> var/external/<source>/<name>.pdf`.
4. Record `sha256sum` and `pdfinfo` (page count, producer) in the source's `SOURCE.md`. Compare the page count with the catalogue record. A mismatch is a finding, not an error to hide (the 2008 thesis: viewer shows 469 pages, catalogue said 472).

## Safety and etiquette

- Use the user's own Chrome only with their approval. Ask before the first navigation, and before any download.
- Use one tab. Close it with `tabs_close_mcp` when done, unless the user wants it open.
- Never type credentials, never accept terms, never click a consent or "allow" button without asking.
- Never read or export cookies, storage, or saved passwords.
- Record the source URL, access date and method in the source's provenance file, so the file can be re-fetched and audited.

## Checklist for the next time

- [ ] curl confirms 403 (`curl -sS -o /dev/null -w "%{http_code}"`).
- [ ] User approved the browser route.
- [ ] Tab loads the PDF in Chrome's viewer.
- [ ] User saved the file; path given.
- [ ] Moved into `var/external/<source>/`, sha256 and page count recorded.
- [ ] Tab closed.
