# Add only the tested proxy boundary to the currently deployed API image.
ARG BASE_IMAGE=chatbot-demo-backend:ed3192b5b1d5ff4e94522eb9de9a5ce1972c04af
FROM ${BASE_IMAGE}
COPY --chown=cri:cri backend/app/core/config.py /app/app/core/config.py
COPY --chown=cri:cri backend/app/core/trusted_proxy.py /app/app/core/trusted_proxy.py
COPY --chown=cri:cri backend/app/main.py /app/app/main.py
