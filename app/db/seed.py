"""数据库初始化种子数据。

创建内容：
1. 11 个部门（按设计文档《1.2 用户角色与权限 - 部门列表》）；
2. 1 个超级管理员：admin / Admin@2026（邮箱 admin@insight.local）；
3. 每个部门的默认部门管理员占位账号：dept_admin_<code> / Dept@2026
   （邮箱 dept_admin_<code>@insight.local）。

幂等设计：脚本可重复执行；已存在的数据会被更新为期望值（部门名称/描述、
角色、归属部门等），不存在则插入。
"""
import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.db.security import hash_password, verify_password
from app.db.session import SessionLocal, engine
from app.models import Department, User
from app.models.user import UserRole

# ---------------- 账号常量 ----------------

SUPER_ADMIN_USERNAME = "admin"
SUPER_ADMIN_PASSWORD = "Admin@2026"
SUPER_ADMIN_EMAIL = "admin@insight.local"

DEPT_ADMIN_DEFAULT_PASSWORD = "Dept@2026"  # 占位账号默认密码，首次登录后请立即修改
DEPT_ADMIN_EMAIL_DOMAIN = "insight.local"

# ---------------- 11 个部门（与设计文档一致） ----------------

DEFAULT_DEPARTMENTS: list[dict[str, str]] = [
    {"code": "care", "name": "Care业务部[终端BG]", "description": "终端BG Care业务部"},
    {"code": "service_quality", "name": "服务质量与运营官[终端BG]", "description": "终端BG服务质量与运营管理"},
    {"code": "iot_service", "name": "IoT产品服务部[终端BG]", "description": "IoT产品服务与支持"},
    {"code": "tablet_pc_service", "name": "平板与PC产品服务部[终端BG]", "description": "平板与PC产品服务与支持"},
    {"code": "global_hrd", "name": "全球服务部HRD[终端BG]", "description": "全球服务人力资源开发"},
    {"code": "mobile_service", "name": "手机产品服务部[终端BG]", "description": "手机产品服务与支持"},
    {"code": "bg_spare_parts", "name": "终端BG备件管理部", "description": "终端BG备件计划与管理"},
    {"code": "bg_mkt_solution", "name": "终端BG服务MKT与解决方案销售部", "description": "服务营销与解决方案销售"},
    {"code": "bg_finance", "name": "终端BG服务财经管理部", "description": "服务财经管理与核算"},
    {"code": "bg_online_service", "name": "终端BG线上服务部", "description": "线上服务渠道运营"},
    {"code": "reserved", "name": "（预留扩展）", "description": "预留部门，用于未来组织扩展"},
]


def dept_admin_username(code: str) -> str:
    return f"dept_admin_{code}"


def dept_admin_email(code: str) -> str:
    return f"{dept_admin_username(code)}@{DEPT_ADMIN_EMAIL_DOMAIN}"


async def _seed_departments(session) -> dict[str, Department]:
    """按 code 幂等写入 11 个部门，返回 {code: Department}。"""
    dept_map: dict[str, Department] = {}
    for item in DEFAULT_DEPARTMENTS:
        dept = await session.scalar(select(Department).where(Department.code == item["code"]))
        if dept is None:
            dept = Department(
                name=item["name"], code=item["code"], description=item["description"]
            )
            session.add(dept)
            await session.flush()
            print(f"[seed] 创建部门: {item['code']} - {item['name']}")
        else:
            dept.name = item["name"]
            dept.description = item["description"]
            dept.is_active = True
            print(f"[seed] 更新部门: {item['code']} - {item['name']}")
        dept_map[item["code"]] = dept
    return dept_map


async def _seed_super_admin(session) -> None:
    """写入超级管理员 admin / Admin@2026。"""
    admin = await session.scalar(select(User).where(User.username == SUPER_ADMIN_USERNAME))
    if admin is None:
        admin = User(
            username=SUPER_ADMIN_USERNAME,
            email=SUPER_ADMIN_EMAIL,
            password_hash=hash_password(SUPER_ADMIN_PASSWORD),
            role=UserRole.SUPER_ADMIN.value,
            is_active=True,
        )
        session.add(admin)
        await session.flush()
        print(f"[seed] 创建超级管理员: {SUPER_ADMIN_USERNAME}")
    else:
        admin.role = UserRole.SUPER_ADMIN.value
        admin.is_active = True
        if not verify_password(SUPER_ADMIN_PASSWORD, admin.password_hash):
            admin.password_hash = hash_password(SUPER_ADMIN_PASSWORD)
        print(f"[seed] 更新超级管理员: {SUPER_ADMIN_USERNAME}")


async def _seed_dept_admins(session, dept_map: dict[str, Department]) -> None:
    """为每个部门写入默认部门管理员占位账号，并关联 departments.admin_id。"""
    for code, dept in dept_map.items():
        username = dept_admin_username(code)
        email = dept_admin_email(code)

        admin = await session.scalar(select(User).where(User.username == username))
        if admin is None:
            admin = User(
                username=username,
                email=email,
                password_hash=hash_password(DEPT_ADMIN_DEFAULT_PASSWORD),
                role=UserRole.DEPT_ADMIN.value,
                department_id=dept.id,
                is_active=True,
            )
            session.add(admin)
            await session.flush()
            print(f"[seed] 创建部门管理员占位账号: {username}")
        else:
            admin.role = UserRole.DEPT_ADMIN.value
            admin.department_id = dept.id
            admin.is_active = True
            print(f"[seed] 更新部门管理员占位账号: {username}")

        # 关联部门管理员（循环外键的 departments.admin_id 一侧）
        dept.admin_id = admin.id


async def run_seed() -> None:
    """执行种子数据写入。"""
    print(f"[seed] 连接数据库: {settings.DATABASE_URL}")
    async with SessionLocal() as session:
        dept_map = await _seed_departments(session)
        await _seed_super_admin(session)
        await _seed_dept_admins(session, dept_map)
        await session.commit()
        print("[seed] 已提交事务 ✅")
    await engine.dispose()
    print("[seed] 种子数据初始化完成 ✅")


if __name__ == "__main__":
    asyncio.run(run_seed())

