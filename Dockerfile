FROM public.ecr.aws/lambda/python:3.13

COPY *.py ${LAMBDA_TASK_ROOT}/

CMD ["app.lambda_handler"]
