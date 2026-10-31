# decision.py
"""TRON's decision contract: what the local brain decided for one request, as a validated object, and how
each step's result is verified.

The model decides by calling tools (natively, through Ollama); code turns that into a Decision: risk, side
effects and whether the user must confirm come from the tool registry, never from the model. It is a concise
summary for the log and the panel, never a reasoning transcript.

Why the model doesn't write this object itself: tested on this laptop (RTX 4070, Qwen3.5-4B) on 42 real
requests, asking for the whole decision as structured JSON on every turn scored 31/42 at a 3.2 s median and
answered "what time is it" with a made-up time; native tool calls scored 37/42 at ~1.1 s. For a voice
assistant that is the difference between snappy and sluggish, so the semantic part stays in tool calls and
the structure is built around them.
"""
import re
import uuid
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DecisionMode(str, Enum):
    ANSWER_DIRECTLY = "answer_directly"
    ASK_CLARIFICATION = "ask_clarification"
    PLAN_ONLY = "plan_only"
    PLAN_AND_EXECUTE = "plan_and_execute"
    EXECUTE_AND_VERIFY = "execute_and_verify"
    REFUSE_OR_REDIRECT = "refuse_or_redirect"


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Intent(BaseModel):
    primary: str
    secondary: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0, le=1)


class Goal(BaseModel):
    statement: str
    success_condition: str


class Risk(BaseModel):
    level: RiskLevel
    external_side_effect: bool
    reversible: bool


class ToolRequirement(BaseModel):
    capability: str
    required: bool = True
    preferred_tool: Optional[str] = None


class PlanStep(BaseModel):
    step_id: str
    objective: str
    required_capability: str
    tool: str
    args: dict = Field(default_factory=dict)
    preconditions: List[str] = Field(default_factory=list)
    expected_result: str = ""
    side_effect: bool = False
    verification_required: bool = True


class Decision(BaseModel):
    request_id: str
    intent: Intent
    goal: Goal
    constraints: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    risk: Risk
    mode: DecisionMode
    requires_confirmation: bool
    reason_codes: List[str] = Field(default_factory=list)
    plan: List[PlanStep] = Field(default_factory=list)
    tool_requirements: List[ToolRequirement] = Field(default_factory=list)
    response_mode: str


class Verification(BaseModel):
    status: str            # verified | partial | retryable | replan | blocked | failed
    confidence: float = 1.0
    evidence: List[str] = Field(default_factory=list)
    goal_progress: float = 0.0
    retryable: bool = False
    replan_required: bool = False
    user_action_required: bool = False


_ORDER = list(RiskLevel)


def from_calls(said: str, calls: list, registry, reply: str = "", request_id: str = "") -> Decision:
    """The Decision for one round of the model's tool calls. calls: [(name, args)]."""
    plan, risks, external, reversible, confirm, caps = [], [RiskLevel.NONE], False, True, False, []
    for i, (name, args) in enumerate(calls, 1):
        meta = registry.get(name)
        cap = meta.capability if meta else "unknown"
        caps.append(cap)
        plan.append(PlanStep(step_id=f"s{i}", objective=f"{name.replace('_', ' ')}", required_capability=cap,
                             tool=name, args=_safe(args), expected_result="the tool reports it was done",
                             side_effect=bool(meta and meta.side_effect)))
        if meta:
            risks.append(RiskLevel(meta.risk))
            external |= meta.external
            reversible &= meta.reversible
            confirm |= meta.requires_confirmation
    if not calls:
        mode = DecisionMode.ASK_CLARIFICATION if reply.rstrip().endswith("?") else DecisionMode.ANSWER_DIRECTLY
    else:
        mode = DecisionMode.PLAN_AND_EXECUTE if len(calls) > 1 else DecisionMode.EXECUTE_AND_VERIFY
    reasons = (["needs_spoken_confirmation"] if confirm else []) + \
              (["external_side_effect"] if external else []) + \
              (["read_only_actions"] if calls and not any(p.side_effect for p in plan) else [])
    response_mode = ("confirmation_required" if confirm else "execution_summary" if calls
                     else "ask_one_question" if mode is DecisionMode.ASK_CLARIFICATION else "concise_answer")
    return Decision(
        request_id=request_id or str(uuid.uuid4()),
        intent=Intent(primary="+".join(dict.fromkeys(caps)) or "conversation"),
        goal=Goal(statement=said, success_condition="every step verified" if calls else "answered"),
        risk=Risk(level=max(risks, key=_ORDER.index), external_side_effect=external, reversible=reversible),
        mode=mode, requires_confirmation=confirm, reason_codes=reasons, plan=plan,
        tool_requirements=[ToolRequirement(capability=p.required_capability, preferred_tool=p.tool) for p in plan],
        response_mode=response_mode)


_SECRET_KEY = re.compile(r"pass|secret|token|api_?key|credential", re.I)


def _safe(args: dict) -> dict:
    """Arguments fit for the log: never a password or a key."""
    return {k: ("***" if _SECRET_KEY.search(k) else v) for k, v in (args or {}).items()}


# A tool reports failure in words ("Spotify didn't open, sir"): these are the words it uses.
_FAILED = re.compile(r"\b(failed|couldn'?t|could not|can'?t|cannot|didn'?t|did not|no result|not found|"
                     r"isn'?t (?:open|running|available)|error|unable|there is no tool)\b", re.I)


def verify(result: str, data: bool) -> Verification:
    """Did the step do what it was for? Decided in code from the tool's own report: tools say plainly when they
    couldn't do something, and nothing counts as done just because a call returned."""
    text = (result or "").strip()
    if text.startswith("NOT DONE") or text.startswith("REFUSED"):
        return Verification(status="blocked", evidence=[text[:160]], user_action_required=True)
    if not text or _FAILED.search(text):
        return Verification(status="replan", confidence=0.8, evidence=[text[:160]], replan_required=True)
    if data:
        # Data for the model to read against the request (a screen listing, a status) before anything is said.
        return Verification(status="partial", evidence=[text[:160]], goal_progress=0.5)
    return Verification(status="verified", evidence=[text[:160]], goal_progress=1.0)
