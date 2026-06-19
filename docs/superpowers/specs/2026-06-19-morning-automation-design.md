# Morning Automation Design

Date: 2026-06-19
Status: Approved design draft
Scope: QuickKick daily Elvis video pipeline

## Goal

Turn the current morning pipeline into a reliable `9:00 AM` daily automation that:

- pulls the newest Elvis topic or production doc from Google Drive
- selects Elvis images that match the script closely
- restores, upscales, and normalizes those images to vertical video assets
- renders the short with subtle motion and transitions
- pauses for Telegram approval if even one scene has a weak image match
- uploads to YouTube only after the image set is acceptable

## Current State

- `\QuickKickMorningRunner` is currently scheduled in Windows Task Scheduler for `10:00 AM` daily.
- `morning_runner.py` already pulls the newest recent topic or production doc from Google Drive and runs the local pipeline.
- `main.py` already supports Ezra via ElevenLabs and skips thumbnails for videos under `120` seconds.
- Local Elvis image selection already uses CLIP matching through `clip_selector.py`.
- Video assembly currently uses static hard cuts with no crossfades or Ken Burns motion.
- The current upscale flow depends on OpenAI image edits and can fail when OpenAI credits are exhausted.

## Approved Product Decisions

- Schedule: run every day at `9:00 AM`
- Voice: ElevenLabs `Ezra`
- Thumbnail rule: no thumbnail for videos under `2` minutes
- Image count: hybrid model with a minimum of `5`
- Time density: target about `1` image every `3` to `5` seconds
- Scene gating: pause if even one selected scene image is weak
- Weak-match behavior: send Telegram preview, pause, and wait for approval
- Approval channel: Telegram via `@TheKingLives_bot`
- Approval timeout: auto-cancel after `10` minutes with no approval
- Approval action: on `approve`, rescan Drive once before final selection
- Search scope: all of Google Drive
- Searchable media: both regular image files and zip files containing images
- Reuse destination: save approved/upscaled finds locally and copy them to Drive folder `Elvis Approved Images`
- Motion style for now: subtle crossfade plus slow Ken Burns pan and zoom
- Upscale fallback: if OpenAI restore/upscale is unavailable due to credits or quota, use an OpenRouter-backed image enhancement fallback

## Recommended Architecture

Use a tiered local-first matcher with explicit approval gating.

Why this approach:

- it preserves fast local reuse for most morning runs
- it can broaden to all of Google Drive when the local pool is not enough
- it gives a deterministic stop before weak visuals are uploaded
- it lets the image pool improve over time through approved caching

Rejected alternatives:

- Drive-first every run: too slow and too brittle for a time-based morning publish
- prebuilt-library only: fast, but it will not benefit from newly added Drive images unless rebuilt manually

## End-to-End Workflow

### 1. Scheduler

Windows Task Scheduler starts `\QuickKickMorningRunner` at `9:00 AM` every day.

The task continues to use the existing once-per-day lock behavior so it cannot double-post.

### 2. Script Intake

`morning_runner.py` fetches the newest eligible topic or production doc from the configured Drive workflow.

Input rules:

- if the file is a production doc, use its script and scene breakdown directly
- otherwise, use the topic and let the pipeline generate the narration and scenes

If no eligible file is found, the run stops and sends a Telegram failure notice.

### 3. Image Planning

The pipeline determines how many images are needed.

Rules:

- use scene count when a valid scene breakdown is available
- otherwise estimate count from narration duration
- if scene count exists but is lower than the `1 image every 3 to 5 seconds` target, split long scenes into additional visual beats until the target density is reached
- target about `1` image every `3` to `5` seconds
- never use fewer than `5` images

This is a hybrid strategy: scene-based first, time-based fallback second.

### 4. Tiered Image Matching

For each scene, the pipeline computes the best Elvis image match using a scored tiered search:

1. local restored pool
2. local cache of previously approved images
3. Drive folder `Elvis Approved Images`
4. all regular image files across Google Drive
5. images extracted from zip files found across Google Drive

Scene text used for matching should prefer:

1. narration line for the scene
2. visual direction if available
3. topic-derived fallback text if neither is present

The matcher should return, for each scene:

- selected image candidate
- confidence score
- candidate source tier
- fallback candidates for audit and debug

### 5. Weak-Match Gate

If any single scene score falls below the configured weak-match threshold, the run must pause before upload.

Pause behavior:

- generate a full contact-sheet preview of the selected image set
- send a Telegram alert through `@TheKingLives_bot`
- include the weak scene number, score summary, and brief reason
- wait up to `10` minutes for a reply

Telegram decision rules:

- if user replies `approve`, rescan Drive once, rerun image matching, and continue with the best available refreshed image set even if one or more scenes are still weak, because the user explicitly approved the run
- if no reply arrives within `10` minutes, cancel the run
- if Telegram delivery fails, cancel the run rather than upload a weak set silently

### 6. Image Prep

Selected images must be normalized into ready-to-render portrait assets.

Pipeline rules:

- restore/upscale when needed
- normalize to `1080x1920`
- preserve the existing vintage-photo restoration prompt behavior where applicable
- avoid over-smoothing or unnatural faces

Provider order:

1. primary: OpenAI image edit / enhancement path
2. fallback: OpenRouter-backed image-edit or enhancement model

Important note:

- OpenRouter is not a drop-in equivalent to the current OpenAI edit path, so this fallback should be implemented as a separate provider path with its own prompt and response handling

### 7. Reuse And Curation

When a non-local image is selected and approved:

- store a local cached copy for future fast matching
- copy the curated result into Drive folder `Elvis Approved Images`

This creates a growing approved Elvis pool that should improve future daily runs.

### 8. Motion Rendering

Replace the current static hard-cut assembly with subtle motion.

Motion rules for the first version:

- slow Ken Burns pan and zoom on stills
- light crossfade between consecutive images
- keep transitions understated and consistent
- preserve current vertical output format and YouTube-ready mp4 generation

The intent is to improve polish without making the edit style distracting.

### 9. Upload

If the run passes matching and approval gates:

- generate narration with ElevenLabs `Ezra`
- assemble the video
- skip thumbnail generation for videos under `120` seconds
- upload to YouTube as `private`
- notify success via Telegram

## Data And State

### Local

Expected local state additions:

- cached approved image directory
- preview contact-sheet output
- weak-match run state for pause/resume
- provider metadata for which upscale path was used
- selection audit log per run

### Google Drive

Expected Drive state additions:

- curated folder `Elvis Approved Images`
- optional temporary extraction cache for Drive zip processing if needed by implementation

## Failure Handling

The run must fail safely without uploading when any of these occur:

- no recent topic or production doc found
- weak scene match not approved within `10` minutes
- Telegram approval alert cannot be delivered for a weak-match pause
- both OpenAI and OpenRouter upscale paths fail
- image search cannot produce the minimum required image set

Each failure path should write a clear local run record and send a Telegram message when possible.

## Testing Plan

Test the implementation in three passes before switching the live daily workflow:

1. Strong-match run
   - topic has clear supporting Elvis images
   - run completes automatically and uploads

2. Weak-scene run
   - force at least one weak scene
   - verify Telegram contact-sheet alert
   - verify `approve` triggers one final rescan and then resumes correctly

3. Provider-fallback run
   - simulate OpenAI image-edit quota failure
   - verify OpenRouter fallback performs the restore/upscale path
   - verify the run still completes

## Open Implementation Constraints

- `C:\Users\erick\quickkick-bot` is not currently a git repository, so this design document can be saved locally but cannot be committed until the project is moved into or initialized as a git repo.
- OpenRouter fallback quality may differ from OpenAI, so provider-specific thresholds and validation may be needed.
- Full Drive-wide image and zip search will be slower than local matching, so caching and indexing should be treated as part of the implementation.

## Success Criteria

The project is successful when:

- the task runs automatically at `9:00 AM` daily
- image count scales correctly with narration length using the hybrid rule
- images match the script closely enough that weak matches are rare
- even one weak scene pauses the run before upload
- Telegram shows a full image preview and supports `approve`
- approved images become part of the reusable pool
- videos render with subtle crossfade and Ken Burns motion
- the system still produces a finished private YouTube upload without manual intervention on strong-match days
