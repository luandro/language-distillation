# Lane 05 — Living-language media: platforms, broadcast, social

Survey date **2026-10-18**. Target: Marúbo (`mzr`, Glottolog `maru1252`), Panoan, TI Vale do
Javari, Amazonas, Brazil. Lane scope: user-generated and community-produced video, audio,
radio, podcasts and social posts where Marúbo or a sister Panoan language is actually
spoken — with attention to anything carrying subtitles, captions, transcripts or on-screen
text.

Status key: **[V]** = verified by direct fetch of the resource in this pass; **[W]** = only
attested through a web index, a third-party listing or a page's own claim; **[U]** = present
but unverified (inference from metadata, or content that cannot be inspected without
listening/downloading).

---

## 0. Bottom line

1. **There is no Marúbo-language corpus on any living-language platform.** Ten years of
   YouTube searching, a TikTok cluster, a radio network and a community newsroom later, the
   total publicly retrievable Marúbo *text* on these platforms is a handful of words in
   Portuguese-language titles (`Kenãpaka yavia`, `tocanto ako`, `Maronal`). Everything else
   is **audio you would have to transcribe by hand**.
2. **The one exception that matters** is a six-film Javari set produced by indigenous
   filmmakers with CTI / UNIVAJA: **3 h 54 min** of Marúbo, Matsés and Matis speech, of which
   **3 h 20 min carries manual Portuguese subtitles** (plus EN and FR on most). It is the only
   place in this lane where an indigenous-language audio track and a human-authored
   Portuguese translation of the same speech exist side by side. The Marúbo-language film in
   the set ("Assim Aprendemos", 33:18) is, however, the **one film without manual subtitles**.
3. **Captions are named but not retrievable.** YouTube's player response enumerates each
   caption track and marks it `kind: "asr"` (auto) or manual, but the `timedtext` endpoint
   returns **0 bytes** without a PO token / player session. So *"does it have subtitles?"* is
   answerable; *"give me the subtitle text"* is not, by an unauthenticated agent, without
   circumventing a bot check — which this survey does not do.
4. **The living channel is radio + WhatsApp, not the web.** UNIVAJA's own communication
   department ("Vozes do Javari") states it produces **weekly radio bulletins** and
   audio/video bulletins that are **"traduzidas para a língua de cada povo"** — i.e. Marúbo
   versions exist — distributed through **WhatsApp groups** and *radiofonia* to villages with
   no internet. None of it is public. This is the highest-value lead and the least accessible.
5. **`Marubo` is a Portuguese music keyword, not a language keyword.** The most-viewed
   "Marubo" results on YouTube are Boi-Bumbá *toadas* (`Mística Marubo`, 128k views;
   `Tanameá Marubo`, 34.7k) — Portuguese lyrics that *thematise* the Marúbo as exotic subject.
   Any keyword-based collection will be dominated by this noise.

Governance headline: **none of this is licensed for reuse or training.** Presence-based
authorization (ADR-0025) settles what the repo may do with a file *once it is in the repo*; it
does not grant a right to take the file off YouTube, TikTok or a radio stream in the first
place, and it does not cure the consent problem of a community that is currently litigating
over how it was represented. See §1.

---

## 1. Governance reality (read before using anything below)

**Platform terms forbid exactly the operation a corpus builder wants.** Quoted verbatim from
the fetched pages (2026-10-18):

- YouTube ToS — you may not *"access, reproduce, download, distribute, transmit, broadcast,
  display, sell, license, alter, modify or otherwise use any part of the Service or any
  Content except: (a) as expressly authorized by the Service; or (b) with prior written
  permission from YouTube and, if applicable, the respective rights holders"*.
- TikTok ToS — User Content may not be *"reproduced, distributed, transmitted, broadcast,
  displayed, sold, licensed or otherwise exploited for any purpose whatsoever without our or,
  where applicable, our licensors' prior written consent. We and our licensors reserve all
  rights not expressly granted"*.

Meta platforms (Facebook/Instagram) and X are the same shape and are additionally
login-gated. There is no platform in this lane that offers a reuse licence for third-party
content. Default posture is **all rights reserved**, and a caption track is a derivative work
of the same content, not a separate free asset.

**ADR-0025 does not change this.** ADR-0025 (accepted 2026-10-18) makes *presence in
`var/external/`* the authorization basis for processing and training, and demotes licence,
ownership and register to recorded metadata rather than gates. That is a decision about what
the pipeline does with material it already holds. It is **not** a right to acquire the
material: the acquisition step is where the platform ToS bind, and where the community's
consent lives. Concretely, for this lane:

| Question | Answer |
|---|---|
| Can an agent fetch these pages? | Yes — HTML/metadata only, for cataloguing. |
| Can an agent download the media or captions? | No. ToS + no PO token + this lane's brief ("do not download media files"). |
| Would putting a downloaded file in `var/external/` make it trainable? | Technically yes per ADR-0025; **provenance would be a ToS breach and a consent gap**, and revocation (ADR-0015) would then have to unwind it. |
| What makes this lane trainable in practice? | A human obtaining (a) written permission from the named rights holder — CTI, UNIVAJA, AIMA, OAMI, or the individual creator — and (b) community consent for the specific register. |
| What is the register risk? | Ritual material (Matis tattoo festival; Marúbo shamanic song) is `ritual_restricted` by default. Do not label it `traditional_public`. |
| Extra caution specific to Marúbo | Brazilian outlets report that Marúbo representatives sued the New York Times over its 2024 Starlink coverage (**[W]** — seen only as YouTube news titles, e.g. *"Indígenas processam NYT por reportagem que liga grupo à pornografia"*, Metrópoles; *"Tribo Indígena PROCESSA o New York Times por 180 Milhões"*). Not verified here, but it is a strong signal that unconsented scraping of Marúbo material is politically live. |

---

## 2. Catalogue

### 2.1 Video — YouTube

Checked 2026-10-18 by fetching `youtube.com/results?search_query=…` and channel `/videos`
pages and parsing `ytInitialData`; caption inventory read from
`ytInitialPlayerResponse.captions.playerCaptionsTracklistRenderer`.

| Slug | Resource | Contents & volume | Formats | Licence | Access | Task fit | Trust / status |
|---|---|---|---|---|---|---|---|
| `yt_cti_univaja_javari_films` | **CTI / UNIVAJA Javari film set**, https://www.youtube.com/@TrabalhoIndigenista (channel `UCw880b_DSn112ayXoXcLnRQ`); films listed in §3.1 | 6 films, **14 028 s ≈ 3 h 54 min**; **5 of 6 have manual pt-BR subs** (4 also EN+FR) = 12 031 s ≈ 3 h 20 min subtitled | MP4 via YouTube; manual WebVTT/SRV caption tracks (enumerated, not extractable) | No licence stated; "realização CTI" + OAMI/AIMA/UNIVAJA/FUNAI; all rights reserved | Page public; captions present but `timedtext` → 0 bytes unauthenticated | Best in-lane: indigenous-language speech + human PT translation; pronunciation, discourse, toponyms, register documentation | **[V]** existence, duration, caption kinds, description text |
| `yt_assim_aprendemos_marubo` | *Assim Aprendemos* (2014, Marúbo, TI Vale do Javari), https://www.youtube.com/watch?v=Q09VvHpmdXU — "Thus we learn" | 33:18; produced by Marúbo teachers and youth, I Oficina de Formação Audiovisual, rio Ituí, 2013 | MP4; **only `es` ASR caption** (auto, wrong language) | as above (CTI + OAMI) | public; no usable transcript | The only known long-form Marúbo-language film; everyday/educational register; needs full transcription | **[V]** metadata + caption inventory; **[W]** that speech is Marúbo (from producer description) |
| `yt_vimi_marubo` | **VIMI MARUBO**, https://www.youtube.com/@vimimarubo3341 | **30 videos, 2 816 s ≈ 47 min**, **348 subscribers**; roça, copaíba oil, rapé plant, *trocano*, *Kenãpaka yavia* (Festa de Ovo), Javari river, aldeia Maronal | MP4, phone-shot; **0 caption tracks** on every video sampled | none; all rights reserved; channel links a Facebook profile (`moaci.yora`) and Kwai (`@vimi132`) | public, fully viewable | Everyday register, toponyms (`Maronal`, rio Curuçu, igarapé), plant/technique vocabulary, festival names; on-camera speech, Portuguese text | **[V]** channel, counts, durations, titles, zero captions |
| `yt_delvair_marubo_2005` | *Marubo, seus adornos e símbolos* (Delvair Montagner, 2005), https://www.youtube.com/watch?v=gpLdSW3Ut_M — "Marubo, their adornments and symbols" | 24:58, 5 026 views; ethnographic doc, credited crew listed | MP4; `pt` **ASR only** | no licence; filmmaker/CNPq-era production, uploaded by "Povos Indígenas no Brasil" | public; ASR of mixed narration + Marúbo speech is unreliable | Material culture vocabulary, adornment terms, possible Marúbo speech under PT narration | **[V]** metadata/captions; **[U]** spoken language (not listened) |
| `yt_amazonia_real_forca_delas` | **Amazônia Real**, *A Força Delas* — Talita Marúbo (https://www.youtube.com/watch?v=IpAtxiZiy6s, 9:17) and Silvana Marúbo (https://www.youtube.com/watch?v=jwM9O_ZkC7Y, 3:47) | 2+ short interviews, channel `UCqso_WZbRLRpKHstlHQj5TA` | MP4; `pt` ASR only | Amazônia Real (journalism), all rights reserved | public | Named Marúbo women speakers, contemporary urban/ political register; PT-dominant with possible Marúbo code-switching | **[V]** metadata/captions |
| `yt_sumuma_beto_marubo` | SUMAÚMA Jornalismo, *Beto Marubo — Direto do Centro do Mundo* (Rádio SUMAÚMA), https://www.youtube.com/watch?v=M-Uvb8l4mLA | 50:46 long-form conversation, 2025-11-14 | MP4; `pt` ASR only | SUMAÚMA, all rights reserved | public | Portuguese-only political discourse; **no Marúbo speech expected**; useful for named-speaker roster and land-conflict toponyms | **[V]** |
| `yt_unreported_world_starlink` | Channel 4 *Unreported World*: "Is Musk's Starlink a threat to the Amazon?" https://www.youtube.com/watch?v=Wg7f3TOaOnY | 23:44, 16 785 views, 2025-04-06; filmed in São Sebastião village with Marúbo leaders | MP4; **`en` ASR only** | Channel 4 / Unreported World, all rights reserved | public; ASR over Marúbo+PT speech produces garbage | Confirms Marúbo on-camera interviews exist in high-production foreign docs; **not** a transcript source | **[V]** metadata/captions; **[U]** how much Marúbo is spoken |
| `yt_ycw_enoque_marubo` | YCW, "Tribal Truths: YCW Meets … Enoque Marubo of the Associação Kapyvanaway", https://www.youtube.com/watch?v=7dH8qo4l4Ik | 25:01, 38 135 views, 2024-07-11; **8 auto-ASR languages, no manual track** | MP4 | third-party creator, all rights reserved; content is a rebuttal campaign aimed at the NYT | public | Long interview with a named Marúbo leader/organisation; register: advocacy | **[V]** metadata; **[W]** trust caution — partisan framing, foreign channel, unclear consent |
| `yt_museu_audio_visual_ufam` | MAVis — Museu AudioVisual (UFAM), https://www.youtube.com/@museuaudiovisual | Ritual/ festival films of Upper Solimões peoples (e.g. *TÜKÜNA NAWA WAIK — III Festival Cultural do Povo Kanamari*, 32:46); **no Marúbo title found** | MP4 | UFAM research archive, all rights reserved | public | Institutional comparator for how ritual film is documented; not Marúbo data | **[V]** channel exists; **negative** for Marúbo |
| `yt_mirrors_lionel_rossini_ogm` | Re-uploads of the Javari films: https://www.youtube.com/@lionelrossini (e.g. *UESNID Bacuëac*, 16:47, **19 454** views vs 821 on CTI's own copy; *Ocondo Podquied*, 27:55, 3 810) and https://www.youtube.com/@canaldaOGM | ≥4 duplicate films, one with **23× the views of the original** | MP4 | **unknown uploader, no visible grant** | public | Shows where audience actually is; **do not use** — orphaned rights | **[V]** pages; **[W]** uploader identity/authority |
| `yt_boi_bumba_false_positives` | Boi-Bumbá *toadas*: *Mística Marubo* (Caprichoso, 4:19, 128 114 views), *Tanameá Marubo* (Garantido, 4:02, 34 784), *Marubo* (Muirapinima, 6:36, 19 807), *Ritual de Cura Marubo* (Mangangá, 3:20) | ≥4 tracks, hundreds of thousands of views | MP4 | label/publisher rights (ONErpm etc.) | public | **None** — Portuguese lyrics; invented "indigenous" words; must be excluded from any keyword harvest | **[V]** |
| `yt_small_personal_channels` | `@shapomarubo` (Enoque Marúbo, 34 subs, 4 videos incl. *Casamento na Tribo Marubo*, 4:11), `@raminpamarubo1261` (3 subs, 1 video), `@alfredomarubo6697` (16 videos claimed, grid shows a playlist) | ~6-21 videos total, all short, no captions | MP4 | none stated | public | Named individual Marúbo videographers — **contact leads**, not corpora | **[V]** existence/subscriber counts; **[W]** video counts where the grid did not render |
| `yt_univaja_oficial` | **UNIVAJA OFICIAL**, https://www.youtube.com/@UNIVAJAOFICIAL | **17 subscribers, 2 videos** (*Oficina UNIVAJA UNODC — Vozes do Javari 2026*, 4:24; a 13:11 phone export) | MP4 | UNIVAJA | public | Proof that the federation's own YouTube is a stub — the real output is radio/WhatsApp (§2.3) | **[V]** |
| `yt_cti_comunicadores_javari` | CTI, *Reportagem Comunicadores Indígenas T.I Vale do Javari* (2022), https://www.youtube.com/watch?v=4vnxK7Q8PA0; and *Oficina Audiovisual Vale do Javari [junho 2024]*, https://www.youtube.com/watch?v=43V-Yom-ahM | 2:07 and 6:27 | MP4 | CTI | public | Documentary evidence that a **Javari indigenous communicators' collective** exists — the human network to ask for consent | **[V]** |
| `yt_band_roda_viva_cultura` | Broadcast interviews with Marúbo leaders: Band Jornalismo (0:57), Roda Viva / Beto Marubo (1:32), TV Cultura / Beto Marubo (6:34), CNN Brasil (2:13), AFP (2:13), Rede TVT (4:16), Fundo Brasil / Paulo Marubo (2:55, https://www.youtube.com/watch?v=LuDXkj0kPKM) | ~8 short items, 2022-2024 | MP4; ASR only (pt/es/en) | each broadcaster, all rights reserved | public | Portuguese testimony; speaker roster + toponyms; no Marúbo-language value | **[V]** per-video metadata |

**Cross-cutting YouTube facts established [V]:** no channel anywhere in the results publishes
Marúbo-language *titles*; the only Marúbo words in metadata are `Kenãpaka yavia`, `tocanto
ako`, `Maronal` (VIMI MARUBO) and the film titles `Nuqin Nidaid Cudas Nuna`, `Ocondo Podquied
Nibëmquid`, `Uesnid Bacuëac` (Matsés/Matis orthography). Manual subtitle tracks exist **only**
on the CTI/Univaja set. Everything else — including all Marúbo-speaker videos — carries zero
or auto-generated captions only.

### 2.2 Short-video and social video (TikTok, Kwai, Instagram, Facebook, Vimeo, X)

| Slug | Resource | Contents & volume | Formats | Licence | Access | Task fit | Trust / status |
|---|---|---|---|---|---|---|---|
| `tiktok_marubo_accounts` | TikTok cluster: `@kena_marubo` (e.g. *Okê okê* https://www.tiktok.com/@kena_marubo/video/7679247369434664210), `@marcus_akany` (https://www.tiktok.com/@marcus_akany/video/7690297208561863944), `@marubo88`, `@marubo562`, `@reinaldo.marubo`, `@clau_marubo`, `@flaviana.marubo`, `@mapocheromarubo`, `@crizin_777x` (Aldeia Boa Vista tourism reel), hashtag https://www.tiktok.com/tag/marubo | **≥9 named accounts**; short clips, high posting frequency; captions are burned-in Portuguese text, song lyrics, or nothing | MP4/HLS; no caption API exposed | TikTok ToS: no reuse without consent (quoted §1); individual creators own their posts | Profiles return a **1 462-byte stub** to non-browser clients (cannot enumerate); `oembed` works per known URL and returns title/description only | **Highest density of contemporary spoken Marúbo**; ideal for pronunciation, prosody, slang, code-switching — if a human with consent collects it | **[V]** two items via oembed (author, title text); **[W]** the remaining handles (from a DDG `site:tiktok.com` result set); **[U]** spoken language of each clip |
| `kwai_vimi132` | Kwai profile https://www.kwai.com/@vimi132 (display name `𝓥𝓲𝓶𝓲_𝓢𝓶15`), linked from VIMI MARUBO's YouTube channel | unknown count; page loads (74 KB) but stats and grid are client-rendered | MP4 | Kwai terms, all rights reserved | page fetches; content not enumerable without JS | Same creator as `yt_vimi_marubo` → cross-platform identity (`moaci.yora` on Facebook), useful for a consent conversation | **[V]** page + handle; **[U]** volume |
| `instagram_marubo_accounts` | `@univajaoficial` (org), `@kena_marubo`, `@artessanato_marubo` ("aldeia são Joaquim", artesanato, 15 followers), `@aldeiamultietnica` reel featuring Kena Marúbo (3 027 likes) | ~4 accounts identified; reels | MP4 | Meta terms; all rights reserved | **Gated**: profile fetch returns a generic "Instagram" document with no OG metadata → login wall | Reels = short speech + Portuguese on-screen text; only via consented capture | **[W]** account existence via index snippets; **[V]** the login wall |
| `facebook_marubo_pages` | `facebook.com/univajaoficial` (linked from univaja.org), `facebook.com/moaci.yora` (VIMI MARUBO's own cross-link); public groups for aldeias assumed but **not verifiable** | unknown | MP4 / text | Meta terms | **Gated** — login wall; groups are not publicly indexable | Would be the best place to find everyday written Marúbo + event notices; blocked | **[W]** pages exist (linked from first-party sites); **[V]** gating |
| `vimeo_panoan_search` | Vimeo search https://vimeo.com/search?q=marubo | unknown | — | Vimeo terms | **HTTP 403** to non-browser clients; API needs a token | Potentially films by CTI/VnA partners | **Negative** (blocked) |
| `x_twitter_marubo` | `x.com/univajaoficial` (linked from univaja.org) | unknown | text/MP4 | X terms | login-gated | Advocacy text, Portuguese | **[W]** account exists; **[V]** gated |

### 2.3 Audio — radio and podcasts

| Slug | Resource | Contents & volume | Formats | Licence | Access | Task fit | Trust / status |
|---|---|---|---|---|---|---|---|
| `univaja_vozes_javari_bulletins` | **UNIVAJA "Vozes do Javari"** communication department — https://univaja.org/vozes-do-javari/ | **Weekly radio bulletins** + audio/video bulletins, "traduzidas para a língua de cada povo"; distributed via **WhatsApp groups** and *radiofonia*; produced for villages without internet or cell signal | audio (WhatsApp voice/audio files), video, radio inserts | UNIVAJA (community-controlled federation); no public licence | **Not public at all** — no archive, no feed, no channel. Access = relationship with UNIVAJA (Atalaia do Norte) | **The single best living-language audio source in the lane**: Marúbo-language news register, recurring, recent, produced *by* the community. Highest consent quality available | **[V]** the programme's existence and self-description (quoted); **[U]** volume, duration, exact language mix |
| `radio_ebc_alto_solimoes` | **Rádio Nacional do Alto Solimões FM 96,1 MHz** (EBC) — stream `https://radionacionalaltosolimoes-stream.ebc.com.br/ebc/radionacionalaltosolimoes/playlist.m3u8`, homepage `https://radios.ebc.com.br/nacionalaltosolimoes` (redirects to `radionacional.ebc.com.br`), studio address Rua Rui Barbosa S/N, Tabatinga/AM | continuous 24/7; HLS, **AAC 119 kbps**; EBC tags `brazilian,mpb,news,public radio,talk` | HLS/AAC stream | EBC (public broadcaster) — no open licence on the stream; rebroadcast requires EBC authorization | stream is publicly playable; **no archive, no transcripts, no per-programme pages** | Only regional station actually serving Tabatinga / Atalaia do Norte / Benjamim Constant; Marúbo-language slots **plausible but unverified** | **[V]** station, frequency, stream, address; **[U]** indigenous-language programming |
| `podcast_marubo_none` | Podcast directories: Apple Podcasts (`itunes.apple.com/search?term=marubo&entity=podcast`, BR store, 25 results), Deezer API, Mixcloud API, Internet Archive audio, SoundCloud search | **No Marúbo or Panoan podcast exists** in any directory checked | — | — | — | — | **Negative**, see §4 |
| `podcast_adjacent_indigenous_br` | Adjacent, *not* Marúbo: **Rádio SUMAÚMA** (38 eps, anchor.fm/s/10b033dcc) — includes the Beto Marúbo episode; **TAVAS** (Museu das Culturas Indígenas, 24 eps); **Vozes do Planeta** (316 eps) | ~380 episodes, Portuguese | RSS/MP3 | each publisher, all rights reserved | public feeds | Portuguese-side vocabulary on Javari issues; **zero Marúbo-language value** | **[V]** feed metadata via iTunes API |
| `archive_org_none` | Internet Archive `advancedsearch.php` for `marubo`, `marúbo`, `javari`, `panoan`, `matsés`, `matis`, plus `mediatype:audio` variants | `marubo` → 8 hits (all noise); `panoan` → 8 (academic texts, Shipibo dictionary); `matsés` → 34 (books, Wikipedia dumps); **no Marúbo audio item** | — | — | — | — | **Negative**; two near-miss items catalogued for completeness: `youtube-xhxLryDjGfQ` (Tim Dillon Show mirror discussing the Marúbo Starlink story — US comedy, irrelevant) and `MARUBOKABLESGEREKBRAMAZONDENEYM` (Turkish re-edit, "MARUBO KABİLESİ", 328 files, uploader contact redacted, no licence, likely re-cut web footage) |
| `radio_garden_mixcloud_none` | Radio Garden `api/search`; Mixcloud `api.mixcloud.com/search` | Radio Garden returns place-name hits with no station fields; Mixcloud returns only homographs (*Maru Botana*, *JAVA RIDDIM*, *DJ Matse Dee*) | — | — | — | — | **Negative** |

### 2.4 Text and social

| Slug | Resource | Contents & volume | Formats | Licence | Access | Task fit | Trust / status |
|---|---|---|---|---|---|---|---|
| `univaja_site_marubo_page` | **UNIVAJA** people page https://univaja.org/marubo/ (and the Javari peoples index https://univaja.org/nossos-povos/) | ~7 500 chars of community-authored self-description: ornament names (*arua* snail cord, *cinta larga*, palm-seed beads: *cocão*, *jarina*, *pupunha*), the term **`nawa`** for non-indigenous people, **`Yora`** as self-designation, village layout, contact history, the 1952 "new contact" | HTML | site copyright UNIVAJA; text reusable only with permission | fully fetchable | **Genuine community-authored vocabulary and self-designation** — the strongest textual anchor in this lane; also the address for consent | **[V]** |
| `univaja_member_associations` | Member associations listed at https://univaja.org/nossa-base/ — **AIKUVAJA, AIMA (Matis), AKAVAJA, AMAS, ASDEC, OAMI (Organização Marúbo do Rio Ituí), OGM** | 7 organisations | HTML | — | fetchable | **This is the consent map.** OAMI is the Marúbo-specific counterparty named in the CTI film credits | **[V]** |
| `medium_blog_marubo` | Medium tag feed https://medium.com/feed/tag/marubo; WordPress.com tag API `read/tags/marubo/posts` | **3 items, total, ever** — one Italian piece on the Starlink story, one 2017 blog on "a palavra xamanística", one unrelated. WordPress: 0 | RSS/JSON | authors | public | Nothing | **Negative** |
| `isa_pib_marubo` | ISA *Povos Indígenas no Brasil* — https://pib.socioambiental.org/pt/Povo:Marubo | long encyclopedia entry; language section | HTML | ISA, CC-ish but per-page; check before reuse | public | Ethnonym/language naming, demographics, history — **context, not media** (probably already known to lanes 01/03) | **[V]** page exists |
| `telegram_whatsapp_marubo` | Public Telegram channels / WhatsApp community links | **none discoverable**; UNIVAJA explicitly uses *private* WhatsApp groups for distribution | — | — | not joinable, and this survey does not join | Distribution channel exists but is closed by design | **Negative** (with the caveat that a closed channel *is* the finding: §2.3) |

### 2.5 News, documentary and festival catalogues

| Slug | Resource | Contents & volume | Formats | Licence | Access | Task fit | Trust / status |
|---|---|---|---|---|---|---|---|
| `news_amazonia_real` | https://amazoniareal.com.br/?s=marubo | ≥12 Marúbo-tagged articles (Paulo Marúbo obituary; isolated Indians sighted near a Marúbo village; Bruno/Dom search; Covid in Atalaia do Norte) + the video series in §2.1 | HTML + YouTube | Amazônia Real, all rights reserved; some CC in specific pieces | fetchable | Named speakers, place names, chronology; **Portuguese only** | **[V]** |
| `news_infoamazonia` | https://infoamazonia.org/?s=marubo | ≥10 articles incl. interviews about the Javari | HTML | InfoAmazonia (often CC BY-NC-ND on individual pieces — check per page) | fetchable | Context; occasional quoted Marúbo leader speech in PT | **[V]** |
| `news_sumaura` | https://sumauma.com (SUMAÚMA — Eliane Brum) | Javari coverage; Rádio SUMAÚMA episodes | HTML + audio | SUMAÚMA, all rights reserved | fetchable (DNS `sumuma.com` is wrong; correct host `sumauma.com`) | Portuguese journalism | **[V]** domain; **[W]** Marúbo-specific pieces not enumerated |
| `forumdoc_etudoverdade` | Forumdoc.bh (https://www.forumdoc.org.br) and É Tudo Verdade (https://etudoverdade.com.br) | **No Marúbo-language title surfaced** in the 2026 Forumdoc navigation; É Tudo Verdade's search URL 404s; `forumdoc.org.br/?s=marubo` returns the homepage (site search unsupported) | HTML | — | partially fetchable | Festival catalogues remain a plausible but unconfirmed route (a human should search the printed/PDF catalogues) | **Negative** (with method caveat) |

---

## 3. Detail on the items that matter

### 3.1 `yt_cti_univaja_javari_films` — the only subtitled indigenous-language film set

Produced in the CTI + UNIVAJA audiovisual workshops with Javari indigenous filmmakers
("Agentes Ambientais Indígenas e cineastas indígenas da TI Vale do Javari"), five films plus a
sixth Marúbo film from an earlier 2013 workshop. All on
https://www.youtube.com/@TrabalhoIndigenista (**2.07k subscribers**), uploaded 2022-05-10
(except *Assim Aprendemos*, 2024-04-30).

| Film | URL | Length | Language | Caption tracks |
|---|---|---|---|---|
| *Nuqin Nidaid Cudas Nuna* — "Protecting our territory" | https://www.youtube.com/watch?v=MQy7PZQhQpg | 20:59 | Matsés | **pt-BR manual**, en-US, fr-FR, pt ASR |
| *Ocondo Podquied Nibëmquid* — "Following Ocondo's footsteps" | https://www.youtube.com/watch?v=J5kfVGnZlSo | 28:22 | Matis | **pt-BR manual**, en, fr, pt ASR |
| *Uesnid Bacuëac* — "Mutum river" | https://www.youtube.com/watch?v=2KmKulW4hpI | 16:41 | Matis | **pt-BR manual**, en-US ASR, pt ASR |
| *Matses Muxan Akadakit* — "Matis tattoo festival" | https://www.youtube.com/watch?v=pUAOl39Jhdo | 1:30:43 | Matis (ritual) | **pt-BR manual**, en, fr |
| *O Manejo está vivo!* — "Management is alive!" | https://www.youtube.com/watch?v=N-I8FqLoMlo | 43:47 | Matis/Matsés + PT | **pt-BR manual**, en, fr, pt ASR |
| *Assim Aprendemos* — "Thus we learn" (2014) | https://www.youtube.com/watch?v=Q09VvHpmdXU | 33:18 | **Marúbo** | **es ASR only — no manual track** |

Why this is the top find despite being sister-language material: it is the *only* place where
the survey found a human-authored Portuguese translation of indigenous Panoan speech with
timecodes. That makes the **alignment method** demonstrable (audio + human PT cue list) even
though the indigenous side is not transcribed. Per invariant 8, Matis/Matsés evidence may
generate **hypotheses**, never Marúbo truth.

Two hard constraints found by direct probe:
- The subtitles are **paraphrases**, not literal glosses — CTI's own framing is translation for
  a general audience. Do not treat a subtitle cue as an IGT line.
- `timedtext` extraction is blocked: fetching the enumerated `baseUrl` (with `fmt=json3` and
  `fmt=vtt`) returned **0 bytes**. The tracks are real (they render in the player) but the
  endpoint requires a PO token from a live player session.

Rights: no licence statement anywhere. Credits name CTI, OAMI (Marúbo, rio Ituí), AIMA (Matis),
UNIVAJA, Instituto Catitu, FUNAI, FNDE/BNDES. **Any use needs CTI + the named association.**

### 3.2 `univaja_vozes_javari_bulletins` — the actual living-language channel

Verbatim from https://univaja.org/vozes-do-javari/ [V]:

> "Utilizamos plataformas como o Instagram e o site da UNIVAJA … ao mesmo tempo em que nos
> valemos de **grupos de WhatsApp e da radiofonia** para informar nossas comunidades que têm
> acesso mais limitado à internet."
> "Além disso, realizamos **boletins semanais transmitidos por rádio** …"
> "Sempre atentos à participação e democratização das informações, os boletins e comunicações
> são **traduzidas para a língua de cada povo**."

Read carefully, this is the whole lane in one paragraph: recurring, community-authored,
Marúbo-language *news* audio exists; it is delivered by radio and WhatsApp; it is not on the
web; and the producing institution is a federation with a public address
(Rua Cunha Gomes, 123, Atalaia do Norte, AM, 69650-000) and a communication department set up
precisely to control its own narrative. Register: modern, everyday, administrative/news —
exactly the register a low-resource LKB lacks, and the complement to the ritual/ mythological
material already indexed (`cesarino_2013_mitologia`, `cesarino_2008_oniska`).

Estimated value if consented: unknown volume, but "weekly" over the programme's lifetime. Even
a single year would be ~50 bulletins — likely the largest Marúbo-language speech corpus in
existence outside the archives.

### 3.3 `yt_vimi_marubo` — the community's own everyday video

30 clips, 47 min, 348 subscribers, run by a Marúbo man who cross-links his Facebook and Kwai
accounts. Titles are Portuguese ("Tirando óleo de copaíba", "Nossa roça, aqui tem vários tipos
de plantas", "Essa planta serve para fazer rapé. Alguém conhece nome da planta?"). The last one
is a **question to the audience about a plant name** — evidence of a live, quiz-like
lexical-elicitation dynamic and of a speaker actively seeking vocabulary exchange online.

Register: everyday/ subsistence (roça, copaíba, rapé, trocano, festivals). Zero captions, empty
descriptions on the clips sampled, phone audio. Value: pronunciation and toponyms
(*Maronal*, alto rio Curuçu, igarapé Maronal, rio Javari), plus festival lexis
(*Kenãpaka yavia*, "Festa de Ovo"; *tocanto ako*). This is the most *quotable* small channel and
the easiest consent conversation (single identifiable creator, small audience).

### 3.4 `radio_ebc_alto_solimoes` — regional broadcast, unarchived

FM 96,1 MHz, Tabatinga studio, HLS/AAC 119 kbps, publicly playable. EBC's own station list
confirms it alongside five other Rádio Nacional outlets. No programme archive, no podcast
per-station, no transcript. Whether any slot is in Marúbo is **[U]** — UNIVAJA's statement that
it supplies radio bulletins to *radiofonia* makes it the most likely carrier, and EBC's
"public radio, talk" tagging is consistent with talk-heavy regional programming, but nothing
in this pass proves a Marúbo-language hour. A human should record a week of the stream and
check.

### 3.5 `tiktok_marubo_accounts` — where the language actually is in 2026

Nine or more active accounts posting short Marúbo-life video; `@kena_marubo`'s *"Okê okê 💃🏻"*
is exactly the kind of interjection-heavy, song-adjacent everyday speech that no archive holds.
TikTok's `oembed` endpoint gives author + caption text without login (**[V]** for two items),
but profile enumeration is blocked (1.4 KB stub). This is the highest-density / worst-access
combination in the survey: a consented, screen-recorded sample negotiated with 3-4 creators
would be worth more for pronunciation and code-switching than every documentary here.

---

## 4. Confirmed negatives (with method used)

| # | Negative claim | Method used (2026-10-18) |
|---|---|---|
| N1 | **No Marúbo-language YouTube channel with captions exists.** | Fetched and parsed `youtube.com/results?search_query=` for `marubo`, `marúbo`, `povo marubo`, `aldeia marubo`, `marubo língua indígena`, `marubo cantiga`, `marubo hino`, `marubo starlink internet`, `marubo documentário pajé`, `vale do javari documentário`, `professores marubo escola`, `OAMI marubo ituí`, `Nuqin Nidaid Cudas Nuna`, `Ocondo Podquied`, `Uesnid Bacuëac`, `O manejo está vivo matis`, `MAVis marubo`, `sumaúma marubo`, `new york times marubo`, `matsés aldeia`, `shipibo konibo cantos`; then enumerated `/videos` for `@vimimarubo3341`, `@shapomarubo`, `@raminpamarubo1261`, `@alfredomarubo6697`, `@TrabalhoIndigenista`, `@UNIVAJAOFICIAL`, `@museuaudiovisual`; then read `captions.playerCaptionsTracklistRenderer` on 12 watch pages. Manual tracks found only on 5 CTI/Univaja films; every Marúbo-speaker video had 0 tracks or ASR only. |
| N2 | **Captions are not extractable by an unauthenticated agent.** | Took the `pt-BR` manual track `baseUrl` from `MQy7PZQhQpg`'s player response; requested it with `fmt=json3`, `fmt=vtt` and no format → **0 bytes each**. No retry with token forgery attempted (governance: no bot-check bypass). |
| N3 | **No Marúbo or Panoan podcast** on Apple Podcasts, Deezer, Mixcloud, SoundCloud or the Internet Archive. | `itunes.apple.com/search?term=marubo&entity=podcast&country=BR` (25 results, all homographs: *Le short RTS*, *Brooke and Jeffrey*, *Vozes do Planeta* …); `api.deezer.com/search?q=marubo|javari|matses` (300 hits each, all homographs — the only "Marubo" is a Boi-Bumbá track by *A.F.C.R Tribu Muirapinima*); `api.mixcloud.com/search/?q=…&type=cloudcast` (8/16/20 hits, all homographs *Maru Botana*, *JAVA RIDDIM*, *DJ Matse Dee*); `archive.org/advancedsearch.php` for 6 terms + audio filter (no Marúbo audio). |
| N4 | **SoundCloud search is not usable** without its private `client_id`. | `soundcloud.com/search?q=marubo` returns 72 KB whose `__sc_hydration` blob contains only feature flags — results are client-rendered; no API attempt made (would require extracting an undocumented key). |
| N5 | **No community radio directory lists an Upper-Solimões indigenous station.** | `de1/de2.api.radio-browser.info` name searches for `Tabatinga` (0), `Atalaia` (2, both Portuguese *Rádio Atalaia* in Lisboa), `Benjamin Constant` (0), `Aldeia` (0), `Javari` (connection reset) and tag `indigena`/`indígena` (3, all Mexican INPI stations); `bycountrycodeexact/BR` filtered to `state=Amazonas` (8 stations, none west of Coari/Tefé). Only **Rádio Nacional Alto Solimões** exists. |
| N6 | **No Marúbo-authored blog.** | `medium.com/feed/tag/marubo` → **3 items ever** (1 Italian Starlink piece, 1 2017 post on shamanic word, 1 unrelated); `public-api.wordpress.com/rest/v1.1/read/tags/marubo/posts` → `found: null`. |
| N7 | **Instagram and Facebook are login-gated; Vimeo and X are blocked.** | `instagram.com/kena_marubo/` returns a generic `Instagram` document with no `og:*` metadata (526-591 KB shell); `vimeo.com/search?q=marubo` → **HTTP 403**; TikTok profiles → 1 462-byte stub; `public.api.bsky.app` search → timeouts then **403**. |
| N8 | **No Marúbo title in the 2026 Forumdoc / É Tudo Verdade web catalogues.** | `forumdoc.org.br/?s=marubo` returns the home page with 0 occurrences of "marubo" (site search unsupported); `etudoverdade.com.br/pt/busca?q=marubo` → **404**. Caveat: PDF/printed catalogues not checked. |
| N9 | **Search engines other than YouTube are unusable in this session.** | `html.duckduckgo.com` and `lite.duckduckgo.com` → DuckDuckGo bot challenge ("Select all squares containing a duck", code `aab3`); `mojeek.com` → JS captcha; `startpage.com`, `search.disroot.org` → Anubis; `search.brave.com` → 429; `ecosia.org` → 403; `bing.com` returned a 124 KB page with no parseable result block. Only `old-search.marginalia.nu` answered. All social/blog discovery after ~11:20 therefore ran on **direct fetches + platform APIs + YouTube**, not on general web search — this is the main coverage limit of the lane. |
| N10 | **No Marúbo-language hymn/ scripture audio on YouTube.** | Queried `marubo hino`, `marubo testemunho deus`; results were Boi-Bumbá toadas and unrelated Brazilian gospel channels. (Scripture *text* is lane 04's `scriptureearth_mzr_corpus`; GRN audio is already indexed as `grn_words_of_life_mzr`.) |

---

## 5. Ranking

### Top 3 (ranked for *route to usable Marúbo evidence*, not for immediate use)

**1. `yt_cti_univaja_javari_films` — CTI / UNIVAJA Javari film set (incl. `yt_assim_aprendemos_marubo`)**
3 h 54 min of Marúbo/Matsés/Matis speech; 3 h 20 min with manual pt-BR (+EN/FR) subtitles;
community-produced by Javari filmmakers; two named counterparties (CTI, OAMI/AIMA) with public
contacts. Only place in the lane with human translations and timecodes. Blockers: subtitle
extraction, no Marúbo transcript, ritual sensitivity in the tattoo film.

**2. `univaja_vozes_javari_bulletins` — UNIVAJA "Vozes do Javari" weekly radio/WhatsApp bulletins**
Recurring, modern-register, *self-translated* Marúbo news audio — the register the LKB is
missing and the exact complement to the ritual corpora already indexed. Zero public footprint:
value is entirely in the relationship. If a consent agreement is ever signed, this is the
single largest potential Marúbo speech source in this survey.

**3. `yt_vimi_marubo` — VIMI MARUBO channel**
47 min of everyday Marúbo life, 30 clips, one identifiable creator, freely viewable, active as
of 2024-12. Gives pronunciation, toponyms (`Maronal`, alto rio Curuçu), subsistence and festival
lexis; the "someone know this plant's name?" clip shows live lexical exchange. Zero captions;
phone audio; small audience.

**Runner-up:** `tiktok_marubo_accounts` — highest density of contemporary spoken Marúbo anywhere
in this survey, and the only place with 2026-vintage youth speech; access and consent are the
whole problem.

### Community language workers / counterparties surfaced (relationship leads, not data)

| Person / body | Role as evidenced | Where |
|---|---|---|
| **UNIVAJA** (União dos Povos Indígenas do Vale do Javari), Atalaia do Norte | federation with a communication department; produces the translated bulletins | univaja.org; @UNIVAJAOFICIAL |
| **OAMI** — Organização Marúbo do Rio Ituí | Marúbo member association; co-producer of *Assim Aprendemos* | univaja.org/nossa-base/; CTI film credits |
| **CTI** — Centro de Trabalho Indigenista | ran the Javari audiovisual workshops; holds masters | @TrabalhoIndigenista |
| **Moaci Yora / "Vimi Marúbo"** | runs the most active Marúbo YouTube channel; also on Kwai `@vimi132`, FB `moaci.yora` | `yt_vimi_marubo` |
| **Enoque Marúbo** | leader, Associação Kapyvanaway; interviewed at length on camera; own channel | `yt_ycw_enoque_marubo`, `@shapomarubo` |
| **Beto, Paulo, Talita, Silvana Marúbo; Kena Marúbo** | public Marúbo voices, repeatedly interviewed | SUMAÚMA, Amazônia Real, Fundo Brasil, Roda Viva, TV Cultura, Instagram/TikTok |
| **Javari indigenous communicators' collective** | formed through CTI workshops (2022 report) | `yt_cti_comunicadores_javari` |

---

## 6. What a human has to do next (none of this is agent-actionable)

1. **Ask CTI and OAMI** for the five Javari films' masters *and* their subtitle files, with a
   written licence limited to LKB research use. That single email turns rank 1 from "viewable"
   into "ingestable".
2. **Ask UNIVAJA's "Vozes do Javari"** whether Marúbo-language bulletins can be deposited, and
   under what conditions (they already control the narrative; frame it as deposition, not
   extraction).
3. **Ask two or three TikTok/YouTube creators individually** (`@kena_marubo`, `@vimi132`,
   `@mapocheromarubo`) for a small consented sample — 10-20 minutes each is enough for a
   pronunciation inventory and would be the highest-value-per-minute acquisition in the lane.
4. **Record one week of FM 96,1** and have a Marúbo speaker mark any Marúbo-language segments
   before anything is transcribed.
5. **Do not** ingest the Lionel Rossini / OGM re-uploads, the Turkish `MARUBO KABİLESİ` item, or
   any Boi-Bumbá toada — orphaned or fabricated rights, and in the toada case no Marúbo at all.
6. If anything is deposited: register = `unknown` at best until a speaker says otherwise; the
   Matis tattoo film and any shamanic song are `ritual_restricted`.

---

## 7. Limits of this pass

- **No audio was listened to.** Every "spoken language" claim above is marked **[W]**/**[U]** and
  rests on producer descriptions, titles and channel context. A 30-minute listening pass by a
  Marúbo speaker would convert most **[U]** into **[V]**.
- **General web search died mid-pass** (N9). Social-platform and blog coverage is therefore
  known-incomplete: Facebook groups, Telegram channels and Portuguese-language blogs are
  under-sampled, not proven absent.
- **TikTok was sampled, not surveyed** — 2 of ≥9 accounts verified; volume unknown.
- **Vimeo and X were never read** (403 / login).
- **Festival catalogues** were only checked through their websites, not their PDF catalogues.
