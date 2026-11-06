import json

import pytest

from app import agents


def events(response):
    return [(chunk.splitlines()[0][7:], json.loads(chunk.splitlines()[1][6:]))
            for chunk in response.text.strip().split("\n\n")]


@pytest.mark.parametrize("stream", [False, True])
def test_task_references(client, monkeypatch, stream):
    first = client.post('/api/tasks', json={'title': 'Same', 'due_date': '2020-01-01T10:00:00'}).json()
    second = client.post('/api/tasks', json={'title': 'Same', 'due_date': '2020-01-01T10:00:00'}).json()
    client.patch(f"/api/tasks/{second['id']}", json={'title': 'Renamed'})

    def result(data):
        candidates = {task['id']: task for task in data['overdue_tasks']}
        assert candidates[first['id']]['status'] == 'todo'
        assert candidates[second['id']]['title'] == 'Renamed'
        assert data['open_tasks_total'] == 2
        return agents.BriefingOutput(
            top_focus=['Do it', 'Unknown', 'General', 'Extra'],
            recommendations=[
                agents.BriefingRecommendation(text='Do it', task_id=second['id']),
                agents.BriefingRecommendation(text='Unknown', task_id='invented'),
                agents.BriefingRecommendation(text='General'),
            ],
        )

    async def run(data, **kwargs):
        return result(data)

    async def streaming(data, **kwargs):
        yield result(data)

    monkeypatch.setattr(agents, 'run_briefing', run)
    monkeypatch.setattr(agents, 'stream_briefing', streaming)
    response = client.post('/api/agents/briefing' + ('/stream' if stream else ''))
    assert response.status_code == 200
    bodies = [body for event, body in events(response)] if stream else [response.json()]
    for body in bodies:
        assert body['recommendations'] == [
            {'text': 'Do it', 'task_id': second['id']},
            {'text': 'Unknown', 'task_id': None},
            {'text': 'General', 'task_id': None},
        ]


@pytest.mark.parametrize('stream', [False, True])
def test_legacy_and_misaligned_recommendations(client, monkeypatch, stream):
    async def run(data, **kwargs):
        return agents.BriefingOutput(top_focus=['Rest'])

    async def streaming(data, **kwargs):
        yield await run(data)

    monkeypatch.setattr(agents, 'run_briefing', run)
    monkeypatch.setattr(agents, 'stream_briefing', streaming)
    response = client.post('/api/agents/briefing' + ('/stream' if stream else ''))
    body = events(response)[-1][1] if stream else response.json()
    assert body['top_focus'] == ['Rest']
    assert body['recommendations'] == [{'text': 'Rest', 'task_id': None}]


@pytest.mark.parametrize('stream', [False, True])
def test_saved_review_followup(client, monkeypatch, stream):
    day = '2026-09-10'
    assert client.get(f'/api/scores/daily/{day}').json()['suggested_action_for_tomorrow'] == ''
    client.put(f'/api/journal/{day}', json={'raw_markdown': 'A day'})
    review = agents.DailyReviewOutput(feedback='Good', suggested_action_for_tomorrow='Call a friend')

    async def run(*args, **kwargs):
        return review

    async def streaming(*args, **kwargs):
        yield review

    monkeypatch.setattr(agents, 'run_daily_review', run)
    monkeypatch.setattr(agents, 'stream_daily_review', streaming)
    path = '/api/agents/rollup/daily' + ('/stream' if stream else '')
    response = client.post(path, params={'day': day})
    body = events(response)[-1][1] if stream else response.json()
    assert body['suggested_action_for_tomorrow'] == 'Call a friend'
    assert client.get(f'/api/scores/daily/{day}').json()['suggested_action_for_tomorrow'] == 'Call a friend'


@pytest.mark.parametrize('rubric', ['{}', '[]', 'null', 'invalid', '{"suggested_action_for_tomorrow": 3}'])
def test_absent_or_invalid_saved_action(rubric):
    from app.schemas import saved_review_action

    assert saved_review_action(rubric) == ''


def test_recommendation_alignment_and_candidate_allowlist():
    from app.ai_orchestration import _briefing_response

    data = {'overdue_tasks': [{'id': 'candidate'}], 'due_today': []}
    review = agents.BriefingOutput(
        top_focus=['First', 'Second', 'Third', 'Fourth'],
        recommendations=[
            agents.BriefingRecommendation(text='Different', task_id='candidate'),
            agents.BriefingRecommendation(text='Second', task_id='not-supplied'),
            agents.BriefingRecommendation(text='Third', task_id='candidate'),
            agents.BriefingRecommendation(text='Fourth', task_id='candidate'),
        ],
    )
    body = _briefing_response(review, data)
    assert body['top_focus'] == ['First', 'Second', 'Third']
    assert body['recommendations'] == [
        {'text': 'First', 'task_id': None},
        {'text': 'Second', 'task_id': None},
        {'text': 'Third', 'task_id': 'candidate'},
    ]
