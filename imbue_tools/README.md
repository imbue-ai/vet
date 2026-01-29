# Purpose
Shared functionality for imbue-cli tools like imbue-verify, imbue-retrieve, etc.

# Contents
- formatting git repos as LLM input

# Excluded files list
We currently maintain a hard-coded list of filename patterns for which we'll only ever include the file name, rather than the files' contents, in the LLM input.
This list is maintained in the EXCLUSIONS_PATHSPEC constant in imbue_tools/imbue_tools/repo_utils/context_prefix.py .
