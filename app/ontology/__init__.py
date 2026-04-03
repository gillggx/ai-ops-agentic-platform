"""
Ontology 層 - 業務邏輯

本層負責：
- ORM 模型定義 (models/)
- Pydantic 數據驗證 (schemas/)
- 業務邏輯服務 (services/)
- 業務規則引擎 (rules/)

特點：
- 零 Agent 依賴
- 零 Ops 依賴
- 完全獨立，可單獨測試和部署
"""

from .services import (
    UserService,
)

__all__ = [
    "UserService",
]
