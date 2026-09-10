"""ORM 模型注册入口。

导入本包即可将全部 11 张表的模型注册到 Base.metadata，
供 Alembic autogenerate、迁移与业务代码复用。
"""
from app.models.department import Department
from app.models.department_model_config import DepartmentModelConfig
from app.models.email_task import EmailTask
from app.models.generation_task import GenerationTask
from app.models.global_email_whitelist import GlobalEmailWhitelist
from app.models.model_cost_log import ModelCostLog
from app.models.operation_log import OperationLog
from app.models.report import Report
from app.models.report_style import ReportStyle
from app.models.report_version import ReportVersion
from app.models.system_config import SystemConfig
from app.models.user import User
from app.models.user_data_source_credential import UserDataSourceCredential

__all__ = [
    "Department",
    "DepartmentModelConfig",
    "User",
    "Report",
    "ReportStyle",
    "ReportVersion",
    "GenerationTask",
    "UserDataSourceCredential",
    "EmailTask",
    "ModelCostLog",
    "GlobalEmailWhitelist",
    "OperationLog",
    "SystemConfig",
]
