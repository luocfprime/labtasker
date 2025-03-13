# import json
# from datetime import datetime
#
# import pytest
# from httpx_sse import aconnect_sse
# from starlette.status import HTTP_201_CREATED
#
# from labtasker.api_models import (
#     EventResponse,
#     QueueCreateResponse,
#     StateTransitionEvent,
#     TaskSubmitRequest,
# )
# from tests.fixtures.mock_datetime_now import mock_get_current_time
# from tests.fixtures.server import async_test_app
#
#
# @pytest.fixture
# async def setup_queue(async_test_app, queue_create_request):
#     response = await async_test_app.post(
#         "/api/v1/queues", json=queue_create_request.to_request_dict()
#     )
#     assert response.status_code == HTTP_201_CREATED
#     return QueueCreateResponse(**response.json())
#
#
# @pytest.mark.integration
# @pytest.mark.unit
# @pytest.mark.anyio
# async def test_task_state_transition_events(
#     async_test_app, setup_queue, auth_headers, mock_get_current_time
# ):
#     mock_get_current_time.set_current_time(datetime(2025, 1, 1, 0, 0, 0))
#
#     async with aconnect_sse(
#         async_test_app, "GET", "/api/v1/queues/me/events", headers=auth_headers
#     ) as event_source:
#         # Collect initial connection event
#         events = [sse async for sse in event_source.aiter_sse()]
#         connection_event = events[0]
#         assert connection_event.event == "connection"
#         connection_data = json.loads(connection_event.data)
#         assert connection_data["status"] == "connected"
#         assert "client_id" in connection_data
#
#         # Create task
#         response = await async_test_app.post(
#             "/api/v1/queues/me/tasks",
#             headers=auth_headers,
#             json=TaskSubmitRequest(
#                 task_name="test_task",
#                 args={"param1": 1},
#             ).model_dump(),
#         )
#         assert response.status_code == HTTP_201_CREATED
#         task_id = response.json()["task_id"]
#
#         # Collect state transition event
#         events = [sse async for sse in event_source.aiter_sse()]
#         state_event = events[0]
#         assert state_event.event == "event"
#         event = EventResponse(**json.loads(state_event.data))
#         assert isinstance(event.event, StateTransitionEvent)
#         assert event.event.entity_type == "task"
#         assert event.event.old_state == "created"
#         assert event.event.new_state == "pending"
#
#
# @pytest.mark.integration
# @pytest.mark.unit
# @pytest.mark.anyio
# async def test_multiple_clients(async_test_app, setup_queue, auth_headers):
#     events1, events2 = [], []
#
#     # Start first client
#     async with aconnect_sse(
#         async_test_app, "GET", "/api/v1/queues/me/events", headers=auth_headers
#     ) as event_source1:
#         # Wait for first client connection
#         async for sse in event_source1.aiter_sse():
#             if sse.event == "connection":
#                 events1.append(sse)
#                 break
#
#         # Start second client
#         async with aconnect_sse(
#             async_test_app, "GET", "/api/v1/queues/me/events", headers=auth_headers
#         ) as event_source2:
#             # Wait for second client connection
#             async for sse in event_source2.aiter_sse():
#                 if sse.event == "connection":
#                     events2.append(sse)
#                     break
#
#             # Create a task
#             response = await async_test_app.post(
#                 "/api/v1/queues/me/tasks",
#                 headers=auth_headers,
#                 json=TaskSubmitRequest(
#                     task_name="test_task",
#                     args={"param1": 1},
#                 ).model_dump(),
#             )
#             assert response.status_code == HTTP_201_CREATED
#
#             # Collect events from both clients
#             async def collect_event(source, events_list):
#                 async for sse in source.aiter_sse():
#                     if sse.event == "event":
#                         events_list.append(sse)
#                         return
#
#             await collect_event(event_source1, events1)
#             await collect_event(event_source2, events2)
#
#     # Verify both clients received the same event
#     assert len(events1) == len(events2) == 2  # Connection + State transition
#     event1 = EventResponse(**json.loads(events1[1].data))
#     event2 = EventResponse(**json.loads(events2[1].data))
#     assert event1.model_dump() == event2.model_dump()
