## Summary

- Added `quickkick_bot.image_prep.prepare_selected_images(...)` to prepare matched scene images before they enter the run `images/` folder.
- Wired `quickkick_bot.pipeline` to use that seam instead of raw-copying `selected_scene_images`.
- Refactored `quickkick_bot.upscale_library` to expose provider-specific restore helpers that reuse the existing restore prompt and final 9:16 canvas logic.
- Added `OPENROUTER_IMAGE_MODEL` to `.env.example`.
- Added a focused Task 5 regression test covering OpenAI restore failure with OpenRouter fallback.

## Verification

- `python -m unittest tests.quickkick_bot.test_image_prep -v` -> passed
- `python -m unittest tests.quickkick_bot.test_import_smoke tests.quickkick_bot.test_image_prep -v` -> passed

## Commit SHA(s)

- `4cb0a6c0bab724cb2c786282c1ca4c1efa184037`

## Concerns

- The OpenRouter fallback assumes the configured `OPENROUTER_IMAGE_MODEL` supports the OpenAI-compatible `images.edit` flow at `https://openrouter.ai/api/v1`; if the selected model does not, the code falls back to copying the original source image into the run folder.

## Review Fix

- Removed the silent raw-copy fallback from `prepare_selected_images(...)`; the matched-image prep path is now provider-authoritative: OpenAI restore first, then OpenRouter restore, then explicit failure if both providers fail.
- Added regression coverage for the both-providers-fail case so the failure is surfaced instead of returning the original file.

## Review Fix Verification

- `python -m unittest tests.quickkick_bot.test_image_prep -v` -> passed
- `python -m unittest tests.quickkick_bot.test_import_smoke tests.quickkick_bot.test_image_prep -v` -> passed

## Review Fix Commit SHA(s)

- `3685733d7db26a5790f4bd89cf4af2db0134eb6a`

## Updated Concerns

- The OpenRouter fallback still assumes the configured `OPENROUTER_IMAGE_MODEL` supports the OpenAI-compatible `images.edit` flow at `https://openrouter.ai/api/v1`; if not, matched-image prep now fails explicitly instead of copying the original source image.
