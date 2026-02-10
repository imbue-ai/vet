# vet_custom_guideline_replace

This project handles PII. Carefully flag any of the following:
- Logging of email addresses, names, or auth tokens
- Missing input sanitization on user-facing endpoints
- Use of `eval()`, `exec()`, or `subprocess.run(shell=True)`
- Hard-coded credentials or API keys
