from __future__ import annotations

import logging
from uuid import uuid4

from app.core.contracts.planning import (
    Goal,
    GoalComplexity,
    GoalIntent,
    PlanTask,
    RouterRequest,
    SkillMatch,
    TaskKind,
    TaskStatus,
)

log = logging.getLogger(__name__)


class TaskDecomposer:
    """Decomposes normalized goals into runtime-executable task sequences.

    Intent-to-plan mapping:
      READ_RESOURCE     → [UNDERSTAND, tool:resolver(read), EXECUTE_VIA_RUNTIME(text_generation), REFLECT]
                          ResolverTool selects the specific handler (pdf, image, filesystem) after planning.
      LIST_DIRECTORY    → [UNDERSTAND, tool:resolver(list), REFLECT]  — no LLM required
      SEARCH_MEMORY     → [UNDERSTAND, tool:memory(search), EXECUTE_VIA_RUNTIME, REFLECT]
      SEARCH_INTERNET   → [UNDERSTAND, tool:internet(search), EXECUTE_VIA_RUNTIME, REFLECT]
      OPERATE_WINDOWS   → [UNDERSTAND, tool:windows(action), REFLECT]
      RUN_COMMAND       → [UNDERSTAND, tool:<shell via capability>, REFLECT]
      CLIPBOARD         → [UNDERSTAND, tool:<clipboard via capability>, REFLECT]
      SEND_NOTIFICATION → [UNDERSTAND, tool:<notification via capability>, REFLECT]
      GENERATE_CODE     → [UNDERSTAND, EXECUTE_VIA_RUNTIME(text_generation), REFLECT]
      ANSWER_QUESTION   → [UNDERSTAND, EXECUTE_VIA_RUNTIME(text_generation), REFLECT]
    """

    def decompose(self, goal: Goal, skill_matches: list[SkillMatch]) -> list[PlanTask]:
        intent = goal.intent

        # Shared first task for all paths
        understand = self._task(
            title="Understand goal and constraints",
            kind=TaskKind.UNDERSTAND,
            description=f"Interpret the user goal: {goal.summary}",
            goal=goal,
            skills=skill_matches,
            status=TaskStatus.READY,
        )
        tasks: list[PlanTask] = [understand]
        prev_id = understand.task_id

        # ── Intent branch ──────────────────────────────────────────────────

        if intent in (
            GoalIntent.READ_RESOURCE,
            GoalIntent.SEARCH_RESOURCE,
            GoalIntent.DELETE_RESOURCE,
            GoalIntent.MOVE_RESOURCE,
            GoalIntent.COPY_RESOURCE,
            GoalIntent.RENAME_RESOURCE,
            GoalIntent.WRITE_RESOURCE,
        ):
            action_map = {
                GoalIntent.READ_RESOURCE: "read",
                GoalIntent.SEARCH_RESOURCE: "search",
                GoalIntent.DELETE_RESOURCE: "delete",
                GoalIntent.MOVE_RESOURCE: "move",
                GoalIntent.COPY_RESOURCE: "copy",
                GoalIntent.RENAME_RESOURCE: "move",
                GoalIntent.WRITE_RESOURCE: "write",
            }
            action = action_map[intent]
            
            # Support multiple paths delimited by | (produced by GoalParser for WRITE_RESOURCE)
            paths = (goal.target_path or "").split("|") if goal.target_path else [""]
            
            for p in paths:
                args = dict(goal.intent_arguments) or {"path": p.strip()}
                args["path"] = p.strip() or args.get("path", "")
                if intent == GoalIntent.WRITE_RESOURCE and goal.query:
                    args.setdefault("content", goal.query)
                
                resolver_task = self._tool_task(
                    title=f"Resolve and {action} resource: {p.strip() or 'unknown'}",
                    tool="resolver",
                    action=action,
                    args=args,
                    goal=goal,
                    dependencies=[prev_id],
                )
                tasks.append(resolver_task)
                prev_id = resolver_task.task_id

            # Only read and search need LLM summarization; mutations just reflect.
            if intent in (GoalIntent.READ_RESOURCE, GoalIntent.SEARCH_RESOURCE):
                llm_task = self._task(
                    title=f"Reason over {action} results",
                    kind=TaskKind.EXECUTE_VIA_RUNTIME,
                    description=f"Use the {action} output as context to summarize or answer the user request.",
                    goal=goal,
                    skills=skill_matches,
                    dependencies=[prev_id],
                )
                llm_task.execution_action_type = "text_generation"
                tasks.append(llm_task)
                prev_id = llm_task.task_id

        elif intent == GoalIntent.LIST_DIRECTORY:
            list_task = self._tool_task(
                title="List directory contents",
                tool="resolver",
                action="list",
                args={"path": goal.target_path or "."},
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(list_task)
            prev_id = list_task.task_id

        elif intent == GoalIntent.SEARCH_INTERNET:
            search_task = self._tool_task(
                title="Search the internet for current information",
                tool="internet",
                action="search",
                args={"query": goal.query or goal.raw_request},
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(search_task)
            prev_id = search_task.task_id

            llm_task = self._task(
                title="Synthesize verified search results into response",
                kind=TaskKind.EXECUTE_VIA_RUNTIME,
                description=(
                    "Reason over the verified internet search results and the "
                    "user request. Answer only from the provided results and "
                    "attribute every claim to its numbered source."
                ),
                goal=goal,
                skills=skill_matches,
                dependencies=[prev_id],
            )
            llm_task.execution_action_type = "text_generation"
            tasks.append(llm_task)
            prev_id = llm_task.task_id

        elif intent == GoalIntent.SEARCH_MEMORY:
            mem_task = self._tool_task(
                title="Search conversation and skill memory",
                tool="memory",
                action="search",
                args={"query": goal.query or goal.raw_request},
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(mem_task)
            prev_id = mem_task.task_id

            llm_task = self._task(
                title="Synthesize memory results into response",
                kind=TaskKind.EXECUTE_VIA_RUNTIME,
                description="Combine memory results with user request and produce a response.",
                goal=goal,
                skills=skill_matches,
                dependencies=[prev_id],
            )
            llm_task.execution_action_type = "text_generation"
            tasks.append(llm_task)
            prev_id = llm_task.task_id

        elif intent == GoalIntent.DELETE_MEMORY:
            action, args = self._detect_memory_delete(goal)
            delete_task = self._tool_task(
                title=f"Delete memory ({action})",
                tool="memory",
                action=action,
                args=args,
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(delete_task)
            prev_id = delete_task.task_id

        elif intent == GoalIntent.RUN_COMMAND:
            shell_task = self._tool_task(
                title="Execute shell command",
                tool=None,
                capability="shell_exec",
                domain="shell",
                action="run",
                args=dict(goal.intent_arguments),
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(shell_task)
            prev_id = shell_task.task_id

        elif intent == GoalIntent.CLIPBOARD:
            clipboard_task = self._tool_task(
                title="Interact with the system clipboard",
                tool=None,
                capability=self._detect_clipboard_capability(goal.raw_request),
                domain="clipboard",
                action=goal.intent_action or self._detect_clipboard_action(goal.raw_request),
                args=dict(goal.intent_arguments),
                goal=goal,
                dependencies=[prev_id],
                policy_action=(
                    "write" if (goal.intent_action or self._detect_clipboard_action(goal.raw_request)) == "write" else "read"
                ),
            )
            tasks.append(clipboard_task)
            prev_id = clipboard_task.task_id

        elif intent == GoalIntent.SEND_NOTIFICATION:
            notification_task = self._tool_task(
                title="Send desktop notification",
                tool=None,
                capability="notify",
                domain="notification",
                action="send",
                args=dict(goal.intent_arguments),
                goal=goal,
                dependencies=[prev_id],
                policy_action="write",
            )
            tasks.append(notification_task)
            prev_id = notification_task.task_id

        elif intent == GoalIntent.OPERATE_WINDOWS:
            windows_task = self._tool_task(
                title="Execute Windows system operation",
                tool="windows",
                action=self._detect_windows_action(goal.raw_request),
                args={"query": goal.query or goal.raw_request},
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(windows_task)
            prev_id = windows_task.task_id

        elif intent in {
            GoalIntent.MANAGE_REMINDER,
            GoalIntent.MANAGE_NOTE,
            GoalIntent.MANAGE_TASK,
            GoalIntent.MANAGE_CONTACT,
            GoalIntent.SEARCH_CONTACT,
            GoalIntent.MANAGE_CALENDAR,
            GoalIntent.SEND_EMAIL,
            GoalIntent.READ_EMAIL,
            GoalIntent.REPLY_EMAIL,
            GoalIntent.FORWARD_EMAIL,
            GoalIntent.SEND_MESSAGE,
            GoalIntent.READ_MESSAGES,
            GoalIntent.SEARCH_MESSAGES,
        }:
            route_map = {
                GoalIntent.MANAGE_REMINDER: ("reminder", "Manage reminder"),
                GoalIntent.MANAGE_NOTE: ("note", "Manage note"),
                GoalIntent.MANAGE_TASK: ("task", "Manage task"),
                GoalIntent.MANAGE_CONTACT: ("contact", "Manage contact"),
                GoalIntent.SEARCH_CONTACT: ("contact", "Search contacts"),
                GoalIntent.MANAGE_CALENDAR: ("calendar", "Manage local calendar"),
                GoalIntent.SEND_EMAIL: ("email", "Prepare simulated email action"),
                GoalIntent.READ_EMAIL: ("email", "Read local email simulation state"),
                GoalIntent.REPLY_EMAIL: ("email", "Prepare simulated email reply"),
                GoalIntent.FORWARD_EMAIL: ("email", "Prepare simulated email forward"),
                GoalIntent.SEND_MESSAGE: ("message", "Prepare simulated message action"),
                GoalIntent.READ_MESSAGES: ("message", "Read local message simulation state"),
                GoalIntent.SEARCH_MESSAGES: ("message", "Search local message simulation state"),
            }
            domain, title = route_map[intent]
            action = goal.intent_action or ""
            routed = self._tool_task(
                title=title,
                tool=None,
                domain=domain,
                capability=domain,
                action=action,
                args=dict(goal.intent_arguments),
                goal=goal,
                dependencies=[prev_id],
                policy_action=(
                    "write"
                    if domain in {"email", "message"}
                    and action in {"send", "reply", "forward", "draft", "compose"}
                    else None
                ),
            )
            tasks.append(routed)
            prev_id = routed.task_id

        else:
            # ANSWER_QUESTION, GENERATE_CODE, and any unmatched intent
            if goal.requires_long_context:
                ctx_task = self._task(
                    title="Retrieve relevant context",
                    kind=TaskKind.RETRIEVE_CONTEXT,
                    description="Request relevant context through memory or retrieval systems.",
                    goal=goal,
                    skills=skill_matches,
                    dependencies=[prev_id],
                )
                tasks.append(ctx_task)
                prev_id = ctx_task.task_id

            llm_task = self._task(
                title="Generate LLM response",
                kind=TaskKind.EXECUTE_VIA_RUNTIME,
                description="Call the language model to produce a direct answer.",
                goal=goal,
                skills=skill_matches,
                dependencies=[prev_id],
            )
            llm_task.execution_action_type = "text_generation"
            tasks.append(llm_task)
            prev_id = llm_task.task_id

        # ── Optional verify for complex goals ────────────────────────────
        if goal.complexity in {GoalComplexity.MEDIUM, GoalComplexity.HIGH}:
            verify = self._task(
                title="Verify plan completeness",
                kind=TaskKind.VERIFY,
                description="Check dependencies, missing context, and expected outputs.",
                goal=goal,
                skills=skill_matches,
                dependencies=[prev_id],
            )
            tasks.append(verify)
            prev_id = verify.task_id

        # ── Always reflect ─────────────────────────────────────────────
        reflect = self._task(
            title="Reflect on plan outcome",
            kind=TaskKind.REFLECT,
            description="Summarize lessons after runtime reports task outcomes.",
            goal=goal,
            skills=skill_matches,
            dependencies=[prev_id],
        )
        tasks.append(reflect)

        log.info("TaskDecomposer: %d tasks created", len(tasks))
        return tasks

    # ── Helper factories ─────────────────────────────────────────────────

    def _task(
        self,
        title: str,
        kind: TaskKind,
        description: str,
        goal: Goal,
        skills: list[SkillMatch],
        dependencies: list[str] | None = None,
        status: TaskStatus = TaskStatus.PENDING,
    ) -> PlanTask:
        return PlanTask(
            task_id=f"task-{uuid4()}",
            title=title,
            kind=kind,
            description=description,
            dependencies=dependencies or [],
            suggested_skills=[
                match.skill.skill_id
                for match in skills
                if kind in match.skill.task_kinds
            ],
            router_request=self._router_request(goal, kind),
            cap_required=True,
            status=status,
        )

    def _tool_task(
        self,
        title: str,
        tool: str | None,
        action: str,
        args: dict,
        goal: Goal,
        dependencies: list[str] | None = None,
        capability: str | None = None,
        domain: str | None = None,
        policy_action: str | None = None,
    ) -> PlanTask:
        """Create a tool execution task that routes through ToolExecutor.

        When ``tool`` is None the task carries a capability/domain hint and
        the Planner resolves the concrete tool id through the ToolSelector —
        selection is data-driven, never hardcoded.
        """
        metadata: dict = {
            "tool": tool,
            "action": action,
            "args": args,
        }
        if capability:
            metadata["capability"] = capability
        if domain:
            metadata["domain"] = domain
        if policy_action:
            metadata["policy_action"] = policy_action
        task = PlanTask(
            task_id=f"task-{uuid4()}",
            title=title,
            kind=TaskKind.EXECUTE_VIA_RUNTIME,
            description=f"{tool or domain or capability}:{action} — {title}",
            dependencies=dependencies or [],
            cap_required=True,
            status=TaskStatus.PENDING,
            execution_action_type="tool",
            metadata=metadata,
        )
        log.info("TaskDecomposer: created task — tool=%s action=%s args=%s", tool or domain, action, args)
        return task

    @staticmethod
    def _detect_clipboard_capability(request: str) -> str:
        lowered = request.lower()
        if any(kw in lowered for kw in ("copy", "set", "put", "write", "save", "paste ")):
            return "clipboard_write"
        return "clipboard_read"

    @staticmethod
    def _detect_clipboard_action(request: str) -> str:
        lowered = request.lower()
        if any(kw in lowered for kw in ("copy", "set", "put", "write", "save", "paste ")):
            return "write"
        return "read"

    @staticmethod
    def _detect_windows_action(request: str) -> str:
        lowered = request.lower()
        if "process" in lowered:
            return "processes"
        if "clipboard" in lowered:
            return "clipboard_get"
        return "terminal"

    @staticmethod
    def _detect_memory_delete(goal: Goal) -> tuple[str, dict]:
        """Map a DELETE_MEMORY goal to a deterministic MemoryTool action.

        Pure string matching over the raw request; never an LLM. Targets:
            delete_all      — "forget everything about me"
            delete_session  — "delete this session" (folder + index + exports)
            delete_type     — preferences, conversation, project, ...
            delete          — a single matching memory ("forget my IDE preference")
        """
        lowered = goal.raw_request.lower()

        if any(phrase in lowered for phrase in (
            "forget everything",
            "forget all about me",
            "forget about me",
            "forget me",
            "delete all memories",
            "delete all memory",
            "delete all my data",
            "erase all data",
            "wipe all data",
            "wipe my memory",
            "erase my memory",
            "clear my memory",
            "clear memory",
            "delete all my memories",
            "delete my memories",
        )):
            return "delete_all", {}

        if any(phrase in lowered for phrase in (
            "delete this session",
            "forget this session",
            "clear my session",
            "delete my session",
            "forget my session",
        )):
            return "delete_session", {"session_id": ""}

        if "preference" in lowered or "preferences" in lowered:
            if any(phrase in lowered for phrase in (
                "delete all preferences",
                "forget all preferences",
                "remove all preferences",
            )):
                return "delete_type", {"memory_type": "preference"}
            if any(phrase in lowered for phrase in (
                "my ide preference",
                "my ide preferences",
                "ide preference",
                "editor preference",
                "tool preference",
            )):
                return "delete", {"memory_type": "preference", "query": "ide"}
            if "forget my" in lowered or "delete my" in lowered or "remove my" in lowered:
                query = lowered.replace("forget my", "").replace("delete my", "").replace("remove my", "").strip(" .!")
                return "delete", {"memory_type": "preference", "query": query}
            return "delete_type", {"memory_type": "preference"}

        if "discussion" in lowered or "conversation" in lowered:
            return "delete_type", {"memory_type": "conversation"}

        if "history" in lowered:
            return "delete_type", {"memory_type": "conversation"}

        if "project" in lowered:
            return "delete_type", {"memory_type": "knowledge", "query": "project"}

        return "delete_all", {}

    @staticmethod
    def _router_request(goal: Goal, kind: TaskKind) -> RouterRequest:
        return RouterRequest(
            purpose=f"{kind.value}: {goal.summary}",
            complexity=goal.complexity,
            estimated_context_tokens=goal.estimated_context_tokens,
            requires_local_model=goal.requires_local_model,
            requires_code=goal.requires_code,
            requires_reasoning=goal.complexity == GoalComplexity.HIGH,
        )
