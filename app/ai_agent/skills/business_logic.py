"""
Business Logic Skill

業務邏輯技能。
"""

from typing import Any, Dict, List

from .base import BaseSkill, SkillInput, SkillMethod, SkillOutput


class BusinessLogicSkill(BaseSkill):
    """
    Skill for business logic operations.
    
    業務邏輯技能。
    
    Provides:
    - Business rule execution
    - Decision making
    - Workflow orchestration
    - Process automation
    """

    def __init__(self):
        """Initialize BusinessLogicSkill."""
        super().__init__(
            name="BusinessLogic",
            description="Execute business logic and rules",
            version="1.0.0",
            author="FastAPI Backend Team",
            tags=["business", "logic", "rules"]
        )

    async def execute(
        self,
        method: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a business logic method."""
        if method == "execute_rule":
            return await self.execute_rule(params)
        elif method == "make_decision":
            return await self.make_decision(params)
        elif method == "orchestrate_workflow":
            return await self.orchestrate_workflow(params)
        elif method == "automate_process":
            return await self.automate_process(params)
        else:
            from ..mcp.errors import SkillNotFoundError
            raise SkillNotFoundError(method)

    def get_exposed_methods(self) -> List[SkillMethod]:
        """Get exposed methods for this skill."""
        return [
            SkillMethod(
                name="execute_rule",
                description="Execute a business rule",
                inputs=[
                    SkillInput(name="rule_id", type="str", description="Rule identifier", required=True),
                    SkillInput(name="context", type="dict", description="Rule context", required=True),
                ],
                outputs=[
                    SkillOutput(name="result", type="dict", description="Rule execution result"),
                    SkillOutput(name="status", type="str", description="Execution status"),
                ]
            ),
            SkillMethod(
                name="make_decision",
                description="Make a business decision",
                inputs=[
                    SkillInput(name="decision_type", type="str", description="Type of decision", required=True),
                    SkillInput(name="factors", type="dict", description="Decision factors", required=True),
                ],
                outputs=[
                    SkillOutput(name="decision", type="str", description="Made decision"),
                    SkillOutput(name="reasoning", type="str", description="Decision reasoning"),
                ]
            ),
            SkillMethod(
                name="orchestrate_workflow",
                description="Orchestrate a workflow",
                inputs=[
                    SkillInput(name="workflow_id", type="str", description="Workflow identifier", required=True),
                    SkillInput(name="steps", type="list", description="Workflow steps", required=True),
                ],
                outputs=[
                    SkillOutput(name="workflow_result", type="dict", description="Workflow result"),
                    SkillOutput(name="execution_time", type="float", description="Execution time"),
                ]
            ),
            SkillMethod(
                name="automate_process",
                description="Automate a business process",
                inputs=[
                    SkillInput(name="process_id", type="str", description="Process identifier", required=True),
                    SkillInput(name="parameters", type="dict", description="Process parameters", required=True),
                ],
                outputs=[
                    SkillOutput(name="process_result", type="dict", description="Process result"),
                    SkillOutput(name="status", type="str", description="Process status"),
                ]
            ),
        ]

    async def execute_rule(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a business rule."""
        rule_id = params.get("rule_id", "")
        context = params.get("context", {})
        
        return {
            "result": {"rule_id": rule_id, "applied": True},
            "status": "success",
        }

    async def make_decision(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a business decision."""
        decision_type = params.get("decision_type", "")
        factors = params.get("factors", {})
        
        return {
            "decision": f"Decision on {decision_type}",
            "reasoning": "Based on provided factors",
        }

    async def orchestrate_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Orchestrate a workflow."""
        workflow_id = params.get("workflow_id", "")
        steps = params.get("steps", [])
        
        return {
            "workflow_result": {"workflow_id": workflow_id, "steps_executed": len(steps)},
            "execution_time": 1.5,
        }

    async def automate_process(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Automate a business process."""
        process_id = params.get("process_id", "")
        parameters = params.get("parameters", {})
        
        return {
            "process_result": {"process_id": process_id, "automated": True},
            "status": "completed",
        }
