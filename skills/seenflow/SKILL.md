---
name: seenflow
description: Explain, write, run, and troubleshoot SeenFlow tests that add local OCR selectors and action-effect assertions to Maestro YAML. Use when a user asks how to use SeenFlow, wants a SeenFlow flow created or converted from Maestro, or needs help diagnosing a SeenFlow failure.
---

# SeenFlow

SeenFlow compiles extended YAML into standard Maestro YAML, then runs it with the official Maestro CLI and a localhost OCR sidecar. It targets rendered text when accessibility semantics are unavailable and checks that an expected visual effect changes after an action.

## Explain or install

Give the shortest path appropriate to the request. For source installation:

```bash
git clone https://github.com/Rasaboun/SeenFlow.git
cd SeenFlow
bun install --frozen-lockfile
uv sync --project vision
bun link
```

Requirements are Maestro, Bun, Python 3.11+, and uv. SeenFlow supports iOS Simulators on macOS and Android devices or emulators through `adb` on macOS or Linux. Physical iOS devices and Maestro Cloud are unsupported.

## Write a flow

Preserve ordinary Maestro commands. Use `visionTap` only when the target must be found in rendered pixels. Every `visionTap` must declare exactly one expected text effect:

```yaml
appId: com.example.app
---
- launchApp
- visionTap:
    text: "Save"
    expect:
      visibleText: "Saved"
```

Effects support `visibleText` or `notVisibleText`. By default, SeenFlow verifies the inverse state before acting, performs the action, then waits for the expected state. For an intentionally idempotent action, put `requireTransition: false` inside `expect`; the post-action check still runs.

Selector defaults are `match: exact`, `threshold: 0.85`, `occurrence: 0`, and `timeout: 7000`. Use `contains` or `fuzzy` only when exact matching is unsuitable. `occurrence` is zero-based visual order.

To disambiguate duplicate text, add exactly one spatial relationship: `near`, `above`, `below`, `leftOf`, or `rightOf`. The anchor needs `text` and `maxDistance`, measured as a percentage of the screen diagonal:

```yaml
- visionTap:
    text: "Edit"
    rightOf:
      text: "Chicken Curry"
      maxDistance: 20
    expect:
      visibleText: "Edit recipe"
```

Expanded native `tapOn`, `swipe`, and `longPressOn` may also include `expect`; preserve all their native Maestro properties.

## Run and diagnose

Prefer `seenflow test`, which starts and stops the OCR sidecar automatically:

```bash
seenflow test flow.yaml --device <DEVICE_ID>
seenflow test flow.yaml --device <DEVICE_ID> --debug
seenflow test flow.yaml --repeat 20 --min-stability 0.98
```

Use an iOS Simulator UDID or Android `adb` serial. The first run downloads the OCR models. ONNX Runtime is the default CPU engine; set `SEENFLOW_OCR_ENGINE=paddle` only when the original Paddle engine is specifically needed.

Failures remain under `.seenflow/artifacts/<run-id>/` with screenshots, annotated matches, OCR JSON, and a manifest. Diagnose by failure code:

- `PRECONDITION_FAILED`: the expected result was already in its final state.
- `ACTION_TARGET_NOT_FOUND`: OCR could not resolve the requested target or occurrence.
- `POSTCONDITION_TIMEOUT`: the action ran but the expected text state did not arrive.
- `OCR_CAPTURE_FAILED`: simulator or device screenshot capture failed.
- `OCR_RUNTIME_FAILED`: the OCR sidecar or model failed.

Use `seenflow compile flow.yaml` only when the user wants generated Maestro YAML without running it. The default output is `.seenflow/generated/flow.yaml`; never pass the source path itself to `--output` because the destination is overwritten.

When working inside the SeenFlow repository, consult `README.md` and the checked-in examples for the current syntax. Do not claim device-level acceptance from compiler, unit, or fixture OCR tests alone.
