# Pinned upstream adaptation

Open-Interface is pinned to `5a4f706223507fc9d9eb2239cced85385fcb1308`, latest main checked 2026-10-16. Latest published release remains v0.9.0 (`c96ffb27d0673a395e7852b643df9ad69d02c1c0`). UFO is separately pinned to `eae3c0a8d168c47cb10df0652e293e092eda1078`. `../upstream.json` records every original and patched file hash; setup refuses mismatches. No startup update follows a moving branch.

`oi-agent-control.patch` makes three changes:

- `Interpreter.execute_function` dispatches only named mouse/key operations and bounded sleep; removes dynamic `getattr`, automatic Command-key injection and exception swallowing. The runtime admits one action at a time.
- `Screen` returns an in-memory screenshot without Settings or file persistence.
- `LLM` accepts an injected completion seam and reads the original OI context without importing provider clients or settings. The companion Planner applies the stronger Agent Control action/observation contract to this original context.

The maintained native additions provide SCK selected-window capture, AX/OCR detection, literal Unicode, local consent, receipts and supervision. These are not claimed to exist upstream.

`ufo-agent-control.patch` changes package initializer imports and postpones TaskStar annotations to avoid importing Galaxy services and its Windows device manager. The actual upstream TaskStar execution method, data types and enums remain unchanged. `scripts/macos_taskstar_probe.py` verifies the pinned class invokes the HTTP bridge and returns an upstream ExecutionResult.

Open-Interface is GPL-3.0; [its license](../COPYING.Open-Interface) is retained. UFO is MIT; [its license](../LICENSE.UFO) is retained. These patches and source references must accompany any distributed adaptation under the applicable upstream terms. This work prepares local source installation, not a signed binary release. Distribution requires a concrete license/source packaging review and separate publication authorization.
