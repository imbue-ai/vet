FROM debian:bookworm-slim

ARG INSTALL_CLAUDE=false

RUN apt-get update \
 && apt-get install -y npm git curl \
 && npm install -g opencode-ai @openai/codex \  # opencode is only installed right now because
                                                # I like using it in containers for development,
                                                # but I don't want it installed on my host.
                                                # TODO: Add support for opencode invocations
                                                # in agentic mode.
 && curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app
RUN git config --global --add safe.directory /app

RUN if [ "$INSTALL_CLAUDE" = "true" ]; then \
      npm install -g @anthropic-ai/claude-code; \
fi
