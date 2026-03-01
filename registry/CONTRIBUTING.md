# Registry Model Standards

Models added to `registry/models.json` should meet the following bar:

1. **Forwards compatibility.** This registry exists primarily so older versions of vet get access to new models. When built-in models are added, they should be added here if endpoint compatibility allows it.

2. **Produces useful output.** The models should be able to complete a vet run and produce at least some actionable findings. It does not need to catch everything, but it should not consistently mis-identify issues.

3. **Runs reliably.** The API endpoint must be stable with no consistent failures, timeouts, or malformed responses during normal usage.

## Limitations

Registry models are routed through a generic OpenAI-compatible API layer, not the native provider-specific API classes used by built-in models. This means features like cost tracking, rate limiting, and provider-specific error handling are not available for registry models. The registry is a lightweight "tide you over" mechanism for making new model IDs available before they are added as builtins, not a full-featured alternative.
