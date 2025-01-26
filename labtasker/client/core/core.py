import httpx

from labtasker.api_models import QueueCreateRequest


def health_check() -> dict:
    pass


def create_queue(param: QueueCreateRequest) -> dict:
    with httpx.Client() as client:
        response = client.post(
            "",
            json=param.to_request_dict(),
        )
        response.raise_for_status()
        return response.json()
