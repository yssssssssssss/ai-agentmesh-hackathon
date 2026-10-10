from __future__ import annotations

import httpx

from agentmesh.runner_contracts import (
    RunnerArtifactUploadRequest,
    RunnerArtifactUploadResponse,
    RunnerCancellationRequest,
    RunnerCapabilitiesV1,
    RunnerCompletionRequest,
    RunnerCompletionRequestV2,
    RunnerDispatchClaimResponse,
    RunnerDispatchResultResponse,
    RunnerEventBatchRequest,
    RunnerEventBatchResponse,
    RunnerExecutionEnvelope,
    RunnerExecutionEventV1,
    RunnerFailureRequest,
    RunnerHeartbeatResponse,
    RunnerLeaseRenewResponse,
    RunnerModelDeliveryRequestV1,
    RunnerModelHandoffRequestV1,
    RunnerNodeCompletionRequest,
    RunnerNodeCompletionRequestV2,
    RunnerToolHandoffRequestV1,
)


class RunnerControlPlaneClient:
    def __init__(self, server_url: str, token: str, *, timeout: float = 30.0):
        self.server_url = server_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RunnerControlPlaneClient:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def heartbeat(self, capabilities: RunnerCapabilitiesV1) -> RunnerHeartbeatResponse:
        response = self._client.post(
            f"{self.server_url}/api/runner/heartbeat",
            json={"capabilities": capabilities.model_dump(mode="json")},
        )
        response.raise_for_status()
        return RunnerHeartbeatResponse.model_validate(response.json())

    def claim(self, capabilities: RunnerCapabilitiesV1) -> RunnerExecutionEnvelope | None:
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/claim",
            json={"capabilities": capabilities.model_dump(mode="json")},
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return RunnerDispatchClaimResponse.model_validate(response.json()).envelope

    def renew(self, lease_id: str) -> RunnerLeaseRenewResponse:
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/{lease_id}/renew",
        )
        response.raise_for_status()
        return RunnerLeaseRenewResponse.model_validate(response.json())

    def authorize_model_handoff(self, lease_id: str, request: RunnerModelHandoffRequestV1) -> str:
        response = self._client.post(f'{self.server_url}/api/runner/dispatches/{lease_id}/model-handoffs',
                                     json=request.model_dump(mode='json'))
        response.raise_for_status()
        return response.json()['handoff_id']

    def confirm_model_handoff(self, lease_id: str, request: RunnerModelDeliveryRequestV1) -> dict:
        response = self._client.post(f'{self.server_url}/api/runner/dispatches/{lease_id}/model-deliveries',
                                     json=request.model_dump(mode='json'))
        response.raise_for_status()
        return response.json()

    def authorize_tool_handoff(self, lease_id: str, request: RunnerToolHandoffRequestV1) -> str:
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/{lease_id}/tool-handoffs",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return response.json()["handoff_id"]

    def append_events(
        self,
        lease_id: str,
        events: list[RunnerExecutionEventV1],
    ) -> RunnerEventBatchResponse:
        request = RunnerEventBatchRequest(events=events)
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/{lease_id}/events",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RunnerEventBatchResponse.model_validate(response.json())

    def complete_node(
        self,
        lease_id: str,
        request: RunnerNodeCompletionRequest | RunnerNodeCompletionRequestV2,
    ) -> RunnerDispatchResultResponse:
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/{lease_id}/node-complete",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RunnerDispatchResultResponse.model_validate(response.json())

    def fail_node(
        self,
        lease_id: str,
        request: RunnerFailureRequest,
    ) -> RunnerDispatchResultResponse:
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/{lease_id}/node-fail",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RunnerDispatchResultResponse.model_validate(response.json())

    def upload_artifact(
        self,
        lease_id: str,
        request: RunnerArtifactUploadRequest,
    ) -> RunnerArtifactUploadResponse:
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/{lease_id}/artifacts",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RunnerArtifactUploadResponse.model_validate(response.json())

    def complete(
        self,
        lease_id: str,
        request: RunnerCompletionRequest | RunnerCompletionRequestV2,
    ) -> RunnerDispatchResultResponse:
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/{lease_id}/complete",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RunnerDispatchResultResponse.model_validate(response.json())

    def acknowledge_cancelled(
        self,
        lease_id: str,
        request: RunnerCancellationRequest,
    ) -> RunnerDispatchResultResponse:
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/{lease_id}/cancelled",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RunnerDispatchResultResponse.model_validate(response.json())

    def fail(
        self,
        lease_id: str,
        request: RunnerFailureRequest,
    ) -> RunnerDispatchResultResponse:
        response = self._client.post(
            f"{self.server_url}/api/runner/dispatches/{lease_id}/fail",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RunnerDispatchResultResponse.model_validate(response.json())
