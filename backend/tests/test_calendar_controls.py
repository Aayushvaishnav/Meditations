"""Public controls exercise durable intent with fake vault and adapter."""
import pytest

from app.calendar_sync.connections import ConnectionFailure
from app.calendar_sync.controls import CalendarControls
from app.calendar_sync.queue_worker import QueueWorker
from app.models import CalendarConnection, CalendarLink, TimeBlock
from test_calendar_outbound import change, env, saved  # noqa: F401
from test_calendar_queue_worker import listing  # noqa: F401

pytestmark = pytest.mark.anyio


def controls(env):
    return CalendarControls(QueueWorker(env.sessions, env.manager))


async def test_pause_preserves_work_and_manual_sync_requires_enablement(env):
    control = controls(env)
    await control.enable(env.connection.id, False)
    with pytest.raises(ConnectionFailure) as error:
        await control.sync_now(env.connection.id)
    assert error.value.status == 409
    assert env.adapter.calls == []
    assert (await control.status(env.connection.id))['queued_count'] == 1
    await control.enable(env.connection.id, True)
    status = await control.sync_now(env.connection.id)
    assert status['queued_count'] == 0
    assert (await saved(env)).state == 'synced'
    assert status['last_success_at'] is not None


async def test_opt_in_only_selected_block_idempotent_and_no_network(env):
    control = controls(env)
    async with env.sessions() as session:
        await session.delete(await session.get(CalendarLink, env.link.id))
        await session.commit()
    first = await control.opt_in(env.connection.id, env.block.id)
    second = await control.opt_in(env.connection.id, env.block.id)
    assert first.id == second.id
    assert first.uid == env.link.uid
    assert first.state == 'pending'
    assert env.adapter.calls == []


async def test_opt_out_published_event_queues_conditional_cleanup_while_paused(env):
    control = controls(env)
    await control.sync_now(env.connection.id)
    success = (await control.status(env.connection.id))['last_success_at']
    await control.enable(env.connection.id, False)
    before = (await saved(env)).local_revision
    result = await control.opt_out(env.connection.id, env.block.id)
    assert result.desired_action == 'delete'
    assert result.local_revision == before + 1
    assert len(env.adapter.resources) == 1
    assert (await control.opt_out(env.connection.id, env.block.id)).local_revision == result.local_revision
    assert (await control.status(env.connection.id))['last_success_at'] == success
    from datetime import datetime
    await change(env, TimeBlock, env.block.id, start_at=datetime(2026, 11, 2, 8))
    assert (await saved(env)).desired_action == 'delete'
    await control.enable(env.connection.id, True)
    await control.sync_now(env.connection.id)
    assert env.adapter.resources == {}
    assert (await saved(env)).state == 'detached'


async def test_detach_conflict_leaves_remote_untouched_and_never_reattaches(env):
    control = controls(env)
    await control.sync_now(env.connection.id)
    await change(env, CalendarLink, env.link.id, state='conflict')
    with pytest.raises(ConnectionFailure):
        await control.opt_out(env.connection.id, env.block.id)
    await control.detach(env.connection.id, env.link.id)
    await control.sync_now(env.connection.id)
    assert len(env.adapter.resources) == 1
    with pytest.raises(ConnectionFailure):
        await control.opt_in(env.connection.id, env.block.id)


@pytest.mark.parametrize('state', ['disconnected', 'authentication_required'])
async def test_authentication_gates_opt_in_enable_and_manual_sync(env, state):
    control = controls(env)
    await change(env, CalendarConnection, env.connection.id, state=state)
    for operation in [control.enable(env.connection.id, True),
                      control.opt_in(env.connection.id, env.block.id),
                      control.sync_now(env.connection.id)]:
        with pytest.raises(ConnectionFailure):
            await operation
    assert env.adapter.calls == []
    await control.enable(env.connection.id, False)
    await control.opt_out(env.connection.id, env.block.id)


async def test_detach_cannot_target_other_connection(env):
    with pytest.raises(ConnectionFailure) as error:
        await controls(env).detach('other', env.link.id)
    assert error.value.status == 404
    assert (await saved(env)).state == 'pending'


async def test_uncertain_create_then_opt_out_reconciles_without_reopt_in(env):
    control = controls(env)
    env.adapter.uncertain = True
    await control.sync_now(env.connection.id)
    assert (await saved(env)).last_synced_at is None
    await control.opt_out(env.connection.id, env.block.id)
    env.adapter.uncertain = False
    await control.sync_now(env.connection.id)
    await control.sync_now(env.connection.id)
    assert env.adapter.resources == {}
    assert (await saved(env)).state == 'detached'


@pytest.mark.parametrize('phase', ['offline', 'acknowledged', 'uncertain_delete'])
async def test_explicit_reopt_in_preserves_identity_and_reconciles_delete(env, phase):
    control = controls(env)
    await control.sync_now(env.connection.id)
    original = await saved(env)
    await control.opt_out(env.connection.id, env.block.id)
    if phase != 'offline':
        env.adapter.uncertain = phase == 'uncertain_delete'
        await control.sync_now(env.connection.id)
        env.adapter.uncertain = False
    before = (await saved(env)).local_revision
    link = await control.opt_in(env.connection.id, env.block.id)
    assert link.uid == original.uid
    assert link.resource_url == original.resource_url
    assert link.local_revision == before + 1
    assert link.desired_action == 'upsert'
    await control.sync_now(env.connection.id)
    await control.sync_now(env.connection.id)
    final = await saved(env)
    assert final.state == 'synced'
    assert final.acknowledged_revision == final.local_revision
    assert len(env.adapter.resources) == 1


async def test_explicit_detach_after_acknowledged_opt_out_cannot_reopt(env):
    control = controls(env)
    await control.sync_now(env.connection.id)
    await control.opt_out(env.connection.id, env.block.id)
    await control.sync_now(env.connection.id)
    assert (await saved(env)).selection_state == 'opted_out'
    await control.detach(env.connection.id, env.link.id)
    assert (await saved(env)).selection_state == 'detached'
    with pytest.raises(ConnectionFailure):
        await control.opt_in(env.connection.id, env.block.id)


async def test_never_attempted_opt_out_then_reopt_is_local_and_preserves_identity(env):
    control = controls(env)
    await control.opt_out(env.connection.id, env.block.id)
    await control.sync_now(env.connection.id)
    assert env.adapter.calls == []
    assert (await saved(env)).state == 'detached'
    link = await control.opt_in(env.connection.id, env.block.id)
    assert link.uid == env.link.uid
    assert link.resource_url == env.link.resource_url
    await control.sync_now(env.connection.id)
    assert (await saved(env)).state == 'synced'
