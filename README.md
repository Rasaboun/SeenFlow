<p align="center">
  <img src="logo.png" alt="SeenFlow logo" width="160">
</p>

# SeenFlow

Deterministic visual selectors and action-effect assertions for Maestro.

Maestro normally interacts with UI semantics. `seenflow` optionally lets a flow interact with rendered text itself. Every supported interaction can also declare the visual state change that proves the action succeeded.

It is a compiler and local OCR sidecar, not a Maestro fork or a new device driver:

```text
Extended Maestro YAML → seenflow → standard Maestro YAML → official Maestro CLI
                                      ↘ local PP-OCRv6 sidecar ↗
```

## Example

```yaml
# Native Maestro
- tapOn: "Save"
- assertVisible: "Saved"
```

```yaml
# seenflow
- visionTap:
    text: "Save"
    expect:
      visibleText: "Saved"
```

The second form:

1. verifies `Saved` is not already visible;
2. finds `Save` in a fresh screenshot using deterministic OCR;
3. asks official Maestro to tap the resolved screen percentage;
4. polls fresh screenshots until `Saved` appears.

If `Saved` is visible before the tap, the flow fails before the action. For an intentionally idempotent action, disable that precondition inside `expect`:

```yaml
- visionTap:
    text: "Save"
    expect:
      visibleText: "Saved"
      requireTransition: false
```

The post-action check still runs.

## Requirements

- macOS with an iOS Simulator, or macOS/Linux with `adb` for Android;
- [Maestro](https://docs.maestro.dev/getting-started/installing-maestro) available as `maestro`;
- Bun;
- Python 3.11+ and `uv`.

Physical iOS devices and Maestro Cloud are not supported in v0.4.

## Install from source

```bash
git clone https://github.com/Rasaboun/SeenFlow.git
cd SeenFlow
bun install --frozen-lockfile
uv sync --project vision
bun link
```

`bun link` exposes the repository's `seenflow` executable for local development. PaddleOCR initializes the official `PP-OCRv6_tiny_det` and `PP-OCRv6_tiny_rec` models once when the sidecar starts; the first run downloads them from Hugging Face.

Seenflow uses PaddleOCR's ONNX Runtime engine by default. This is CPU inference, not Apple Metal or GPU acceleration. To use the original Paddle engine instead:

```bash
SEENFLOW_OCR_ENGINE=paddle seenflow test flow.yaml
```

## Run your first flow

Save this as `flow.yaml`, replace `com.example.app` with your installed app's ID, and choose labels that match its UI:

```yaml
appId: com.example.app
---
- launchApp
- visionTap:
    text: "Save"
    expect:
      visibleText: "Saved"
```

With your simulator or Android device running:

```bash
seenflow test flow.yaml --device <DEVICE_ID>
```

Use an iOS Simulator UDID or an Android `adb` serial for `<DEVICE_ID>`. To try a ready-made app and flow, use the [acceptance fixtures](#acceptance-fixtures) below.

## Compile

```bash
seenflow compile flow.yaml
seenflow compile flow.yaml --output /tmp/flow.yaml
```

The default output is `.seenflow/generated/flow.yaml`. Compilation does not run Maestro. Choose an output path different from the input: `--output` overwrites its destination, including the source if you pass the same path.

Generated YAML uses official Maestro commands, including `runScript` calls to the copied SeenFlow runtime scripts. Visual actions still need a running sidecar and its connection settings; use `seenflow test` to manage those automatically.

## Test

```bash
seenflow test flow.yaml
seenflow test flow.yaml --device <UDID>
seenflow test flow.yaml --device <UDID> --debug
seenflow test flow.yaml --repeat 20 --min-stability 0.98
```

The test command validates the source, starts an authenticated localhost-only sidecar on a random port, compiles the flow, forwards Maestro's output, preserves its exit code, and stops the sidecar. Repeated mode runs Maestro sequentially against the same loaded OCR model and exits successfully only when the measured pass rate meets `--min-stability` (default `1.0`).

## Syntax

```yaml
seenflow:
  requireEffects: true
appId: com.example.app
---

- visionTap:
    text: "Add"
    match: exact       # exact | contains | fuzzy
    threshold: 0.85
    occurrence: 1      # zero-based visual order
    timeout: 7000
    expect:
      visibleText: "2 items"

- visionTap:
    text: "Edit"
    rightOf:
      text: "Chicken Curry"
      match: exact
      threshold: 0.85
      occurrence: 0
      maxDistance: 20
    expect:
      visibleText: "Edit recipe"

- tapOn:
    id: "save-button"
    retryTapIfNoChange: true
    expect:
      notVisibleText: "Loading..."

- swipe:
    direction: UP
    waitToSettleTimeoutMs: 500
    expect:
      visibleText: "Orders"

- longPressOn:
    point: "50%,50%"
    expect:
      visibleText: "Actions"
```

`visionTap` defaults to exact matching, threshold `0.85`, occurrence `0`, and a post-action timeout of `7000ms`. Expanded `tapOn`, `swipe`, and `longPressOn` keep all native Maestro properties and use OCR only for their expected effects. Other Maestro commands pass through unchanged.

`visionTap` always requires `expect`. Expanded `tapOn` requires it by default; set `seenflow.requireEffects: false` in the flow header to allow expanded taps without effects. Shorthand `tapOn: "Save"`, effectless `swipe`, and effectless `longPressOn` are accepted with warnings. Native action effects have a fixed post-action timeout of `7000ms`.

Spatial `visionTap` supports exactly one of `near`, `above`, `below`, `leftOf`, or `rightOf`. The nested anchor uses the same `match`, `threshold`, and zero-based `occurrence` options, with defaults of `exact`, `0.85`, and `0`. `maxDistance` is required and measures center-to-center distance as a percentage of the screen diagonal.

Directional relationships use a 90-degree cone so `rightOf`, for example, rejects candidates that are mostly above or below the anchor. Valid targets are ranked by distance, match score, OCR confidence, then screen order before the target occurrence is applied. Anchor and target resolution use the same fresh screenshot and OCR result.

PP-OCRv6 may recognize nearby labels as one text line. v0.4 requests Paddle's native word boxes, reconstructs consecutive multi-word phrases from the recognized line, and prefers the smallest matching word or phrase geometry without changing the YAML. For example, one OCR line containing `Chicken Curry Edit` can resolve `Chicken Curry` as the spatial anchor and `Edit` as the tap target. Debug responses and artifacts identify whether the selected geometry came from a line, word, or reconstructed phrase.

Word refinement uses the same screenshot and Paddle inference as the original lookup. Seenflow does not estimate substring coordinates from character widths; malformed or unavailable native word geometry falls back to the original line evidence with a diagnostic reason.

Effects are screenshot-based OCR assertions. They support exactly one of `visibleText` or `notVisibleText`. Matching Unicode-normalizes, trims, collapses whitespace, and case-folds without globally removing punctuation.

## Failure artifacts and debugging

Visual failures report a distinct code such as `PRECONDITION_FAILED`, `ACTION_TARGET_NOT_FOUND`, `POSTCONDITION_TIMEOUT`, `OCR_CAPTURE_FAILED`, or `OCR_RUNTIME_FAILED`.

Every OCR decision is journaled under a run and source step:

```text
.seenflow/artifacts/<run-id>/
├── manifest.json
└── <step>-<phase>-<attempt>/
    ├── screenshot.png
    ├── annotated.png
    └── ocr.json
```

Successful journals are removed by default. Failed runs remain, and `--debug` retains successful journals while also printing capture/OCR durations, match details, coordinates, precondition state, and polling attempts. Add this to `.gitignore`:

```gitignore
.seenflow/
```

## Acceptance fixtures

iOS Simulator:

```bash
examples/fixtures/ios/build.sh
xcrun simctl install <UDID> .seenflow/fixtures/ios/SeenflowFixture.app
seenflow test examples/ios/continue-welcome.yaml --device <UDID>
seenflow test examples/ios/long-press-actions.yaml --device <UDID>
seenflow test examples/ios/spatial-edit.yaml --device <UDID>
```

Android (SDK 34 platform and build-tools 35):

```bash
ANDROID_SDK_ROOT=/path/to/sdk examples/fixtures/android/build.sh
adb -s <UDID> install -r .seenflow/fixtures/android/SeenflowFixture.apk
seenflow test examples/android/continue-welcome.yaml --device <UDID>
seenflow test examples/android/swipe-orders.yaml --device <UDID>
seenflow test examples/android/spatial-edit.yaml --device <UDID>
```

Both fixture apps draw their labels directly into pixels and hide accessibility descendants. They cover OCR tapping, spatial disambiguation of duplicate text, native swipe and long-press effects, and transition-safety failure before an action.

## Scope

v0.4 matches rendered text using local OCR. It does not match images or icons, perform visual regression, or use VLMs/LLMs. Spatial selectors support one relationship at a time; expected effects check text visibility only.

Supported targets are iOS Simulators and Android devices/emulators on the host platforms listed above. Physical iOS devices and Maestro Cloud are unsupported. Maestro performs the interactions; the sidecar captures and analyzes screenshots. Stability runs execute sequentially.

## OCR performance

ONNX Runtime is the default CPU inference engine. A recorded comparison on the checked-in merged-row fixture measured `83.9ms` median OCR time with ONNX Runtime versus `271.8ms` with Paddle across five warm runs: approximately `3.24×` faster, with identical text, boxes, word spans, and provenance. The hardware was not recorded alongside these results, so treat them as illustrative rather than a portable performance guarantee. Capture, startup, and IPC costs are excluded.

Reproduce the comparison on your machine from the repository root:

```bash
uv run --project vision python vision/benchmarks/ocr_engines.py vision/tests/fixtures/spatial-merged-row.png
```

The script warms up each engine, measures five OCR calls per engine, and reports durations and whether the extracted geometry and text agree.

## Related reading

Shopify Engineering's [How we raised mobile end-to-end test stability to 98%](https://shopify.engineering/mobile-e2e-testing) describes visual targeting, assertions checked before and after actions, and repeated runs to measure stability—the same principles behind SeenFlow's OCR selectors, transition checks, and stability mode. Shopify's reported 98% result applies to its own test suite.

## Development

```bash
bun run test
bun run typecheck
UV_CACHE_DIR=.seenflow/uv-cache uv run --project vision --extra test pytest
```

Licensed under the MIT License.
