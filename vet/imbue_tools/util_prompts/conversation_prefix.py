CONVERSATION_PREFIX_TEMPLATE = """[ROLE=SYSTEM_CACHED]
You will be provided a conversation history between a user and another agent. The other agent may be from any model provider or model family.
The conversation history includes the user's messages and the agent's text-based messages, but may be missing some automated messages and tool calls/tool call results.
Examine the conversation carefully and be prepared to answer questions about it.
Note: This conversation is being analyzed while still in progress. The agent's final messages may reference actions it is currently performing (such as running verification tools). Do not treat these as completed claims — the results may not yet be visible because the action is still executing at the time of this analysis.
Here is the conversation history between the user and the other agent.
{% filter indent(width=2) %}
```
{{ conversation_history }}
```{% endfilter %}"""
