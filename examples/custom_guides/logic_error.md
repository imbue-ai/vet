# vet_custom_guideline_prefix

This project uses 1-based indexing for all public API array parameters.
Off-by-one errors are especially common at the boundary between
internal (0-based) and external (1-based) representations.
