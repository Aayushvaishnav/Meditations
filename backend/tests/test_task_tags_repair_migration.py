import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from app import migrations
from app.migrations.task_null_tags import migrate_task_null_tags


def test_upgrade_repairs_only_json_null_tags_and_is_idempotent():
    async def check():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                for migration in migrations.MIGRATIONS[:16]:
                    await migration(conn)
                await conn.exec_driver_sql("PRAGMA user_version = 16")
                for task_id, tags in [
                    ("broken", "null"), ("whitespace", " null \n"),
                    ("empty", "[]"), ("tagged", '["keep"]'),
                    ("string", '"null"'), ("null_element", "[null]"),
                    ("malformed", "not json"),
                ]:
                    await conn.exec_driver_sql(
                        "INSERT INTO tasks (id,title,priority,status,actual_minutes,tags,order_index,created_at,updated_at) "
                        "VALUES (?, 'Keep', 2, 'in_progress', 0, ?, 1000, '2026-11-01', '2026-11-02')",
                        (task_id, tags),
                    )
                before = (await conn.exec_driver_sql("SELECT * FROM tasks ORDER BY id")).mappings().all()
            await migrations.migrate(engine)
            async with engine.connect() as conn:
                after = (await conn.exec_driver_sql("SELECT * FROM tasks ORDER BY id")).mappings().all()
                assert [dict(row) for row in after] == [
                    {**row, "tags": "[]" if row["id"] in {"broken", "whitespace"} else row["tags"]}
                    for row in before
                ]
                assert (await conn.exec_driver_sql("PRAGMA user_version")).scalar_one() == migrations.LATEST_VERSION
            async with engine.begin() as conn:
                await migrate_task_null_tags(conn)
                assert (await conn.exec_driver_sql("SELECT * FROM tasks ORDER BY id")).mappings().all() == after
            await migrations.migrate(engine)
            async with engine.connect() as conn:
                assert (await conn.exec_driver_sql("SELECT * FROM tasks ORDER BY id")).mappings().all() == after
        finally:
            await engine.dispose()

    asyncio.run(check())
