CONVERSATION_PREFIX_TEMPLATE = """[ROLE=SYSTEM_CACHED]
You will be provided a conversation history between a user and another agent. The other agent may be from any model provider or model family.
The conversation history includes the user's messages and the agent's text-based messages, but may be missing some automated messages and tool calls/tool call results.
Examine the conversation carefully and be prepared to answer questions about it.
Here is the conversation history between the user and the other agent.
{% filter indent(width=2) %}
```
{{ conversation_history }}
```{% endfilter %}"""
