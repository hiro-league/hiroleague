## What we are building

Hiro League is a private team of empathetic AI characters. They are active, emotional and loyal. They live in your private environment to serve you, your family and your home.
Check out the [About Hiro League](../../hiro-docs/docs/about.md) for more information.

## What we need


| Rank | Feature                                                           | Description                                                                                                                                      |
| ---- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1    | **Python toolkit**                                                | The agent toolkit must be Python-based so it fits the expected backend/agent development stack.                                                  |
| 2    | **Locally embeddable SDK/package**                                | The toolkit must run inside your own codebase as a package, SDK, or library, not only as a hosted service.                                       |
| 3    | **Tool/function calling**                                         | The toolkit should support structured tool definitions, argument schemas, tool selection, execution, and result handling.                        |
| 4    | **Tool-use integration**                                          | The toolkit should let agents use external tools such as file search, email, calendar, browser automation, and app/device APIs.                  |
| 5    | **Agent state management**                                        | The toolkit should preserve agent state across turns, tasks, workflows, interruptions, and long-running sessions.                                |
| 6    | **Memory integration and long-term memory support**               | The toolkit should integrate with durable memory stores for preferences, family context, interests, habits, conversations, and important dates.  |
| 7    | **Context management, context engineering, and context assembly** | The toolkit should help assemble and control the right memories, files, history, user state, summaries, and tool results before each agent step. |
| 8    | **Simple LLM model integration / model abstraction**              | The toolkit should make it easy to switch between local models, cloud models, and different providers per agent or task.                         |
| 9    | **Retries, fallbacks, and recovery**                              | The toolkit should handle failed LLM calls, failed tool calls, partial results, retries, model fallback, and workflow recovery.                  |
| 10   | **Permissions and safety**                                        | The toolkit should support guardrails, approval gates, restricted tool access, and safe handling of sensitive actions.                           |
| 11   | **Human-in-the-loop, interruptibility, and resumability**         | The toolkit should allow users to approve, reject, interrupt, modify, pause, cancel, or resume agent workflows.                                  |
| 12   | **Graph workflow building and execution**                         | The toolkit should support graph-based flows for planning, branching, tool use, memory retrieval, review, and action execution.                  |
| 13   | **Observability/tracing**                                         | The toolkit should provide traces for prompts, model calls, tool calls, memory access, decisions, errors, and workflow execution.                |
| 14   | **Streaming execution**                                           | The toolkit should stream tokens, tool progress, intermediate steps, and agent status to support responsive UI/voice experiences.                |
| 15   | **Multi-modal support**                                           | The toolkit should support text, voice, images, video/camera inputs, and possibly audio streams where needed.                                    |
| 16   | **TTS/STT model support**                                         | The toolkit should support or integrate cleanly with speech-to-text and text-to-speech models for voice interaction.                             |

## What we like about langchain\langgraph

- Graph-based workflows
- Langsmith/telemetry visualization
- 

## langchain/langgraph weakness

- No TTS/STT Support

## Other Toolkits

- Pi-Agent/Pi-Mono, this is TypeScript toolkit, not an option.
- AgentScope: Good candidate.
- Letta: 
  - Self Hostable, not embeddable in our codebase
  - No Workflow Support
  - 
