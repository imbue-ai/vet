# Registry Model Standards

Models added to `registry/models.json` should meet the following bar:

1. **Forwards compatibility.** This registry exists so users automatically get access to new capable models. When new built-in models are added, they should also be added here if endpoint compatibility allows it.

2. **Produces useful output.** The model should be able to complete a vet run and produce at least some actionable findings. It does not need to catch everything, but it should not hallucinate issues or return empty/unusable results.

3. **Runs reliably.** The API endpoint must be stable with no consistent failures, timeouts, or malformed responses during normal usage.
