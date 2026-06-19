# Task 3 Report

## Summary
- Added `quickkick_bot.planner.plan_image_beats` for hybrid beat planning with a minimum of 5 images and scene trimming/expansion toward the configured 3-5 second density window.
- Added `quickkick_bot.render` with slideshow filter generation and ffmpeg-based motion assembly using subtle crossfades plus a slow Ken Burns zoom/pan.
- Routed `quickkick_bot.pipeline` through the new planner and motion renderer while leaving the thumbnail skip threshold for videos under 2 minutes intact.
- Added Task 3 unit coverage in `tests/quickkick_bot/test_planner_and_render.py`.

## Verification
- `python -m unittest tests.quickkick_bot.test_planner_and_render -v` — passed
- `python -m unittest tests.quickkick_bot.test_settings_and_state -v` — passed
- `python -m unittest tests.quickkick_bot.test_planner_and_render tests.quickkick_bot.test_settings_and_state -v` — passed
- `python -m unittest discover tests -v` — failed due existing package import resolution issues in the repo test layout (`tests/quickkick_bot` shadowing `quickkick_bot`)

## Commit SHAs
- `8ec4297` — `feat: add hybrid image planning and motion renderer`

## Concerns
- Full `unittest discover` is still broken by the existing test-package/import structure and is not specific to Task 3.
- `quickkick_bot.render` currently duplicates ffmpeg probing helpers that also still exist in `quickkick_bot.pipeline`; consolidating them would be a reasonable follow-up cleanup.

## Fix Pass
- Addressed the 60s/5-images density failure by making both planning and rendering reconcile to a target image count that keeps the average image duration inside the configured 3-5 second window when duplication/trimming can do so.
- Updated the pipeline to re-plan beats and reconcile render inputs again after real TTS audio duration is probed, while preserving the under-2-minute thumbnail skip rule.
- Extended Task 3 coverage with a direct density-regression test and a pipeline integration test that proves post-TTS audio duration changes the render input count.

## Fix Pass Verification
- `python -m unittest tests.quickkick_bot.test_planner_and_render -v` — passed, 7 tests OK including the 60s/5-images density regression and real-audio reconciliation path
- `python -m unittest tests.quickkick_bot.test_settings_and_state -v` — passed, 2 tests OK
- `python -m unittest tests.quickkick_bot.test_planner_and_render tests.quickkick_bot.test_settings_and_state -v` — passed, 9 tests OK
