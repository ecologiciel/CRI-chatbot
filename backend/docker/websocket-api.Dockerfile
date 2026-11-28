# Apply the WebSocket cleanup fix to the currently deployed API image.
ARG BASE_IMAGE=chatbot-demo-api:proxyip-v1
FROM ${BASE_IMAGE}
COPY --chown=cri:cri backend/app/api/ws/escalation_ws.py /app/app/api/ws/escalation_ws.py
