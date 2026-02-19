FROM debian:bookworm-slim

ARG INSTALL_CLAUDE=false

RUN apt-get update \
 && apt-get install -y npm git curl \
 && npm install -g opencode-ai @openai/codex \
 && curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app
RUN git config --global --add safe.directory /app

RUN if [ "$INSTALL_CLAUDE" = "true" ]; then \
      npm install -g @anthropic-ai/claude-code; \
fi
