"""Phase 6.1 — Samaktha Agent Runtime Orchestrator.

The master orchestration layer connecting Conversation, Session, CAP, GAMBIT, 
Workflow, Runtime, and Memory without violating any architectural invariants.
"""

from typing import Any, AsyncGenerator, Callable, Dict, Optional

from app.agent.config import AgentConfig
from app.agent.conversation import ConversationManager
from app.agent.models import AgentEvent, ConversationState
from app.agent.personality import PersonalityManager
from app.agent.prompts import TOOL_SUMMARIZE_PROMPT
from app.agent.session import SessionManager


class AgentRuntime:
    """The master interactive orchestrator.
    
    Coordinates the strictly segregated subsystems (CAP, GAMBIT, Workflow, Runtime)
    into a stateful conversational agent.
    """

    def __init__(
        self,
        config: AgentConfig,
        session_manager: SessionManager,
        conversation_manager: ConversationManager,
        personality_manager: PersonalityManager,
        # Injected subsystems to preserve boundaries
        cap_manager: Any,
        gambit_planner: Any,
        workflow_engine: Any,
        memory_manager: Any,
        streaming_executor: Any,
        event_callback: Optional[Callable[[AgentEvent, Dict[str, Any]], None]] = None,
    ) -> None:
        self._config = config
        self._session = session_manager
        self._conversation = conversation_manager
        self._personality = personality_manager
        
        self._cap = cap_manager
        self._gambit = gambit_planner
        self._workflow = workflow_engine
        self._memory = memory_manager
        self._streaming = streaming_executor
        
        self._event_callback = event_callback

    def _emit(self, event: AgentEvent, data: Dict[str, Any]) -> None:
        if self._event_callback:
            self._event_callback(event, data)

    async def handle_message(
        self, 
        session_id: str, 
        user_input: str,
    ) -> AsyncGenerator[str, None]:
        """Main interaction loop. Handles a user message and streams the response."""
        
        # 1. Load Session
        state = self._session.get_session(session_id)
        if not state:
            state = self._session.create_session()
            self._emit(AgentEvent.SESSION_CREATED, {"session_id": state.session_id})
            
        self._emit(AgentEvent.USER_MESSAGE, {"content": user_input})
        
        # 2. Update Conversation History
        self._conversation.append_user_message(state, user_input)
        
        # 3. Retrieve Memory (if enabled)
        context = ""
        if self._config.memory_enabled:
            # We fetch summaries or skills from memory
            memory_results = await self._memory.search(user_input)
            if memory_results:
                context = f"Retrieved Context:\n{memory_results}\n"
                self._emit(AgentEvent.MEMORY_UPDATED, {"items_found": len(memory_results)})
        
        # 4. CAP Governance Check
        # CAP evaluates the raw input + context for safety.
        cap_result = await self._cap.evaluate(user_input)
        if not cap_result.allowed:
            self._emit(AgentEvent.ERROR_OCCURRED, {"reason": "CAP_REJECTION"})
            yield "CAP Intervention: Request denied due to policy violation."
            return

        # 5. GAMBIT Planning
        # GAMBIT creates a deterministic ExecutionPlan based on history + input
        self._emit(AgentEvent.PLAN_STARTED, {})
        sys_prompt = self._personality.get_system_prompt()
        plan = await self._gambit.plan(f"{sys_prompt}\n{context}\n{user_input}")
        state.current_plan = plan.model_dump()
        self._emit(AgentEvent.PLAN_FINISHED, {"plan_id": plan.plan_id})
        
        # 6. Workflow & Runtime Execution
        # Workflow manages dependencies; Runtime executes them securely.
        if plan.tasks:
            self._emit(AgentEvent.TOOL_STARTED, {"tasks": len(plan.tasks)})
            workflow_result = await self._workflow.execute(plan)
            
            # Append tool results to conversation for context
            for task_id, result in workflow_result.task_results.items():
                self._conversation.append_tool_message(
                    state, 
                    tool_name=f"task_{task_id}", 
                    result=str(result.output)
                )
            self._emit(AgentEvent.TOOL_FINISHED, {"success": workflow_result.success})

        # 7. Streaming Response Generation
        # Stream if no tasks (chat fallback), or any task has an execution action type
        # (text_generation or tool_execution) so we can respond/summarize.
        needs_generation = not plan.tasks or any(
            getattr(t, "execution_action_type", None) is not None for t in plan.tasks
        )
        
        if needs_generation:
            self._emit(AgentEvent.STREAM_STARTED, {})
            
            full_response = []
            from app.core.contracts.streaming import StreamRequest
            
            prompt_to_send = user_input
            if plan.tasks and any(t.execution_action_type not in (None, "text_generation") for t in plan.tasks):
                prompt_to_send = TOOL_SUMMARIZE_PROMPT
                
            stream_req = StreamRequest(
                request_id=f"req-{state.session_id}",
                provider_id=self._config.default_provider,
                prompt=prompt_to_send,
            )
            
            async for chunk in self._streaming.stream(stream_req):
                full_response.append(chunk.content)
                yield chunk.content
                
            self._emit(AgentEvent.STREAM_FINISHED, {"tokens": len(full_response)})
            
            # 8. Store Final Assistant Message
            final_text = "".join(full_response)
            self._conversation.append_assistant_message(state, final_text)
            self._emit(AgentEvent.ASSISTANT_MESSAGE, {"content": final_text})
        else:
            # Yield nothing if only tool tasks were executed (tool output handles display)
            pass
