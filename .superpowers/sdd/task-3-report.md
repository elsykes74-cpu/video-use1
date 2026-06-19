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
