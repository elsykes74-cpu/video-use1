# MJ TikTok / Shorts -- Project Template

Copy this file to your-mj-videos-folder/edit/project.md before your first session.
Then run claude in that folder and say "let's make a video".

Emulates presets/elvis-youtube.md. Does not modify the Elvis preset or workflow doc.

## Project context

Channel: Michael Jackson tribute / facts channel -- TikTok (mjforeverlove0) plus YouTube Shorts
Target format: vertical short-form, 1080x1920 @ 30fps, -14 LUFS normalized
Target runtime: 70 seconds (1:10)

Source material types: archival MJ photos by decade stored in Drive under MJ Videos / Reference Images by Decade, concert or performance clips where rights allow, and Gemini-generated mood and B-roll only such as stages, lighting, fashion, and crowd shots -- no AI-generated MJ face, matching the design already in mj-niche.yaml.

## Workflow defaults for this channel

Color grade: matches mj-niche.yaml visual.prompt_suffix -- vibrant 1980s aesthetic, neon lighting, high contrast, bold saturated colors. Use auto per-segment for archival photos with inconsistent exposure.

Subtitles: bold-overlay, 2-word uppercase chunks, matching the caption style already live on the TikTok channel. Highlight color hex FFFFFF from mj-niche.yaml.

Still photos to video clips: use helpers/ken_burns.py on every archival photo before adding to the EDL, same as the Elvis workflow. For a 70-second video, budget roughly 8 to 10 photos at 6 to 8 seconds each, or fewer photos with longer holds if narration is dense.

Music: duck_factor 0.10 from mj-niche.yaml, meaning music sits at 10 percent volume under narration. OPEN ITEM -- confirm this matches "1.5 volume" from the brief; need the actual render or EDL param name to lock it in exactly.

## Proven video structure -- 70-second facts format

0:00-0:05 HOOK -- explosive opening line from mj-niche.yaml hooks list, bold caption reveal.
0:05-0:20 FACT 1 -- photo plus caption plus narration.
0:20-0:35 FACT 2 -- photo plus caption plus narration.
0:35-0:50 FACT 3 -- photo plus caption plus narration.
0:50-1:05 FACT 4 (LEGACY) -- photo plus caption plus narration, land on cultural impact.
1:05-1:10 CTA -- follow or subscribe line from mj-niche.yaml cta_variants.

## Cut craft notes for MJ content

Fast-paced, punchy cuts, matching mj-niche.yaml pacing -- quicker cadence than the Elvis vertical. Caption reveal should hit on the beat if music is present. Every photo needs a confirmed-rights source -- pull only from the Drive reference folders you populate yourself. No synthetic MJ face or voice, ever: B-roll and atmosphere only from Gemini, real archival photos for anything showing him.

## Open items before this is fully wired

Item one, QuickKick duration and volume params: need the QuickKick service source, which is not in this repo, to confirm how to lock the 70s runtime and exact music level.

Item two, TikTok upload leg: this pipeline auto-uploads to YouTube via OAuth, so TikTok posting is still a manual step or a separate integration.

## Session log
