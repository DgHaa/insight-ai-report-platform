"""报告访问权限控制（依据设计文档权限矩阵）。

- 超级管理员：可见/管理所有报告；
- 部门管理员：可见本部门所有报告，可管理本部门报告；
- 普通用户：仅可见/管理自己的报告、本部门报告与公开报告。
"""
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import Report, User


async def load_report_or_404(db, report_id) -> Report:
    """加载报告，不存在或已软删除时抛出 1004。"""
    report = await db.get(Report, report_id)
    if report is None or not report.is_active:
        raise NotFoundError("报告不存在")
    return report


def can_view(report: Report, user: User) -> bool:
    """是否可查看报告（读取权限）。"""
    if user.role == "super_admin":
        return True
    if report.owner_id == user.id:
        return True
    if (
        report.department_id
        and user.department_id
        and report.department_id == user.department_id
    ):
        return True
    if report.is_public:
        return True
    return False


def can_manage(report: Report, user: User) -> bool:
    """是否可管理报告（修改/删除/生成/回滚权限）。"""
    if user.role == "super_admin":
        return True
    if report.owner_id == user.id:
        return True
    if (
        user.role == "dept_admin"
        and report.department_id
        and user.department_id
        and report.department_id == user.department_id
    ):
        return True
    return False


def can_edit(report: Report, user: User) -> bool:
    """是否可编辑报告（严格所有权隔离：仅报告创建者可编辑配置 / 触发生成 /
    回滚版本 / 删除报告）。

    部门管理员与超级管理员保留查看全部门/全部报告的权限，但**不可编辑
    非本人创建的报告**（写操作一律校验 owner_id）。
    """
    return report.owner_id is not None and report.owner_id == user.id


def ensure_can_edit(report: Report, user: User) -> None:
    """写操作（更新/生成/回滚/删除）鉴权：仅报告所有者可通过。"""
    if not can_edit(report, user):
        raise PermissionDeniedError("无权限操作此报告，仅报告所有者可执行该操作")


def ensure_can_view(report: Report, user: User) -> None:
    if not can_view(report, user):
        raise PermissionDeniedError("无权访问该报告")


def ensure_can_manage(report: Report, user: User) -> None:
    if not can_manage(report, user):
        raise PermissionDeniedError("无权管理该报告")
