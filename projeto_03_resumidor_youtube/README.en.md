Versão em português: [README.md](README.md)

# Video studio: create videos on any topic, analyze YouTube videos, edit local video, and TACTO Studio Reels

Four modes in the same Streamlit app. Project 03 of the "7 AI Projects to Build in a Weekend" challenge, expanded.

```bash
streamlit run projeto_03_resumidor_youtube/app_youtube.py
```

## Mode "Create video on any topic" (default)

You provide a **context** (a topic, an article, meeting notes, a product description, the summary of a recently analyzed YouTube video) and receive a vertical video (1080x1920, 24 fps, H.264) with neural voiceover in Portuguese.

1. **Script** ([criador_reels.py](criador_reels.py)): AI breaks the context into 3 to 7 scenes and picks, for each one, one of 5 layouts: title, list, animated number, comparison (before/after, myth/fact), or call-to-action with button. You choose duration (15 to 90 s), tone, audience, and call to action.
2. **Editing**: each scene becomes a form with a frame preview; you adjust layout, copy, and narration before rendering. If something is incomplete (a list with 1 item, a button without text), the render button is disabled and indicates what is missing.
3. **Video** ([renderizador_generico.py](renderizador_generico.py)): 5 visual themes, text watermark or uploaded logo, male voice, female voice, or silent video. Subtitles traverse the entire spoken phrase during the scene (in blocks, not word-synchronized).

**Only what is in your context.** The prompt forbids inventing facts, and code verifies it: a highlighted number absent from context is replaced with a simple title, and any other scene number not in context triggers a warning ("verify before publishing"). The context is passed to the model between delimiters as data, and user input cannot close the delimiter.

**Without key** (degraded mode, with warning): text is simply split into scenes in order, without rewriting anything, and the video renders normally. It is less varied and lacks hashtags, but works offline (only voiceover requires internet; "without voice" generates a silent video).

How it was built:
- Text is measured before drawing (size and line count), so it never overflows the card; emojis are stripped from screen (the font would render them as boxes).
- Frames pipe directly to ffmpeg: no thousands of temporary PNGs, and temporary directories are cleaned up even on errors. Rendering takes about 0.8 s per second of video.
- Fonts define fallbacks (Segoe, Arial, DejaVu, Liberation), so tests also run on CI under Linux.

What was verified: 90 automated tests (scene rules, numbers, prompt, each layout across each theme with absurdly long text without overflowing the screen, silent video, and end-to-end simulated voiceover) and a live rendering with neural voice. **Not verified with real Gemini**: the schema is accepted by the SDK, but the quality of scripts written by it (pacing, layout selection, whether it respects numeric bounds) only surfaces with your key.

## Mode "Official TACTO Studio Reels"

The 4 fixed TACTO scenes (marketplace fee, PWA, AI + data, call to action), using the original renderer ([renderizador_video_tacto.py](renderizador_video_tacto.py)), untouched. TACTO also exists as a theme in free mode (palette and logo), to create new branded videos.

## Mode "Analyze YouTube Video" (the e-book project)

Paste a URL and receive, in tabs: **Summary**, **Topics** (each timestamp links to the video position), a 5-question **Quiz** with answer key, **Clips** for Reels, and **Script** — and at the end of the script, the **ready-to-post video**.

- **Map-reduce** ([agente_map_reduce.py](agente_map_reduce.py)): the transcript is chunked by size (without discarding text), summarized **in parallel**, and subsequently synthesized.
- **Context**: video title and channel (YouTube oEmbed, keyless) feed into prompts.
- **Structured output** ([esquemas_video.py](esquemas_video.py)): Pydantic schemas (5 questions with 4 choices and answer key 0 to 3, clips 1 to 180 s, timestamps `MM:SS`). Schemas that fail validation undergo one repair attempt, and become a warning if repair fails.
- **Full transcript** in clips and script (previous version only examined the first few minutes). Only above 300k characters (clips) or 60k (script) is it uniformly sampled across the full video.
- **Degraded mode**: without a key, or if AI fails, each stage specifies that it did NOT come from AI and why. Quiz without AI remains empty (instead of an invented generic question) and the script warns, within its own tab, that it is the TACTO template rather than one based on the video — and in this state it is never used to construct any video.

### Details of the official TACTO renderer

Renders a vertical video (1080x1920, 24 fps, H.264) with pt-BR neural voiceover, animations rendered with Pillow, and ffmpeg assembly ([renderizador_video_tacto.py](renderizador_video_tacto.py)). ffmpeg comes from the `imageio-ffmpeg` package (no hardcoded paths), its exit code is verified, and temporary frames are erased at the end.

**Regarding video metrics**: scene 3 total revenue, order count, and average order value come from Project 05 demo data (completed orders on PWA channel), and the screen displays "demo data". The previous version showed static values never present in the database. The PWA benchmark button remains an illustrative demo (measures nothing) and now clearly states that on screen.

### Clip selection

There are **5 suggestions** per video, starting and ending where sentence boundaries begin and end.

Previously they cut mid-thought, caused by what the AI saw: the prompt took summary chunks, which had **a timestamp every ~44 seconds**, forcing the model to guess clip boundaries within that window. Now the prompt receives individual transcript lines — a timestamp every ~4 seconds — and explicitly requests complete thoughts.

Yet the model still approximates, so a second layer **independent of the model** snaps selected timestamps to sentence boundaries calculated from word-level timings ([legendas.py](legendas.py)). The start steps back up to 10 s to catch sentence beginnings; the end extends until the sentence finishes, without a fixed cutoff — bounded only by the 90 s maximum duration (Reels/TikTok ceiling). Shortening the end cuts content, so it only happens when no upcoming sentence boundary exists and the previous boundary is less than 2 s behind. This also applies to mechanical clips in degraded mode.

Measured across two real videos (18 and 22 minutes): all 10 clips land within 1 second of a sentence boundary on both ends, with durations between 49 and 62 seconds.

### The clip slicer

The clip is generated **without downloading the full video**: yt-dlp retrieves the stream URL and ffmpeg fetches only the requested range via HTTP byte ranges. A 15 s clip in 1080p took 11 seconds and 1.1 MB; 45 s took 40 s.

We do not use yt-dlp's native partial download for a concrete reason: it checks for ffmpeg via `FFmpegFD.available()`, which initializes an unparameterized object and therefore **ignores the `ffmpeg_location` we supply** — yt-dlp's own codebase has a `Fixme` acknowledging this. On machines lacking ffmpeg in system PATH, the check fails and aborts with "ffmpeg is not installed", despite ffmpeg being bundled right alongside. That happened on first live usage.

**Quality** (up to 4K, 1440p, 1080p, 720p, 480p, or 360p, chosen in UI; default is up to 1440p). Initial live usage output 360p, caused not by the requested format, but because code forced `player_client: ["android"]`, which only serves format 18 — 360p with bundled audio. Measured on that video: with `android`, available heights were 144/180/**360**; without forcing client, 144/240/360/480/720/**1080**. Now the first attempt forces no client, keeping `android` as a fallback (it responds when the other fails, albeit in 360p). Above 360p, video and audio arrive in separate streams and ffmpeg muxes them. The selector does **not** pin codec: YouTube H.264 caps at 1080p, and prioritizing it would discard 1440p and 4K (only available in VP9 and AV1) — since clips are re-encoded anyway, resolution matters more than source codec.

YouTube occasionally rejects freshly issued URLs with an intermittent **403** (URLs are signed and bound to the client that generated them). In this scenario, the clip is retried once via a fresh extraction, yielding a fresh signature; only then does an error propagate to the UI.

The clip is re-encoded (`-ss` before `-i` for fast seek, followed by libx264 with CRF 16) to start at the exact requested second rather than the preceding keyframe. Network failures, restricted videos, or ffmpeg errors display clear Portuguese messages on screen rather than tracebacks.

### Ready-to-post video (in Script tab)

The tab previously delivered a text script. Now it assembles the full piece: **the 9:16 formatted clip + an end card inviting viewers to follow**, in a single `.mp4`, alongside publication title and description ([editor_reels.py](editor_reels.py), [publicacao.py](publicacao.py)).

**Full video over blurred background** is default, for image quality reasons: this *downscales* the image (16:9 becomes 1080x607), and downscaling remains sharp. The background is the video itself scaled up, blurred, and darkened — no black bars and no colored outlines: blur separates image from background, whereas borders would mark the piece as a template. *Full screen* mode exists for talking-head content, but incurs the tradeoffs described below.

Without header text, video shifts up and spans full width — 1080x607 instead of 1000x562, an 8% increase in size and resolution. With a title or badge, it shifts down to avoid collision.

**By default, only video and subtitles.** Title, badge, branding, subtitle background box, progress bar, intro card, and end card exist, but all default to disabled — in live testing, a black box over video and a fixed badge hindered more than helped. Subtitles sit directly over the image, with a 7 px text stroke maintaining legibility over any background without occluding footage. An empty art layer is never fed into ffmpeg.

### Subtitles ([legendas.py](legendas.py))

YouTube caption files arrive in ~3 s chunks bearing no correlation to sentences. The initial version used these chunks as-is, resulting in three defects measured on the same clip:

- **captions lingered after speech ended** — "e baixar o código…" spoken from 0.00 to 3.77 s persisted until 5.07 s, because chunks stretched to the next to prevent flickering;
- **large chunks were not broken up** — word limits only prevented *merging*, so a 12-word chunk became a 12-word caption;
- **blocks started mid-clause in lowercase**, matching file splits rather than grammatical sentences.

Now **each word receives its own timestamp**: chunk duration is distributed proportionally by word character length. It is accurate to fractions of a second, avoiding the 2-second offset of full chunks. Overlapping chunks (common in auto-captions) are trimmed at the start of the next, and split words are handled cleanly.

With word timings, blocks break where speech breaks: sentence ends, pauses longer than 0.7 s, or thresholds of 12 words and 4 s. Remaining large blocks are split into **equal** halves (10 words become 5+5, not 8+2). Each block disappears 0.5 s after its last word, never reaching the next — keeping silences caption-free, as they should be.

Limits were established through measurement: at 8 words/3 s, the test passage became 16 blocks averaging 1.8 s, too fast to read; at 12 words/4 s, it yielded 9 blocks averaging 3.2 s.

**Then aligned with professional standards** ([Netflix Brazilian Portuguese Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215600497-Brazilian-Portuguese-Timed-Text-Style-Guide) and [general requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)): maximum **2 lines**, each caption on screen between **5/6 s and 7 s**, breaking after punctuation or before conjunctions/prepositions — never splitting articles from nouns, nor negation/pronouns from verbs. What changed, and what each change resolved:

- **Long sentences break at syntactic boundaries**, not where time limits ran out. Previously: "tá na hora da gente ter uma última" in one block and "conversa." isolated in the next. Now: "Senhor Rengoku, / tá na hora da gente ter uma última conversa.". Time ceiling per block rose from 4 to 6 s: at 4, "enquanto você se afoga em tristeza." (slow speech, 5 s) became "enquanto você / se afoga", splitting subject from verb.
- **Line breaks follow the same rules.** Across 84 real captions, instances of line 1 ending in an article, preposition, or conjunction dropped from 29 to 3 ("Entre o céu e a terra, / sou o mais honrado.").
- **Stretched blocks exit based on reading speed.** An auto-caption chunk spanning 8 s of music kept "Está me superestimando." on screen for 8.8 s; now, when speech pacing drops below natural rates (< 6 characters/second), the block exits with comfortable reading buffer — 4.1 s in that case. Truly slow speech is preserved.
- **Short text is not fragmented by time** ("Está / me / superestimando." across three blocks) and **sentence openings truncated by clip boundaries vanish** ("Se" stranded alone).
- **Auto-caption markers are removed** ("[Música]", "[Aplausos]", music notes), along with unrenderable glyphs (Korean artifacts embedded in Portuguese text).

**Timing was measured against voice**, filtering audio in the speech band: in clean dialogue (Rengoku farewell), block starts matched voice onset within 0.15 s for the vast majority. Measurement degrades under loud music sharing the same frequency range. The remaining limitation was **word-by-word highlighting**: individual word timing was estimated from character length — resolved by local speech recognition below.

### Local speech recognition ([fala_local.py](fala_local.py))

The [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`small` model, ~480 MB, downloaded on first use to Hugging Face cache) runs on CPU, with zero marginal cost. Three use cases:

**1. Word-level timing measured directly from audio.** Measured against ground truth — the app's neural voice (edge-tts) reporting exact timestamps for each word; 55 words across 4 sentences, captions in 3 s YouTube-like chunks:

| | average error | 90% of words within | worst case |
|---|---|---|---|
| character length estimate | 0.118 s | 0.230 s | 0.952 s |
| whisper, clean audio | 0.048 s | 0.090 s | 0.303 s |
| whisper, heavy background noise | 0.050 s | 0.102 s | 0.316 s |

Synthetic speech maintains steady cadence, favoring length estimation; in natural speech with mid-sentence pauses, the gap widens.

**However, text does not originate from Whisper.** In dubbed clips, it failed where YouTube captions succeeded: "Lengoku", "Chugue as lágrimas", "Está-me superestido", "rio Harabara" instead of Yhwach. Text remains sourced from transcript (or `.srt`, or AI), while Whisper provides only the clock: both sequences are **aligned** word by word (character by character in Japanese and Chinese). Matching words inherit audio timestamps; substituted words ("Ele" in text, "Leng" in audio) take the timing of the audio word at that position; words Whisper missed anchor to neighbors with natural duration. Three alignment revisions were benchmarked on real clips: the first drifted missed words across silence ("Mamãe" appeared 8 s early), the second stretched substituted words over 3 s silences ("superestimando" across 4.3 s). On Rengoku, Aizen, and Ichigo (Japanese) clips, 86%, 92%, and 82% of words found matches; below 40%, text and audio diverge and estimated timing is retained. The UI displays the match percentage after assembly.

All three screens provide a "Synchronize subtitles with audio" checkbox, enabled by default. Costs time, not money: ~half the clip's duration (43 s of speech in 15 to 24 s on a 12-core CPU). Results are cached per clip: re-rendering does not re-listen.

**2. Videos with disabled YouTube subtitles.** A button transcribes the full video locally, allowing analysis to proceed normally. Measured on a live video: 4.4 min of audio downloaded in 4 s, first minute transcribed in 23 s — entire video in ~1.7 min. Word timings are saved alongside, avoiding re-transcribing for clip subtitles.

**3. Subtitle source in local editor**, free, alongside `.srt` and AI transcription — which can also sync to audio. Whisper's detected language determines whether translation is required.

Japanese and Chinese lack spaces between words: an entire Japanese caption chunk previously became a single 13 s "word". Now each clause (split on 、。！？) is a unit, and full-width punctuation closes sentences.

**With an API key, AI re-punctuates and segments better** — returning, for each block, the start and end word indices it spans. Timestamps remain anchored to audio, not hallucinated by the model. If indices fail to cover all words sequentially without overlap, the entire revision is rejected, falling back to mechanical segmentation: an invalid index would desynchronize subtitles across the whole video. The prompt forbids summarizing or altering words — it is the speaker's verbatim voice — and transcripts are stripped of `<` and `>` to prevent delimiter escapes.

**Regarding image sharpness.** In full-screen mode, 16:9 video loses 68% of width and the center third is magnified **1.78x** to fill 1080x1920 — this is framing math, not codec settings, and caused initial softness. Countermeasures implemented: request highest possible source resolution (at 1440p scale drops to 1.33x; at 4K it downscales), upscale with **lanczos** instead of default bicubic, restore edges via **unsharp** — applied strictly when upscaling to avoid artifacts — and minimize generation loss by encoding clips at CRF 16 and final output at CRF 18 on `medium` preset. On a 6 s clip, this added 3 s of compute.

**Nothing important below y=1500.** Instagram and TikTok overlay usernames, post captions, and action buttons across the bottom fifth of the screen. Subtitles terminate at y=1500 and the progress bar sits immediately below, inset within card margins — spanning edge-to-edge previously made it read as a border.

**Output filenames reflect the video title**, rather than YouTube IDs: `como_a_rede_neural_enxerga_um_numero_corte1_20260920_143022.mp4` instead of `reels_aircAruvnKk_1_pt_20260920_143022.mp4`. Filenames derive from the post title — which, without a key, defaults to the analyzed video title. Clip index distinguishes the three cuts from a video, timestamps prevent overwriting earlier assemblies, and language codes appear only when multiple are generated. Accompanying `.srt` files share the name.

**Publishing**: a field specifies handles to mention, and AI generates title, description, hashtags, and end-card text from video summary and selected clip dialogue — the follow prompt ties directly into content rather than boilerplate copy. Without a key, title matches video name, description uses summary lead, and end card uses simple template ("Siga @conta para mais"); zero hashtags are invented.

**Multiple languages**: each selected language renders its own video with title, end card, and subtitles translated in a single model call, plus a `.srt`. Why one video per language rather than multi-track subtitles: **Instagram and TikTok discard embedded subtitle tracks** — subtitles must be burned in, meaning regional variations require separate video files. YouTube and Facebook support `.srt` and auto-select by viewer language. Limited to Latin-script languages (pt, en, es, fr, de, it): packaged fonts lack glyphs for Japanese, Chinese, Korean, Arabic, and Hebrew — rendering empty boxes per character. Translations with mismatched text counts are rejected entirely, outputting original language with a warning: partial translations would desynchronize captions across the entire video.

Intro and outro cards are optional and **default to off**: each adds frame-by-frame rendering, voiceover, and an additional concatenation step, which didn't justify the cost in real usage. Without either, the processed clip is the final video — bypassing concatenation completely. Without button text, outro cards render plain text instead of duplicating it in a button box. All copy is editable prior to generation.

**Degraded scripts never enter the video.** Without a key (or if AI fails on this step alone), `gerar_roteiro_viral` falls back to TACTO Studio's static template script. In the tab, it displays as text with an explicit warning noting it does not describe the analyzed video; in the video itself, it would burn another company's advertising over creator content — which occurred during early testing. The intro card, which is the only element that would consume it, starts with the clip title and leaves the rest blank.

How it was built: elements static across frames are rendered **once** via Pillow and fed to ffmpeg as transparent PNGs (subtitles as timed PNG image streams — see Art direction). Rendering frame-by-frame would cost ~9 MB RGBA per frame in the pipeline for the same outcome. Background blur computes at 1/4 resolution before upscaling — identical blur quality, reducing 15 s clip processing from 23 s to 5 s. Segments originate from the same encoder settings, allowing stream copy without recompression (falling back to re-encoding if parameters diverge).

Verified: 128 automated tests (end-to-end ffmpeg renders, silent clips, both framings, `.srt` generation, degraded script rejection, and all translation paths) and live renders — 45 s 1080p YouTube clip, 13 subtitle blocks from live transcript, neural voiceover on outro card, and English variant with swapped text.

### Tab "Editing": multiple segments in one piece

The slicer grabs a continuous segment and hopes the topic fits. The editing tab acts like an editor: AI reviews the full video and selects 2 to 6 segments from **different moments** — hook from one part, example from another, conclusion from a third — spliced together seamlessly ([edicao.py](edicao.py), [ui_edicao.py](ui_edicao.py)).

The prompt asks for what defines whether the piece works: combined segments must tell **a single idea from start to finish**, without relying on external context — no unreferenced "as I said" pointing to omitted parts. You can specify an angle ("practical steps only, omitting theory") and target duration.

**The plan is presented for review, not direct execution.** The UI displays each segment with its speech transcript, editable timestamps, and a discard toggle. Assembly is a separate click — selecting which segments make the cut defines the piece, and that remains your decision.

Once selected, segments snap to sentence boundaries like the slicer, with one adjustment: segments can expand by at most 50% beyond requested length. In single clips, extending 15 s to finish a sentence is acceptable; across four segments, that doubled overall duration in early benchmarks (45 s requested became 72 s). Segments that touch after snapping merge into one to prevent repeating audio.

Each segment is reframed and subtitled independently, and the final `.srt` accumulates offsets: segment 3 captions account for segment 1 and 2 durations.

**Without a key, segments are distributed evenly across timestamps**, and the UI notes this: there is no semantic understanding, and pretending otherwise would be misleading. True value here depends on an active key.

Transitions between segments default to hard cuts, with animated transitions available — see Art direction. What it does **not** do: background music, sound effects, and speech pause removal. Each is an independent challenge, and none impact results as much as good segment selection.

Verified with real video: 3 segments (at 4s, 519s, and 1071s of the same video) formed a 51 s video in 22 s assembly time, with captions crossing cuts at correct timestamps.

### Source video watermark

The app **adds zero watermarks**: header branding is optional and defaults to off. It handles watermarks already burned into source video, defaulting to **detecting and removing them** ([marca_dagua.py](marca_dagua.py)). Results display on screen post-assembly: bounding box coordinates or a notice that none were found.

**How detection works.** Watermark contours remain static across frames; video content does not. 40 frames distributed across the clip are sampled, computing signed pixel differences between neighbors. Taking temporal medians filters changing content, preserving static edges (method from Dekel et al., CVPR 2017). Candidate regions are filtered by watermark heuristics: not long horizontal lines (letterbox edges), not oversized, not centered, containing internal structure. Adjacent regions — icon, text, separator — merge into a single bounding box.

**The initial version failed on the first live video**, motivating the methodological change. It tracked *static pixels*; the watermark "YOUTUBE | BLEACH BRASILEIRO" was semi-transparent, so moving background made pixels vary as much as the rest, and it sat offset from corners — out of reach for corner boxes. Gradient medians do not require static pixels, only static edge locations.

**Measured across 17 real clips from 5 videos:** watermarks were identified in all 6 clips containing them, yielding identical bounding boxes, while the 11 watermark-free clips produced zero false positives. Bounding boxes underwent two calibrated fixes: in a short, static clip, content contours touched the watermark, doubling box height (weak elongated tails are now trimmed); over-trimming caused the watermark's vertical stroke to land on the edge, causing `delogo` to smear it across the frame (short protrusions are now preserved). Search takes 2 to 4 s per clip.

**Limitations.** Small sample size on one content type (anime). On synthetic noise backgrounds, false positives occur — documented in tests. Static video (constant still image) cannot separate watermark from content, and search aborts rather than guessing. Moving watermarks (like TikTok's floating logo) have not been tested. And `delogo` **does not reconstruct** underlying imagery: on flat backgrounds watermarks disappear, but complex textures leave a blur.

For this reason, the UI includes a **single-frame preview**: showing original frame with red bounding box alongside the processed frame in seconds. If the box misses, "I'll mark the position" opens manual coordinate sliders pre-filled with detected coordinates.

### Art direction ([efeitos.py](efeitos.py))

Across the three assembly tabs (ready video, Editing, and local editor):

- **Color filters**: vivid, neon, cinema (blue shadows, warm highlights), warm, cold, dramatic, vintage, black & white. Selected by evaluating contact sheets of identical frames across two live videos; none default to on.
- **Emphasis zoom**: punches in on sentence changes and resets on the next (subtle 8%, pronounced 18%). Without subtitles, alternates every 3 s. Zoom applies solely to the video window — subtitles and framing overlays do not scale.
- **Vignette** (darkened borders).
- **Subtitle styles**: classic (full sentence), highlighted word (karaoke, theme color), and impact (up to 3 uppercase words updating with speech tempo).
- **Segment transitions** (Editing tab only): fade, white flash, black dip, slide, zoom, wipe circle, blur — ffmpeg `xfade` with crossfaded audio. Subtitles and `.srt` offset for transition overlap durations.

**Measured performance shaped architecture.** On 12 s of 1080p 50fps clip (bare video took 3.7 s): film grain added 33 to 41 s — tripling render time, so it was dropped; "cinema" filter via `colorbalance` added 11 s; ffmpeg vignette added 5 s. Three optimizations: input video conforms to output framerate (24 fps) upfront rather than processing 50 frames only to drop half; color curves apply **after** downscaling (foreground 1080x607, background 270x480) via per-channel lookup tables rather than per-pixel expressions; vignette became a single pre-rendered PNG. With **all effects enabled** — watermark removal, cinema filter, vignette, zoom, and karaoke subtitles — the same 12 s render in 6.3 s. A full 50 s clip dropped from 90 s to 40 s, watermark search included.

**Subtitles converted into image streams.** Each subtitle state (a block, or a block highlighting word N) is a PNG, sequenced via ffmpeg's `concat` demuxer with display durations. ffmpeg sees a single video input with a single overlay. Previously, each block was an independent input and filter overlay — viable for 15 blocks, but unusable for karaoke with ~150 word states per minute.

### Anime situation presets ([efeitos.py](efeitos.py), [momentos.py](momentos.py))

The top selector in art direction is the **preset**: fight, aura/character entrance, emotional/farewell, comedy/reaction, and dialogue — or "custom", exposing individual controls. Each preset bundles what an editor would apply to that scene type:

| Preset | What it does |
|---|---|
| Fight | inverted frame on hits, white flash, RGB-split shake and zoom; strongest hit in slow motion; impact subtitles; flash transitions |
| Aura | darkened red-shifted palette, bloom on highlights, cinematic bars, vignette; occasional red-flash hits; slow motion on peak action |
| Emotion | muted desaturated tones, soft bloom, cinematic bars, vignette; no hit effects, shake, or zoom; classic subtitles; crossfade transitions |
| Comedy | rapid zoom on audio spikes (reaction punch), subtle shake, saturated colors |
| Dialogue | vivid colors, subtle zoom per sentence, active spoken word highlighted |

**References** (researched September 2026): short-form pacing guides — cut every 1.5–3 s on TikTok and 2.5–4 s on Reels, hook in first 3 seconds ([Shortzly](https://shortzly.com/blog/short-form-video-pacing-editing-guide)); action vs. emotional scene pacing — quick cuts for tension, held shots for emotional weight ([Inside the Edit](https://www.insidetheedit.com/blog/pacing-in-video-editing)); CapCut anime edit effects — velocity, flash, shake, reverse ([CapCut](https://www.capcut.com/explore/velocity-x-flash-x-shake-x-reverse)), RGB split and motion blur in fights ([Toolify, CapCut anime editing tutorial](https://www.toolify.ai/ai-news/capcut-tutorial-creating-stunning-animestyle-video-edits-3634198)); slow motion tied to impacts rather than arbitrary timestamps ([Northwest Media Systems](https://northwestmediasystems.com/blog/speed-ramping-time-remapping-corporate-video/)); and impact frames — brief monochromatic or inverted frames used in anime during climax impacts ([Sakugabooru](https://blog.sakugabooru.com/glossary/impact-frames/)). Preset parameters (impacts per minute, shake intensity, 2 impact frames, half speed) were tuned by visually inspecting real clips, not copied verbatim from sources.

**Effects trigger on impacts, not clocks.** [momentos.py](momentos.py) detects, without AI, audio spikes (+8 dB in 100 ms up to -20 dBFS) and shot cuts (large difference between consecutive frames); impacts coinciding with shot changes receive higher weight. The first version compared volume to the clip's median, causing Rengoku's whispered farewell to register 50 "impacts" per minute: every sentence onset triggered it. With absolute thresholds, it registered zero. This succeeds because YouTube normalizes audio loudness.

**Measured on 14 real clips across 5 videos:** fights had 36 to 59 shot cuts per minute (except one slower clip with 13); Aizen's monologue had 16 to 30; Rengoku's farewell had 24 at much lower volume. Previews use this to **suggest** a preset — fights suggest "Fight" (5 of 6), farewell suggests "Emotion", Aizen suggests "Dialogue, try Aura". This is a heuristic from 14 clips, and the UI labels it as such.

**Slow motion**: slightly over 1 s around the strongest impact at half speed; audio stretches using `atempo` without pitch distortion. All timed elements — subtitles, words, impacts, zoom windows, `.srt` — remap to the new timeline, extending video duration by 1.2 s. Anime is animated at 8–12 frames per second, so half speed duplicates frames; frame interpolation (`minterpolate`) would be far slower.

**Three visual bugs identified and fixed**: additive RGB brightness left an 8 px purple artifact on the right edge when color filters preceded it (additive blend now operates strictly on luminance); RGB split on final output caused a thin blue line at borders (split now runs on oversized image prior to cropping); and preview crashed with slow motion enabled due to unbound audio output (preview is silent).

**Compute**: fight preset renders 25 s of 1440p clip in ~25 s; aura takes ~32 s for 40 s; emotion ~30 s for 43 s — including impact detection (2 to 7 s per clip).

Omitted features: **continuous slow zoom** — ffmpeg's `zoompan` jitters (rounds position to integer pixels per frame) while `scale` with frame expressions drifts horizontally (subsequent `crop` calculates center once); both were tested. Also omitted: film grain (compute cost), random shake, variable speed curves, and background music.

### Local video editor and other platforms ([ui_local.py](ui_local.py), [fonte_local.py](fonte_local.py))

A fourth mode that bypasses analysis: **local files** (mp4, mov, mkv, webm, m4v, avi, up to 2 GB — Streamlit limit increased in `.streamlit/config.toml`) or **links from other platforms**. Same compositor, same art direction, same watermark detection, and same preview. From links, only the chosen range downloads; from local files, it cuts at exact timestamps. Files reside in `videos_locais/` outside git, hashed to prevent duplicate uploads.

**Platform compatibility**, tested 2026-09-21 reading metadata and duration with public test videos from yt-dlp's test suite (version 2026.08.19, 1,751 extractors): **functional**: Dailymotion, Reddit, Twitch clips, and public Facebook videos; **required login**: Vimeo and Instagram; **TikTok** returned "your IP is blocked for this post" across 2 tested posts from this connection. yt-dlp can import browser cookies for login-walled sites, but exposing user session tokens to external scripts is deliberately avoided. For those sites, download via official apps and upload as files. Live video downloads were tested only on YouTube.

**Subtitles default to disabled here** (content from other platforms usually arrives subtitled) and support two sources: a **`.srt`** file (timestamps trimmed to clip boundaries; handles BOM, CRLF, comma/period milliseconds, strips `<i>` and `{\an8}`) or **AI audio transcription** — audio extracts in low-bitrate mono (1 min ≈ 360 KB) and returns timed segments. Out-of-bounds timestamps are dropped, not adjusted. **Not verified with a live API key**: segment timestamps represent what the model reported hearing; if subtitles lead or lag, next step is local speech recognition with word timings (faster-whisper), accurate and free, but requiring ~500 MB model download.

**Subtitles are an explicit choice across all three screens, displaying associated costs:**

| Speech language | Options |
|---|---|
| Portuguese | AI-reviewed (1 call) · as-is, without AI (zero cost) · do not generate |
| Other language | translated to Portuguese (1 call) · in spoken language, without AI (if font supports glyphs) · do not generate |

"As-is" keeps YouTube text untouched — default in offline mode. For translation, subtitles do **not** undergo prior review: translated text is already punctuated, and reviewing beforehand would double API costs. "Do not generate" handles videos with burned-in subtitles: nothing renders over them, and **cinematic letterboxing is disabled** because cropping to 2.39:1 cuts off bottom-third subtitles.

A bug previously prevented this: translation was skipped when the destination was Portuguese, assuming speech was already Portuguese. Ichigo's clip with Japanese transcripts would have rendered Japanese subtitles — which the font cannot draw, resulting in empty boxes. Spoken language is now stored during analysis, "spoken language" option hides when glyphs lack font support, and translation errors suppress subtitles with a warning instead of rendering boxes. In the same audit, YouTube auto-captions on Rengoku's fight in Portuguese contained Korean junk characters ("가사주"), which also rendered as boxes; unsupported glyphs are now sanitized prior to drawing.

The local editor lacks language metadata (speech comes from `.srt` or transcription): Portuguese-specific vocabulary heuristics prevent translating Portuguese to Portuguese. Correctly identified all 16 Portuguese `.srt` files on disk while rejecting English, Spanish, French, German, and Italian test samples. In the local editor, neither `.srt` nor transcription undergoes AI review: the former is pre-formatted, the latter arrives punctuated.

**Videos with disabled YouTube subtitles.** Analysis (summary, clips, script) relies on spoken transcript; without subtitles, there is nothing to analyze. Previously, library error strings surfaced in English. Now distinct Portuguese messages cover each case — disabled subtitles, unavailable video, age restrictions, rate limiting — and when captions are absent, two solutions exist: transcribe locally on CPU and analyze normally, or load link into the local editor, which operates without analysis.

### Breakdown of costs

Gemini 3.6 Flash paid tier prices verified 2026-09-21 in [official pricing](https://ai.google.dev/gemini-api/docs/pricing): US$ 0.75 per million input tokens and US$ 3.75 per million output tokens — **both double on 2027-01-01**. Audio bills at text rates and counts [32 tokens per second](https://ai.google.dev/gemini-api/docs/audio). Model "thinking" bills as output and cannot be predicted; ranges below assume 300 to 1,500 thinking tokens per call. Token counts measured on a real 50 s clip (74 words), estimated at ~4 characters per token.

| Item | Calls | Approximate cost |
|---|---|---|
| Download, slice, watermark removal, presets, effects, preview, assembly, card voiceovers | 0 | zero (runs locally; voice via free edge-tts) |
| Subtitles "as-is", `.srt`, "do not generate" | 0 | zero |
| Review subtitles for 50 s clip | 1 | US$ 0.003 to 0.007 |
| Translate subtitles for 50 s clip | 1 | US$ 0.002 to 0.006 |
| Local speech recognition (sync, local editor, video without captions) | 0 | zero — costs compute: ~half audio duration |
| Transcribe 50 s audio via AI (local editor) | 1 | US$ 0.003 to 0.008 |
| "Write with AI" (title, description, hashtags) | 1 | US$ 0.002 to 0.007 |
| Plan Editing (video ~10 min) | 1 | US$ 0.004 to 0.009 |
| Analyze video up to ~15 min (summary, quiz, clips, script) | ~5 | measured on your account: US$ 0.0323 |

The app sidebar displays actual session spend (input, output, and thinking tokens). Repeating identical text requests incurs no cost (caching); audio transcription bypasses cache but persists within the session so preview and render steps do not pay twice.

## Copyright

The clip slicer downloads third-party video segments for reuse. Use with your own or licensed content.

## Known limitations

Local speech recognition (`small` model) struggles with proper nouns and unusual words — which is why it only supplies timestamps when text already exists; on videos without captions, it provides transcript text directly. AI audio transcription was not verified with a live key. Auto-captions lack punctuation and are not cleaned prior to summarization. On cards, subtitles display scene copy in blocks, not word-synchronized. Without audio synchronization (disabled, or audio-text mismatch), word timing is **estimated** from character count — and word highlights may drift slightly from audio. Framing crop is fixed center (does not track speakers). Translation applies to screen text and subtitles, not audio: speaker voice remains original (outro card voiceover matches selected language). Hashtags remain identical across all languages. Official TACTO renderer uses 4 fixed scenes (not data-driven).
