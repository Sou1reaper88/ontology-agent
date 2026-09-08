"""种子数据脚本：初始化默认角色、管理员账号、示例表权限。

用法：.venv/Scripts/python.exe -m scripts.seed
幂等：已存在的数据跳过。
"""

from __future__ import annotations

from auth.jwt import hash_password
from models import Role, TablePermission, User
from models.base import SessionLocal

# 开发默认管理员密码（生产环境需通过环境变量/首次登录修改）
ADMIN_DEFAULT_PASSWORD = "admin123"


def seed() -> None:
    db = SessionLocal()
    try:
        # 默认角色
        admin_role = db.query(Role).filter(Role.name == "全省管理员").first()
        if not admin_role:
            admin_role = Role(name="全省管理员", description="可访问全部本体对象与表")
            db.add(admin_role)

        prod_role = db.query(Role).filter(Role.name == "地市生产岗").first()
        if not prod_role:
            prod_role = Role(name="地市生产岗", description="可访问本业务线常用表")
            db.add(prod_role)

        maintainer_role = db.query(Role).filter(Role.name == "本体维护者").first()
        if not maintainer_role:
            db.add(Role(name="本体维护者", description="可维护本体草稿并执行校验"))
        db.flush()

        # 管理员账号（含密码哈希，开发默认 admin/admin123）
        admin_user = db.query(User).filter(User.username == "admin").first()
        if not admin_user:
            db.add(
                User(
                    username="admin",
                    display_name="系统管理员",
                    password_hash=hash_password(ADMIN_DEFAULT_PASSWORD),
                    role_id=admin_role.id,
                )
            )
        elif not admin_user.password_hash:
            admin_user.password_hash = hash_password(ADMIN_DEFAULT_PASSWORD)

        # 示例表权限（以沉默判断常用表为例）
        sample_perms = [
            {
                "role_id": admin_role.id,
                "table_name": "D_BBZX_DW_PRODUCT_M",
                "ontology_object": "用户统一视图月表",
            },
            {
                "role_id": admin_role.id,
                "table_name": "D_CRM_INS_OFFER_D",
                "ontology_object": "客户订购关系日表",
            },
        ]
        for p in sample_perms:
            exists = (
                db.query(TablePermission)
                .filter(TablePermission.table_name == p["table_name"])
                .first()
            )
            if not exists:
                db.add(
                    TablePermission(
                        role_id=p["role_id"],
                        table_name=p["table_name"],
                        ontology_object=p["ontology_object"],
                        can_query=True,
                        can_execute=True,
                    )
                )

        db.commit()
        print("种子数据写入完成：角色×3、管理员×1、示例表权限×2")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
