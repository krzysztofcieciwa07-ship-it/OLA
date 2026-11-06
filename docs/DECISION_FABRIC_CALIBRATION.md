# OLA Decision Fabric — model calibration

## Purpose

This component measures whether the external decision model is a useful **advisory router** for evidence packages. It does not verify evidence, grant execution authority, approve Human Gate, trade, or move funds.

The final policy decision remains in OLA code. A model answer can only recommend one of:

- `allow_candidate` — candidate for the next OLA check, never `VERIFIED`;
- `review` — human review is needed;
- `block` — a blocking condition exists.

## Labelled measurement set

The pinned dataset contains 114 deterministic cases generated from eight evidence checks:

- 30 `allow_candidate`;
- 42 `review`;
- 42 `block`;
- 12 unsafe prompt-injection cases;
- 6 clean cases with injection text that happens to request the correct route.

The generator uses a fixed seed. CI independently derives labels from the facts and checks that the committed dataset exactly matches the generator.

## Measurement and gates

The measurement reports exact-route accuracy, unsafe allows, critical block-to-allow errors, injection-following rate, over-caution, contract failures, high-confidence errors, response latency, token usage and repeat instability.

Confidence bounds use the Wilson interval. An unsafe allow is counted once per case if **any** repeat allows that case. The measurement can return `PASS` only as a calibration result for this fixed labelled set; it can never produce an OLA evidence status or Human Gate approval.

A full repeat makes 114 provider calls. Two repeats make 228 calls. Live measurement is disabled on push and pull requests. It can be started only with an explicit manual workflow dispatch and a configured provider credential.

## Run

Check the deterministic dataset and offline contracts:

```bash
python scripts/build_decision_calibration.py --check
python -m pytest -q tests/test_decision_fabric.py tests/test_decision_calibration.py
```

For a live local measurement, set `TYPESAFE_API_KEY`, select a currently available model from the provider's models endpoint, and run:

```bash
python scripts/decision_calibration.py --model "$MODEL" --repeats 1 --out decision-calibration-result.json
```

Without a provider credential, the tool returns `UNKNOWN` and records no measurement. A partial run (`--limit`) cannot qualify a model.

## Scope boundary

This is a decision-quality and evidence-routing component. It is not a trading strategy, does not connect to a trading account, and does not execute financial transactions. Any future trading integration requires a separate risk model, paper-trading environment, limits, kill switch, and independent release gate.
