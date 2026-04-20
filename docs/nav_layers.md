# nav: layers

The 12 horizontal intelligence layers. Each layer is a
processor the orchestrator invokes in a fixed order
inside the `layers(12)` phase.

## Physical source

`layers/` — one file per layer.

Typical layers (see `docs/AGI_STACK.md` for the full
10+6 list):

```
L1  sensing         L7  risk tripwire
L2  perception      L8  launch simulator
L3  intent          L9  memory ladder
L4  planning        LX.1 customer chatbot
L5  decision        LX.2 fulfilment
L6  execution       LX.3 federation
```

## Contract

Each layer:
- Takes the cycle context dict, mutates/adds a key
  under its namespace.
- Emits side-effects only through adapters.
- Reports stage timing via `layer_timer`.

## Tests

`tests/test_layer_<name>.py` — contract tests verifying
the layer writes the expected keys.

## Rules

- Never add a new layer without updating the 36-phase
  order in `core/core_orchestrator.py`.
- Layer order matters — dependencies are one-way; a
  later layer can read earlier results but not vice
  versa.
- If two layers want to write the same key, that's a
  bug — split the namespace.
