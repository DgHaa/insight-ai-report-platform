"""密码哈希工具（bcrypt）。

统一在此封装密码哈希与校验，供注册、登录与种子数据脚本复用。
"""
import bcrypt


def hash_password(password: str) -> str:
    """生成 bcrypt 密码哈希。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
