# AgentMark Natural Controller N1 — Official Home Assistant Motion-Light

Status: **FROZEN BEFORE FIRST N1 EXECUTION** on `agentmark-theory-lock`.

This experiment is designed to test the locked AgentMark replay-validity theory on an independently authored controller. It does not modify E3b/E3c and does not search for a controller after observing replay outcomes.

## 1. External controller provenance

Controller: Home Assistant official **Motion-activated Light** automation blueprint.

- repository: `home-assistant/core`
- commit: `0cb25fe4727b5466743285f048eb6aa75fd02bbb`
- path: `homeassistant/components/automation/blueprints/motion_light.yaml`
- expected source SHA-256: `e07ac35fae7270131f118da767b036e7f7776672077691d9fbcd026e5a7e3f9c`
- Home Assistant runtime: Core `2026.9.0`
- immutable runtime image: resolved by CI and retained in every artifact

The blueprint source must be executed byte-for-byte as fetched. Only declared blueprint inputs may be bound. Branch/action logic may not be rewritten.

## 2. Native controller structure under test

The externally authored blueprint specifies:

1. state trigger `motion_entity: off -> on`;
2. `light.turn_on`;
3. `wait_for_trigger` until `motion_entity: on -> off`;
4. a configured delay;
5. `light.turn_off`;
6. automation `mode: restart`.

N1 tests the decision after the initial `light.turn_on`: while motion remains `on`, the live controller is still waiting and has not enabled the recorded `light.turn_off`; after no-motion feedback arrives and the configured delay elapses, `light.turn_off` becomes the live controller action.

## 3. Input bindings

These are controller inputs, not source-code edits:

- `motion_entity = binary_sensor.agentmark_motion`
- `light_target = {entity_id: light.agentmark_light}`
- `no_motion_wait = 0.020 seconds`

The virtual light service is used only to control action-completion latency while all automation control-flow semantics are Home Assistant native.

## 4. Frozen feedback and timing conditions

All times are monotonic and relative to the motion `off -> on` trigger.

- source no-motion feedback (`motion on -> off`): **60 ms**
- target no-motion feedback: **180 ms**
- source `light.turn_on` service completion delay: **5 ms**
- target `light.turn_on` service completion delay: **40 ms**
- `light.turn_off` service completion delay: **0 ms**
- source blueprint post-feedback delay: **20 ms**

The target action-completion latency is deliberately changed independently of the controller-semantic motion feedback. This gives R1 genuine current-system timing feedback without giving it target controller feedback.

## 5. Source trace

Each independent runner records one source trace by running the unmodified official blueprint through Home Assistant's native automation engine.

A valid source trace must:

- produce exactly one `light.turn_on` and one `light.turn_off` service call;
- observe motion `off` before the source `light.turn_off` issue;
- issue source `light.turn_off` before **130 ms** from trigger, leaving at least 50 ms separation from the frozen target no-motion event;
- retain native service-call Context IDs and monotonic timestamps.

If these source-qualification conditions fail, the runner is invalid rather than the thresholds being changed.

## 6. Replay modes

All modes execute Home Assistant service calls; R2 additionally executes the original native automation.

### R0 — rigid replay

Reissue source-recorded `light.turn_on` and `light.turn_off` at their source-relative issue times. Target service completion may differ, but recorded issue timing and semantic action sequence are frozen.

### R1 — timing-feedback-only replay

Issue source-recorded `light.turn_on`, wait for its actual target completion, then preserve the source post-completion interval

`source_turn_off_issue - source_turn_on_complete`

before reissuing recorded `light.turn_off`.

Thus R1 receives current action-completion timing while freezing source semantic action identity.

### R2 — semantic-feedback-preserving replay

Run the original official Home Assistant automation under target motion feedback. The live controller therefore remains at `wait_for_trigger` until target no-motion arrives, then executes its configured delay and `light.turn_off`.

## 7. Locked support oracle

The paper-facing projection for N1 is operation identity.

At the relevant controller state after `light.turn_on`:

- feedback `MOTION` (`binary_sensor` still `on`) leaves the external controller at `wait_for_trigger`; recorded `light.turn_off` is not enabled / has zero support;
- feedback `NO_MOTION` (`binary_sensor` is `off`) enters the path that, after the blueprint's declared delay, emits `light.turn_off`.

The AgentMark finite kernel used by the independent validator therefore represents the externally specified control node as:

- `MOTION -> WAIT` (remain waiting)
- `NO_MOTION -> light.turn_off` (advance to completion)

`WAIT` denotes the blueprint's explicit `wait_for_trigger` control operation; it is not a synthetic device action.

A replayed `light.turn_off` is a support failure iff it is source-consistent under `NO_MOTION` but is issued while target motion remains `MOTION`.

## 8. Replication

- **2 independent GitHub-hosted runners**
- **6 target trials per replay mode per runner**
- each runner records its own source trace before target trials
- fresh Home Assistant instance per source/control/mode trial, so automation state does not leak between trials

No failed runner may be dropped from the aggregate.

## 9. Primary predictions and promotion gates

N1 is promoted only if both independent runners satisfy every gate below.

### External-source integrity

- exact external source SHA-256 matches the frozen hash;
- native Home Assistant automation blueprint schema accepts the source;
- R2 loads the external source through the native automation engine;
- only the three declared blueprint inputs differ between source and experiment instance.

### Source qualification

- source trace valid under Section 5.

### Decisive target condition

For every target trial:

- R0 issues exactly one `light.turn_on` and one `light.turn_off`;
- R1 issues exactly one `light.turn_on` and one `light.turn_off`;
- R2 native automation issues exactly one `light.turn_on` and one `light.turn_off`;
- R0 `light.turn_off` occurs while motion is `on` -> support failure;
- R1 `light.turn_off` occurs while motion is `on` -> support failure;
- R2 `light.turn_off` occurs after motion is `off` -> no support failure;
- R1 mean `light.turn_off` shift versus R0 is at least **20 ms**;
- R2 mean `light.turn_off` shift versus source is at least **80 ms**.

### No-feedback-shift negative control

Repeat R0/R1/R2 with target no-motion feedback equal to the source **60 ms**. For every mode:

- recorded semantic path remains `light.turn_on -> light.turn_off`;
- `light.turn_off` is not classified as a support failure;
- exactly one native `turn_on` and one native `turn_off` occur.

The control is about semantic path validity, not equality of absolute issue timestamps.

### Native accounting

For every run, raw `EVENT_CALL_SERVICE` events are retained with monotonic time and Context ID. Producer summaries are not sufficient evidence.

## 10. Independent validation

A separate host-side validator must recompute from raw result rows and raw native service events:

- source qualification;
- exact service-call conservation;
- motion state at each `turn_off` issue;
- R0/R1 support failures;
- R2 support preservation;
- R1 timing shift;
- R2 semantic timing shift;
- no-feedback-shift control;
- external-source/runtime provenance.

The producer and validator must both pass before aggregation. Aggregate requires two independently validated replicas.

## 11. Forbidden post-hoc moves

After first N1 execution begins, do **not**:

- change 60/180 ms feedback timing because a gate failed;
- change 5/40 ms service delays because a gate failed;
- change the 20 ms blueprint delay because a gate failed;
- weaken the 20 ms R1 or 80 ms R2 materiality gates;
- redefine `MOTION`/`NO_MOTION` after results;
- replace the official blueprint with an AgentMark-authored equivalent;
- edit the blueprint's `wait_for_trigger`, delay, action sequence, or restart mode;
- count a failed independent runner as a successful replication;
- silently interpret unsupported native automation behavior by hand.

Implementation-only corrections are allowed only when they restore the frozen experiment to the semantics above without changing scientific conditions. Every such correction must be documented and followed by a fresh run.

## 12. Claim boundary

A passing N1 would establish that the E3b/E3c timing-versus-controller-semantic separation occurs in an independently authored official Home Assistant controller, using the native automation engine. It would **not** establish prevalence across all smart-home automations; that is the purpose of the broader outcome-blind controller corpus.
