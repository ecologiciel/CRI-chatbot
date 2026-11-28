ARG BASE_IMAGE=chatbot-demo-backend:ed3192b5b1d5ff4e94522eb9de9a5ce1972c04af
FROM ${BASE_IMAGE}
COPY --chown=cri:cri backend/app/services/whatsapp/local_relay.py /app/app/services/whatsapp/local_relay.py
USER cri
CMD ["uvicorn", "app.services.whatsapp.local_relay:app", "--host", "0.0.0.0", "--port", "8081", "--no-access-log"]
