# Task 4 Report

## Summary

- Added `quickkick_bot.drive_pool` with Drive-wide candidate collection across regular image files and zip-contained images, plus a mockable zip-enumeration seam and lazy cache materialization.
- Added `quickkick_bot.image_matcher` with local-first scene matching, drive fallback scoring, and weak-scene detection.
- Updated `quickkick_bot.pipeline` to use matched scene images for production-doc runs and stop before render/upload when any scene remains weak.
- Added `tests.quickkick_bot.test_drive_pool_and_matcher` to cover Drive collection, zip expansion, local-vs-drive tier preference, and weak-scene gating.

## Verification

- `python -m unittest tests.quickkick_bot.test_drive_pool_and_matcher -v` — passed
- `python -m unittest tests.quickkick_bot.test_planner_and_render tests.quickkick_bot.test_settings_and_state tests.quickkick_bot.test_import_smoke -v` — passed

## Commit SHAs

- Implementation commit: `18188a8`

## Concerns

- Regular Drive image candidates are cached lazily when selected, so first-use latency remains on the selection path.
- Zip candidate extraction currently downloads the full zip before enumerating image members, which is correct for scope coverage but could be slow for very large archives.

## Fix Pass

### Summary

- Routed the ordinary generated-topic pipeline path through `_collect_scene_images` after scene planning so topic runs now use candidate collection, matching, and weak-scene gating instead of jumping straight to `gpt-image-1`.
- Changed scene matching to treat explicit local picks as preferred but still allow Drive fallback per scene when local coverage is partial, and to replace weak discovered local matches with stronger Drive candidates.
- Added regression coverage for generated-topic integration, partial local supplementation, weak-local Drive replacement, and skipping Drive scans when strong local coverage already satisfies every scene.

### Verification

- `python -m unittest tests.quickkick_bot.test_drive_pool_and_matcher -v`
  - Passed: 8 tests
- `python -m unittest tests.quickkick_bot.test_planner_and_render tests.quickkick_bot.test_settings_and_state tests.quickkick_bot.test_import_smoke -v`
  - Passed: 11 tests

### Concerns

- Full zip downloads are still required before zip-contained image enumeration, so very large Drive archives will remain the slowest part of candidate discovery.

## Second Fix Pass

### Summary

- Distinguished trusted CLIP-selected local matches from untrusted alphabetical/local fallback by tracking trust state at the pipeline seam.
- Stopped fallback local lists from receiving automatic strong scores, so CLIP-unavailable or CLIP-failure paths still drive weak-scene scoring and Drive fallback when local filenames are not strong matches.
- Added regression coverage for the fallback-local path to ensure Drive search is not silently suppressed.

### Verification

- `python -m unittest tests.quickkick_bot.test_drive_pool_and_matcher -v`
  - Passed: 9 tests
- `python -m unittest tests.quickkick_bot.test_planner_and_render tests.quickkick_bot.test_settings_and_state tests.quickkick_bot.test_import_smoke -v`
  - Passed: 11 tests

### Concerns

- Trust is currently tracked as process-local pipeline state around `_clip_select_images`, which is sufficient for this single-run pipeline path but still intentionally lightweight.

## Third Fix Pass

### Summary

- Removed the module-global CLIP trust bit from `pipeline.py` and replaced it with an explicit per-call seam: `_clip_select_images_with_trust(...) -> (images, trusted)`.
- Kept `_clip_select_images(...)` as a compatibility wrapper so existing callers and tests still work, while `_collect_scene_images` now consumes the explicit trust tuple directly.
- Adjusted Task 4 regression coverage to patch the trust-aware seam directly, while preserving coverage for older codepaths that still patch `_clip_select_images`.

### Verification

- `python -m unittest tests.quickkick_bot.test_drive_pool_and_matcher -v`
  - Passed: 9 tests
- `python -m unittest tests.quickkick_bot.test_planner_and_render tests.quickkick_bot.test_settings_and_state tests.quickkick_bot.test_import_smoke -v`
  - Passed: 11 tests

### Concerns

- Zip-contained Drive images still require full archive download before enumeration, so large archives remain the slowest candidate-discovery path.
