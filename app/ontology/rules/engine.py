"""
Business Rules Engine

业务规则引擎。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class Rule(ABC):
    """
    Base class for business rules.
    
    业务规则的基类。
    
    A rule encapsulates a business logic check or operation.
    """

    @abstractmethod
    def validate(self, data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate data against the rule.
        
        Args:
            data: Dictionary of data to validate
        
        Returns:
            tuple: (is_valid, error_message)
        
        验证数据。
        """
        pass

    @abstractmethod
    def apply(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply the rule transformation to data.
        
        Args:
            data: Dictionary of data
        
        Returns:
            Dict: Transformed data
        
        应用规则转换。
        """
        pass


class RuleEngine:
    """
    Business rules engine for executing validation rules.
    
    业务规则引擎。
    
    Manages:
    - Rule registration
    - Rule validation
    - Error collection
    - Rule execution order
    
    用途:
    - 规则注册
    - 规则验证
    - 错误收集
    - 规则执行顺序
    
    Example:
        engine = RuleEngine()
        engine.register_rule(PasswordStrengthRule())
        engine.register_rule(EmailFormatRule())
        
        is_valid, errors = engine.validate({"password": "weak"})
        if not is_valid:
            print(errors)
    """

    def __init__(self):
        """Initialize the rule engine."""
        self._rules: List[Rule] = []
        self._rule_names: Dict[str, Rule] = {}

    def register_rule(
        self,
        rule: Rule,
        name: Optional[str] = None,
    ) -> None:
        """
        Register a new rule.
        
        Args:
            rule: Rule - The rule to register
            name: Optional[str] - Rule name (defaults to class name)
        
        注册规则。
        """
        rule_name = name or rule.__class__.__name__
        self._rules.append(rule)
        self._rule_names[rule_name] = rule

    def unregister_rule(self, name: str) -> None:
        """
        Unregister a rule.
        
        Args:
            name: str - Rule name
        
        Raises:
            KeyError: If rule not found
        
        注销规则。
        """
        if name not in self._rule_names:
            raise KeyError(f"Rule '{name}' not found")

        rule = self._rule_names[name]
        self._rules.remove(rule)
        del self._rule_names[name]

    def validate(
        self,
        data: Dict[str, Any],
        stop_on_error: bool = False,
    ) -> tuple[bool, List[str]]:
        """
        Validate data against all registered rules.
        
        Args:
            data: Dict - Data to validate
            stop_on_error: bool - Stop on first error
        
        Returns:
            tuple: (is_valid, error_messages)
        
        验证数据。
        """
        errors: List[str] = []

        for rule in self._rules:
            is_valid, error_msg = rule.validate(data)
            if not is_valid:
                if error_msg:
                    errors.append(error_msg)
                if stop_on_error:
                    break

        return len(errors) == 0, errors

    def apply_rules(
        self,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Apply all rules to transform data.
        
        Args:
            data: Dict - Data to transform
        
        Returns:
            Dict - Transformed data
        
        应用所有规则。
        """
        result = data.copy()

        for rule in self._rules:
            result = rule.apply(result)

        return result

    def get_rule(self, name: str) -> Optional[Rule]:
        """
        Get a registered rule by name.
        
        Args:
            name: str - Rule name
        
        Returns:
            Rule or None - The rule or None
        
        获取规则。
        """
        return self._rule_names.get(name)

    def list_all_rules(self) -> List[str]:
        """
        List all registered rule names.
        
        Returns:
            List[str] - Rule names
        
        列出所有规则。
        """
        return list(self._rule_names.keys())

    def __len__(self) -> int:
        """Return number of registered rules."""
        return len(self._rules)

    def __repr__(self) -> str:
        """Return detailed representation."""
        return f"RuleEngine(rules={len(self._rules)})"
